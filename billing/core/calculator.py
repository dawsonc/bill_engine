"""
Core billing calculator functions.

Orchestrates charge application and monthly bill aggregation.
"""

from decimal import Decimal

import pandas as pd

from .charges.customer import apply_customer_charge
from .charges.demand import apply_demand_charge
from .charges.energy import apply_energy_charge
from .types import BillLineItem, ChargeList, MonthlyBillResult


def apply_charges(usage: pd.DataFrame, charges: ChargeList) -> pd.DataFrame:
    """
    Apply all charges to usage data, creating a billing DataFrame.

    Creates a DataFrame with the original usage columns plus one additional column
    per charge, where each charge column is labeled with the charge's UUID and contains
    the per-interval cost for that charge.

    Args:
        usage: DataFrame with validated usage data containing columns:
            interval_start, interval_end, kwh, kw, is_weekday, is_weekend, is_holiday
        charges: ChargeList containing all charges to apply

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


def calculate_monthly_bills(
    usage: pd.DataFrame, charges: ChargeList
) -> tuple[list[MonthlyBillResult], pd.DataFrame]:
    """
    Calculate monthly bills from usage and charges.

    Applies all charges to the usage data and aggregates the results by month,
    creating structured bill results with line items for each charge.

    Args:
        usage: DataFrame with validated usage data
        charges: ChargeList containing all charges to apply

    Returns:
        Tuple of:
        - List of MonthlyBillResult objects (one per month, sorted chronologically)
        - Complete billing DataFrame with per-interval charges
    """
    # Save original usage columns for filtering out charge columns later
    usage_columns = usage.columns

    # Apply all charges to get billing DataFrame
    billing_df = apply_charges(usage, charges)

    # Build mapping from charge_id to charge object for line item descriptions
    charge_map: dict[str, tuple] = {}
    for charge in charges.energy_charges:
        charge_map[str(charge.charge_id.value)] = ("energy", charge)
    for charge in charges.demand_charges:
        charge_map[str(charge.charge_id.value)] = ("demand", charge)
    for charge in charges.customer_charges:
        charge_map[str(charge.charge_id.value)] = ("customer", charge)

    # Identify charge columns (everything except the original 7 usage columns)
    charge_columns = [col for col in billing_df.columns if col not in usage_columns]

    # Group by month
    billing_df_with_month = billing_df.copy()
    billing_df_with_month["_month_period"] = billing_df_with_month["interval_start"].dt.to_period(
        "M"
    )
    grouped = billing_df_with_month.groupby("_month_period")

    # Build monthly results
    monthly_results = []
    for period, group_df in grouped:
        # Extract month boundaries
        month_start = period.start_time.date()
        month_end = period.end_time.date()

        # Sum each charge for the month
        energy_line_items = []
        demand_line_items = []
        customer_line_items = []

        for charge_col in charge_columns:
            monthly_sum = group_df[charge_col].sum()

            # Convert to Decimal if needed
            if not isinstance(monthly_sum, Decimal):
                # This shouldn't be needed, since we should be handling Decimal conversions
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

        # Calculate total
        total_usd = sum(
            item.amount_usd
            for items in [energy_line_items, demand_line_items, customer_line_items]
            for item in items
        )

        # Create monthly result
        monthly_result = MonthlyBillResult(
            month_start=month_start,
            month_end=month_end,
            energy_line_items=tuple(energy_line_items),
            demand_line_items=tuple(demand_line_items),
            customer_line_items=tuple(customer_line_items),
            total_usd=total_usd,
        )

        monthly_results.append(monthly_result)

    # Sort by month_start
    monthly_results.sort(key=lambda r: r.month_start)

    return (monthly_results, billing_df)
