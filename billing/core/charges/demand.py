"""
Logic for applying demand charges to bills.
"""

from datetime import date
from decimal import Decimal

import pandas as pd

from ..applicability import construct_applicability_mask
from ..types import ApplicabilityRule, DemandCharge, PeakType
from ..util import _to_decimal_series


def _calculate_applicability_scaling_factor(
    period_start: date,
    period_end: date,
    applicability: ApplicabilityRule,
) -> Decimal:
    """Calculate scaling factor for a billing period based on applicability date range.

    When an applicability rule's start_date or end_date falls mid-billing period,
    the charge should be scaled by the fraction of applicable days.

    Args:
        period_start: First date of the billing period
        period_end: Last date of the billing period
        applicability: The applicability rule with optional date constraints

    Returns:
        Scaling factor between 0 and 1 (applicable_days / total_days)
    """
    if applicability.start_date is None and applicability.end_date is None:
        return Decimal("1")

    total_days = (period_end - period_start).days + 1

    # Normalize applicability dates to period's year (they're stored as year 2000)
    if applicability.start_date:
        app_start = date(
            period_start.year, applicability.start_date.month, applicability.start_date.day
        )
    else:
        app_start = period_start

    if applicability.end_date:
        app_end = date(period_start.year, applicability.end_date.month, applicability.end_date.day)
    else:
        app_end = period_end

    # Calculate intersection of billing period and applicability range
    effective_start = max(period_start, app_start)
    effective_end = min(period_end, app_end)

    if effective_start > effective_end:
        return Decimal("0")  # No overlap

    applicable_days = (effective_end - effective_start).days + 1
    return Decimal(applicable_days) / Decimal(total_days)


def apply_demand_charge(
    usage: pd.DataFrame,
    demand_charge: DemandCharge,
) -> pd.Series:
    """
    Estimate the demand charge in each interval.

    Finds the peak demand in each period (daily or monthly) and allocates the charge
    evenly across all intervals that achieve that peak.

    Args:
        usage: DataFrame with usage data. Required columns:
            - interval_start: datetime for each interval
            - kw: demand in kW for each interval
            - is_weekday, is_weekend, is_holiday: booleans for applicability filtering
            - billing_period: str identifier for billing period (required for MONTHLY charges)
        demand_charge: the charge to apply

    Returns:
        Series with per-interval demand charge amounts
    """
    # The demand charge is equal to the rate times the max demand in applicable intervals
    # The maximum is either daily or monthly, depending on the type of charge

    # Mask out all hours where the charge doesn't apply
    applicable_intervals = construct_applicability_mask(
        usage,
        demand_charge.applicability_rules,
    )
    usage["_masked_kw"] = _to_decimal_series(usage["kw"] * applicable_intervals)

    # Get the groupings over which we will compute the max
    if demand_charge.type == PeakType.MONTHLY:
        # Monthly refers to billing period rather than calendar month
        usage["_peak_grouping"] = usage["billing_period"]
    elif demand_charge.type == PeakType.DAILY:
        usage["_peak_grouping"] = usage["interval_start"].dt.date
    else:
        # DemandCharge validation should prevent this
        raise ValueError(f"Invalid demand_charge.type: {demand_charge.type}")

    # Get the peak demand in each period, and allocate the cost evenly all intervals that
    # achieve that peak demand
    peak_demand = usage.groupby("_peak_grouping")["_masked_kw"].max()

    # Merge peak demand back to usage for comparison
    usage["_peak_demand"] = usage["_peak_grouping"].map(peak_demand)

    # Identify peak intervals (where actual kW equals the peak for that period)
    usage["_is_peak_interval"] = usage["_masked_kw"] == usage["_peak_demand"]

    # Count how many intervals share the peak in each group
    num_peaks = usage.groupby("_peak_grouping")["_is_peak_interval"].sum()

    # Merge num_peaks back to usage
    usage["_num_peaks"] = usage["_peak_grouping"].map(num_peaks)

    # Calculate cost: rate × peak_demand × is_peak / num_peaks
    # Only peak intervals get charged, split evenly among all peak intervals in that period
    demand_cost = (
        demand_charge.rate_usd_per_kw
        * usage["_peak_demand"]
        * usage["_is_peak_interval"]
        / usage["_num_peaks"]
    )

    # Apply scaling for applicability date ranges that fall mid-billing period
    # (only applies to MONTHLY charges with date constraints)
    # Check if any rule has date constraints
    rules_with_dates = [
        rule
        for rule in demand_charge.applicability_rules
        if rule.start_date or rule.end_date
    ]
    if demand_charge.type == PeakType.MONTHLY and rules_with_dates:
        # Calculate scaling factor for each billing period
        # Use max scaling factor across all rules (OR logic: most permissive wins)
        period_date_ranges = usage.groupby("_peak_grouping")["interval_start"].agg(["min", "max"])

        def _compute_period_scaling(row):
            period_start = row["min"].date()
            period_end = row["max"].date()
            rule_scalings = [
                _calculate_applicability_scaling_factor(period_start, period_end, rule)
                for rule in rules_with_dates
            ]
            # OR logic: take the max scaling factor
            return max(rule_scalings)

        scaling_factors = period_date_ranges.apply(_compute_period_scaling, axis=1).to_dict()

        usage["_scaling_factor"] = usage["_peak_grouping"].map(scaling_factors)
        demand_cost = demand_cost * usage["_scaling_factor"]
        usage.drop(columns=["_scaling_factor"], inplace=True)

    usage.drop(
        columns=["_masked_kw", "_peak_grouping", "_is_peak_interval", "_peak_demand", "_num_peaks"],
        inplace=True,
    )

    return demand_cost
