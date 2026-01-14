"""
Billing service layer.

Orchestrates loading usage data from Django models, preparing it for billing,
and calculating bills using the core billing engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
import zoneinfo

import pandas as pd

from billing.adapters import tariff_to_dto
from billing.core.calculator import calculate_monthly_bills
from billing.core.data import (
    GapAnalysis,
    analyze_gaps,
    fill_missing_data,
    validate_usage_dataframe,
)
from billing.core.types import BillingMonthResult
from billing.exceptions import InvalidDateRangeError, NoUsageDataError
from usage.models import CustomerUsage
from utilities.models import Holiday

if TYPE_CHECKING:
    from customers.models import Customer
    from tariffs.models import Tariff
    from utilities.models import Utility


@dataclass
class BillingCalculationResult:
    """Result of a billing calculation."""

    customer: Customer
    tariff: Tariff
    period_start: date
    period_end: date
    billing_months: list[BillingMonthResult]
    billing_df: pd.DataFrame
    warnings: list[str]
    gap_analysis: GapAnalysis | None = None

    @property
    def grand_total_usd(self):
        """Calculate the sum of all monthly totals."""
        from decimal import Decimal

        return sum(
            (month.total_usd for month in self.billing_months), start=Decimal("0")
        )


def get_holiday_dates(
    utility: Utility,
    start_date: date,
    end_date: date,
) -> set[date]:
    """
    Get set of holiday dates for a utility within a date range.

    Args:
        utility: Utility to get holidays for
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)

    Returns:
        Set of holiday dates within the range
    """
    holidays = Holiday.objects.filter(
        utility=utility,
        date__gte=start_date,
        date__lte=end_date,
    ).values_list("date", flat=True)
    return set(holidays)


def determine_day_types(
    df: pd.DataFrame,
    utility: Utility,
    customer_tz: zoneinfo.ZoneInfo,
) -> pd.DataFrame:
    """
    Add is_weekday, is_weekend, is_holiday columns to DataFrame.

    Uses utility's holiday list to determine holidays.

    Args:
        df: DataFrame with interval_start column (timezone-aware)
        utility: Utility for holiday lookup
        customer_tz: Customer's timezone

    Returns:
        DataFrame with added day type columns
    """
    result = df.copy()

    # Get holiday set for the date range
    min_date = df["interval_start"].min().date()
    max_date = df["interval_start"].max().date()
    holiday_dates = get_holiday_dates(utility, min_date, max_date)

    # Calculate day types from local dates
    local_dates = result["interval_start"].dt.date
    day_of_week = result["interval_start"].dt.dayofweek

    result["is_holiday"] = local_dates.isin(holiday_dates)
    result["is_weekend"] = day_of_week >= 5  # Sat=5, Sun=6
    result["is_weekday"] = (day_of_week < 5) & ~result["is_holiday"]

    return result


def load_usage_dataframe(
    customer: Customer,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Load usage data from CustomerUsage model into DataFrame format.

    Converts from UTC to customer local time and renames columns to match
    the format expected by the billing core.

    Args:
        customer: Customer to load usage for
        start_date: Start of date range in customer's local timezone (inclusive)
        end_date: End of date range in customer's local timezone (inclusive)

    Returns:
        DataFrame with columns: interval_start, interval_end, kwh, kw

    Raises:
        NoUsageDataError: If no usage data exists for the period
    """
    tz = zoneinfo.ZoneInfo(str(customer.timezone))

    # Convert local dates to UTC datetime range
    start_dt = datetime.combine(start_date, datetime.min.time())
    start_utc = start_dt.replace(tzinfo=tz).astimezone(zoneinfo.ZoneInfo("UTC"))

    # Use end of day for end_date (inclusive)
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    end_utc = end_dt.replace(tzinfo=tz).astimezone(zoneinfo.ZoneInfo("UTC"))

    # Query usage records
    usage_qs = CustomerUsage.objects.filter(
        customer=customer,
        interval_start_utc__gte=start_utc,
        interval_start_utc__lt=end_utc,
    ).order_by("interval_start_utc")

    if not usage_qs.exists():
        raise NoUsageDataError(customer, start_date, end_date)

    # Convert to DataFrame
    records = list(
        usage_qs.values(
            "interval_start_utc",
            "interval_end_utc",
            "energy_kwh",
            "peak_demand_kw",
        )
    )

    df = pd.DataFrame(records)

    # Rename columns to match billing core expectations
    df = df.rename(
        columns={
            "interval_start_utc": "interval_start",
            "interval_end_utc": "interval_end",
            "energy_kwh": "kwh",
            "peak_demand_kw": "kw",
        }
    )

    # Convert to timezone-aware and localize to customer timezone
    df["interval_start"] = pd.to_datetime(df["interval_start"], utc=True).dt.tz_convert(
        tz
    )
    df["interval_end"] = pd.to_datetime(df["interval_end"], utc=True).dt.tz_convert(tz)

    # Convert Decimal to float for pandas operations
    df["kwh"] = df["kwh"].astype(float)
    df["kw"] = df["kw"].astype(float)

    return df


def get_billing_period_for_month(
    billing_day: int, year: int, month: int
) -> tuple[date, date]:
    """
    Get the billing period that ends in the given month.

    With billing_day=15 and month=1 (January), year=2024:
    Returns (date(2023, 12, 16), date(2024, 1, 15))

    Args:
        billing_day: Day of month when billing cycle ends (1-28)
        year: Year of the billing month
        month: Month of the billing month (1-12)

    Returns:
        Tuple of (start_date, end_date) for the billing period
    """
    end_date = date(year, month, billing_day)

    # Start date is day after billing_day of previous month
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    start_date = date(prev_year, prev_month, billing_day) + timedelta(days=1)

    return (start_date, end_date)


def get_available_billing_months(
    customer: Customer,
) -> list[tuple[str, str]]:
    """
    Get list of billing months with available usage data for a customer.

    Returns a list of (value, label) tuples for use in a form ChoiceField.
    The value is in "YYYY-MM" format, the label is human-readable.

    Args:
        customer: Customer to get billing months for

    Returns:
        List of (value, label) tuples sorted chronologically
    """
    from django.db.models import Max, Min

    # Get the date range of available usage data
    usage_range = CustomerUsage.objects.filter(customer=customer).aggregate(
        min_date=Min("interval_start_utc"),
        max_date=Max("interval_start_utc"),
    )

    if not usage_range["min_date"] or not usage_range["max_date"]:
        return []

    # Convert to customer's local timezone
    tz = zoneinfo.ZoneInfo(str(customer.timezone))
    min_local = usage_range["min_date"].astimezone(tz)
    max_local = usage_range["max_date"].astimezone(tz)

    billing_day = customer.billing_day

    # Find the first complete billing month
    # A billing month is complete if we have data from start to end
    choices = []

    # Start from the month of the first data point
    current_year = min_local.year
    current_month = min_local.month

    # Iterate through potential billing months
    while True:
        period_start, period_end = get_billing_period_for_month(
            billing_day, current_year, current_month
        )

        # Stop if the period end is beyond our data
        if period_end > max_local.date():
            break

        # Only include if we have data covering the start
        if period_start >= min_local.date():
            value = f"{current_year:04d}-{current_month:02d}"
            label = date(current_year, current_month, 1).strftime("%B %Y")
            choices.append((value, label))

        # Move to next month
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1

        # Safety limit
        if len(choices) > 120:  # 10 years max
            break

    return choices


def calculate_customer_bill(
    customer: Customer,
    start_date: date,
    end_date: date,
    tariff: Tariff | None = None,
    billing_periods: list[tuple[date, date]] | None = None,
    fill_gaps: bool = True,
) -> BillingCalculationResult:
    """
    Calculate bills for a customer over a date range.

    Args:
        customer: Customer to bill
        start_date: Start of billing period (customer local time, inclusive)
        end_date: End of billing period (customer local time, inclusive)
        tariff: Tariff to use (defaults to customer.current_tariff)
        billing_periods: Custom billing periods, or None for calendar months
        fill_gaps: Whether to fill missing intervals with fill_missing_data()

    Returns:
        BillingCalculationResult with monthly bills and full DataFrame

    Raises:
        InvalidDateRangeError: If date range is invalid
        NoUsageDataError: If no usage data exists
    """
    warnings: list[str] = []

    # Validate date range
    if start_date > end_date:
        raise InvalidDateRangeError(
            "Start date must be before or equal to end date", start_date, end_date
        )

    # Use customer's current tariff if not specified
    if tariff is None:
        tariff = customer.current_tariff

    # Get utility for holiday lookup
    utility = tariff.utility
    customer_tz = zoneinfo.ZoneInfo(str(customer.timezone))

    # Load usage data
    df = load_usage_dataframe(customer, start_date, end_date)

    # Add day type columns
    df = determine_day_types(df, utility, customer_tz)

    # Analyze gaps before filling
    expected_grain = timedelta(minutes=customer.billing_interval_minutes)
    gap_analysis = analyze_gaps(df, expected_grain)

    # Fill gaps if requested
    if fill_gaps:
        original_len = len(df)
        df = fill_missing_data(df)
        if len(df) > original_len:
            warnings.append(f"Filled {len(df) - original_len} missing intervals")

    # Validate the prepared dataframe
    validate_usage_dataframe(df)

    # Convert tariff to DTO (with prefetched charges and applicability rules)
    from tariffs.models import Tariff as TariffModel

    tariff_with_charges = TariffModel.objects.prefetch_related(
        "energy_charges__applicability_rules",
        "demand_charges__applicability_rules",
        "customer_charges",
    ).get(pk=tariff.pk)
    tariff_dto = tariff_to_dto(tariff_with_charges)

    # Calculate bills
    billing_months, billing_df = calculate_monthly_bills(
        df, tariff_dto, billing_periods
    )

    return BillingCalculationResult(
        customer=customer,
        tariff=tariff,
        period_start=start_date,
        period_end=end_date,
        billing_months=billing_months,
        billing_df=billing_df,
        warnings=warnings,
        gap_analysis=gap_analysis,
    )
