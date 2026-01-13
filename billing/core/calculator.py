"""
Core billing calculator functions.

Orchestrates charge application and monthly bill aggregation.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from .charges.customer import apply_customer_charge
from .charges.demand import apply_demand_charge
from .charges.energy import apply_energy_charge
from .types import (
    BillingMonthResult,
    BillLineItem,
    ChargeId,
    CustomerChargeType,
    MonthlyBillResult,
    Tariff,
)
from .util import _derive_calendar_months, _trim_to_date_range


def apply_charges(usage: pd.DataFrame, charges: Tariff) -> pd.DataFrame:
    """
    Apply all charges to usage data, creating a billing DataFrame.

    Creates a DataFrame with the original usage columns plus one additional column
    per charge, where each charge column is labeled with the charge's UUID and contains
    the per-interval cost for that charge.

    Args:
        usage: DataFrame with validated usage data containing columns:
            interval_start, interval_end, kwh, kw, is_weekday, is_weekend, is_holiday
        charges: Tariff containing all charges to apply

    Returns:
        DataFrame with original usage columns plus one column per charge,
        labeled with charge_id UUID strings
    """
    # Create a copy to avoid mutating the input
    billing_df = usage.copy()

    # Apply energy charges
    for charge in charges.energy_charges:
        result = apply_energy_charge(usage, charge)
        column_name = str(charge.charge_id.value)
        billing_df[column_name] = result

    # Apply demand charges
    for charge in charges.demand_charges:
        result = apply_demand_charge(usage, charge)
        column_name = str(charge.charge_id.value)
        billing_df[column_name] = result

    # Apply customer charges
    for charge in charges.customer_charges:
        result = apply_customer_charge(usage, charge)
        column_name = str(charge.charge_id.value)
        billing_df[column_name] = result

    return billing_df


def _sum_charges_for_group(
    group_df: pd.DataFrame,
    charge_columns: list[str],
    charge_map: dict[str, tuple[str, Any]],
) -> tuple[list[BillLineItem], list[BillLineItem], list[BillLineItem]]:
    """
    Sum charges for a group of intervals and create line items.

    Args:
        group_df: DataFrame containing the interval group to sum
        charge_columns: List of charge column names (UUIDs)
        charge_map: Mapping from charge_id to (charge_type, charge_obj)

    Returns:
        Tuple of (energy_line_items, demand_line_items, customer_line_items)
    """
    energy_line_items: list[BillLineItem] = []
    demand_line_items: list[BillLineItem] = []
    customer_line_items: list[BillLineItem] = []

    for charge_col in charge_columns:
        monthly_sum = group_df[charge_col].sum()

        # Convert to Decimal if needed
        if not isinstance(monthly_sum, Decimal):
            monthly_sum = Decimal(str(monthly_sum))

        # Look up charge object to get name and type
        charge_type, charge_obj = charge_map[charge_col]

        line_item = BillLineItem(
            description=charge_obj.name,
            amount_usd=monthly_sum,
            charge_id=charge_obj.charge_id,
        )

        # Add to appropriate list
        if charge_type == "energy":
            energy_line_items.append(line_item)
        elif charge_type == "demand":
            demand_line_items.append(line_item)
        elif charge_type == "customer":
            customer_line_items.append(line_item)

    return energy_line_items, demand_line_items, customer_line_items


def _aggregate_line_items_weighted(
    monthly_results: list[MonthlyBillResult],
    line_item_attr: str,
    weights: dict[date, Decimal],
) -> list[BillLineItem]:
    """
    Aggregate line items across calendar months with day-based weighting.

    Groups line items by charge_id and applies weighted sum based on the
    number of days each calendar month contributes to the billing period.

    Args:
        monthly_results: List of MonthlyBillResult for each calendar month portion
        line_item_attr: Attribute name to access line items ("demand_line_items" or "customer_line_items")
        weights: Mapping from month_start date to weight (Decimal between 0 and 1)

    Returns:
        List of aggregated BillLineItem with weighted amounts
    """

    charge_amounts: dict[ChargeId, Decimal] = defaultdict(Decimal)
    charge_descriptions: dict[ChargeId, str] = {}

    for result in monthly_results:
        weight = weights.get(result.month_start, Decimal("1"))
        line_items = getattr(result, line_item_attr)

        for item in line_items:
            charge_amounts[item.charge_id] += item.amount_usd * weight
            charge_descriptions[item.charge_id] = item.description

    return [
        BillLineItem(
            description=charge_descriptions[charge_id],
            amount_usd=amount,
            charge_id=charge_id,
        )
        for charge_id, amount in charge_amounts.items()
    ]


def _calculate_billing_month_result(
    billing_df: pd.DataFrame,
    period_start: date,
    period_end: date,
    charge_map: dict[str, tuple[str, Any]],
    charge_columns: list[str],
) -> BillingMonthResult:
    """
    Calculate BillingMonthResult for a single custom billing month.

    For billing months spanning multiple calendar months:
    - Energy charges: simple sum of all energy in the billing month
    - Customer charges: weighted by days in each calendar month portion
    - Demand charges: full monthly demand (peak * rate) weighted by days in each portion

    Args:
        billing_df: DataFrame with per-interval charges
        period_start: Start of billing month (inclusive)
        period_end: End of billing month (inclusive)
        charge_map: Mapping from charge_id to (charge_type, charge_obj)
        charge_columns: List of charge column names

    Returns:
        BillingMonthResult with weighted aggregations for demand/customer charges
    """

    # Filter billing_df to only intervals within this billing period
    mask = (billing_df["interval_start"].dt.date >= period_start) & (
        billing_df["interval_start"].dt.date <= period_end
    )
    period_df = billing_df[mask].copy()

    if period_df.empty:
        # Return empty result for this billing period
        return BillingMonthResult(
            period_start=period_start,
            period_end=period_end,
            monthly_breakdowns=(),
            energy_line_items=(),
            demand_line_items=(),
            customer_line_items=(),
            total_usd=Decimal("0"),
        )

    # Group by calendar month within the billing period
    period_df["_month_period"] = period_df["interval_start"].dt.to_period("M")
    grouped = period_df.groupby("_month_period")

    # Calculate days in billing period for weighting
    total_days = (period_end - period_start).days + 1

    monthly_results: list[MonthlyBillResult] = []
    weights: dict[date, Decimal] = {}

    for month_period, group_df in grouped:
        # Calculate the actual date range for this month within the billing period
        month_start_full = month_period.start_time.date()
        month_end_full = month_period.end_time.date()

        # Clip to billing period boundaries
        month_start_clipped = max(month_start_full, period_start)
        month_end_clipped = min(month_end_full, period_end)

        days_in_month_portion = (month_end_clipped - month_start_clipped).days + 1
        weight = Decimal(days_in_month_portion) / Decimal(total_days)
        weights[month_start_clipped] = weight

        # Calculate line items for this month portion (simple sum, not weighted yet)
        energy_items, demand_items, customer_items = _sum_charges_for_group(
            group_df, charge_columns, charge_map
        )

        monthly_result = MonthlyBillResult(
            month_start=month_start_clipped,
            month_end=month_end_clipped,
            energy_line_items=tuple(energy_items),
            demand_line_items=tuple(demand_items),
            customer_line_items=tuple(customer_items),
            total_usd=sum(
                item.amount_usd
                for items in [energy_items, demand_items, customer_items]
                for item in items
            ),
        )
        monthly_results.append(monthly_result)

    # Sort monthly results chronologically
    monthly_results.sort(key=lambda r: r.month_start)

    # Aggregate across months with appropriate weighting
    # Energy: simple sum (no weighting)
    aggregated_energy = [
        BillLineItem(
            description=item.description,
            amount_usd=sum(
                line_item.amount_usd
                for result in monthly_results
                for line_item in result.energy_line_items
                if line_item.charge_id == item.charge_id
            ),
            charge_id=item.charge_id,
        )
        for item in (monthly_results[0].energy_line_items if monthly_results else [])
    ]

    # Demand: weighted sum of full monthly demand charges
    # The demand charge for each calendar month should be peak_kw * rate, weighted by days
    aggregated_demand = _aggregate_line_items_weighted(
        monthly_results, "demand_line_items", weights
    )

    # Customer: handle differently based on charge type (daily vs monthly)
    aggregated_customer: list[BillLineItem] = []
    customer_charge_amounts: dict[ChargeId, Decimal] = defaultdict(Decimal)
    customer_charge_descriptions: dict[ChargeId, str] = {}

    for charge_col, (charge_type, charge_obj) in charge_map.items():
        if charge_type == "customer":
            if charge_obj.type == CustomerChargeType.DAILY:
                # Daily charge: multiply by number of days in billing period
                customer_charge_amounts[charge_obj.charge_id] += charge_obj.amount_usd * Decimal(
                    total_days
                )
            else:
                # Monthly charge: weight by days in each calendar month portion
                for result in monthly_results:
                    weight = weights.get(result.month_start, Decimal("1"))
                    customer_charge_amounts[charge_obj.charge_id] += charge_obj.amount_usd * weight
            customer_charge_descriptions[charge_obj.charge_id] = charge_obj.name

    aggregated_customer = [
        BillLineItem(
            description=customer_charge_descriptions[charge_id],
            amount_usd=amount,
            charge_id=charge_id,
        )
        for charge_id, amount in customer_charge_amounts.items()
    ]

    total = sum(
        item.amount_usd
        for items in [aggregated_energy, aggregated_demand, aggregated_customer]
        for item in items
    )

    return BillingMonthResult(
        period_start=period_start,
        period_end=period_end,
        monthly_breakdowns=tuple(monthly_results),
        energy_line_items=tuple(aggregated_energy),
        demand_line_items=tuple(aggregated_demand),
        customer_line_items=tuple(aggregated_customer),
        total_usd=total,
    )


def calculate_monthly_bills(
    usage: pd.DataFrame,
    charges: Tariff,
    billing_periods: list[tuple[date, date]] | None = None,
) -> tuple[list[BillingMonthResult], pd.DataFrame]:
    """
    Calculate bills from usage and charges.

    Applies all charges to the usage data and aggregates the results by billing period,
    creating structured bill results with line items for each charge.

    Args:
        usage: DataFrame with validated usage data
        charges: Tariff containing all charges to apply
        billing_periods: Optional list of (start_date, end_date) tuples defining
            billing periods. Both dates are inclusive. If None, uses calendar months
            derived from the usage data.

    Returns:
        Tuple of:
        - List of BillingMonthResult objects (one per billing period)
        - Complete billing DataFrame with per-interval charges
    """
    # Save original usage columns for filtering out charge columns later
    usage_columns = usage.columns

    # Build mapping from charge_id to charge object for line item descriptions
    charge_map: dict[str, tuple] = {}
    for charge in charges.energy_charges:
        charge_map[str(charge.charge_id.value)] = ("energy", charge)
    for charge in charges.demand_charges:
        charge_map[str(charge.charge_id.value)] = ("demand", charge)
    for charge in charges.customer_charges:
        charge_map[str(charge.charge_id.value)] = ("customer", charge)

    # If billing_periods not provided, derive from calendar months in the data
    if billing_periods is None:
        billing_periods = _derive_calendar_months(usage)

    # Handle empty billing_periods
    if not billing_periods:
        return [], apply_charges(usage, charges)

    # Trim the data down to just the billing periods
    billing_start_date = min(period[0] for period in billing_periods)
    billing_end_date = max(period[1] for period in billing_periods)
    usage = _trim_to_date_range(usage, billing_start_date, billing_end_date)

    # Label with billing months
    usage["billing_period"] = None
    for period_start, period_end in billing_periods:
        period_str = f"{period_start:%Y-%m} -- {period_end:%Y-%m}"
        mask = (usage["interval_start"].dt.date >= period_start) & (
            usage["interval_start"].dt.date <= period_end
        )
        usage.loc[mask, "billing_period"] = period_str

    # Apply all charges to get billing DataFrame
    billing_df = apply_charges(usage, charges)

    # Identify charge columns (everything except the original usage columns)
    charge_columns = [col for col in billing_df.columns if col not in usage_columns]

    # Calculate results for each billing period
    billing_month_results: list[BillingMonthResult] = []
    for period_start, period_end in billing_periods:
        result = _calculate_billing_month_result(
            billing_df, period_start, period_end, charge_map, charge_columns
        )
        billing_month_results.append(result)

    return (billing_month_results, billing_df)
