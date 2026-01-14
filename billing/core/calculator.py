"""
Core billing calculator functions.

Orchestrates charge application and monthly bill aggregation.
"""

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
            monthly_sum = Decimal(monthly_sum)

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
    - Customer charges: simple sum if daily, weighted if monthly
    - Demand charges: pro-rated if a demand charge only applies for part of the
        billing month

    Args:
        billing_df: DataFrame with per-interval charges
        period_start: Start of billing month (inclusive)
        period_end: End of billing month (inclusive)
        charge_map: Mapping from charge_id to (charge_type, charge_obj)
        charge_columns: List of charge column names

    Returns:
        BillingMonthResult
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
            energy_line_items=(),
            demand_line_items=(),
            customer_line_items=(),
            total_usd=Decimal("0"),
        )

    # Sum charges and create line items
    energy_line_items, demand_line_items, customer_line_items = _sum_charges_for_group(
        period_df, charge_columns, charge_map
    )

    # Calculate total
    total_usd = sum(
        (item.amount_usd for item in energy_line_items),
        start=Decimal("0"),
    ) + sum(
        (item.amount_usd for item in demand_line_items),
        start=Decimal("0"),
    ) + sum(
        (item.amount_usd for item in customer_line_items),
        start=Decimal("0"),
    )

    return BillingMonthResult(
        period_start=period_start,
        period_end=period_end,
        energy_line_items=tuple(energy_line_items),
        demand_line_items=tuple(demand_line_items),
        customer_line_items=tuple(customer_line_items),
        total_usd=total_usd,
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
