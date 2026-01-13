"""
Logic for applying demand charges to bills.
"""

import pandas as pd

from ..applicability import construct_applicability_mask
from ..types import DemandCharge, PeakType
from ..util import _to_decimal_series


def apply_demand_charge(
    usage: pd.DataFrame,
    demand_charge: DemandCharge,
) -> pd.Series:
    """
    Estimate the demand charge in each interval.

    Args:
        usage: a dataframe of usage, as validated by `billing.core.data.validate_usage_dataframe
        demand_charge: the charge to apply
    """
    # The demand charge is equal to the rate times the max demand in applicable intervals
    # The maximum is either daily or monthly, depending on the type of charge

    # Mask out all hours where the charge doesn't apply
    applicable_intervals = construct_applicability_mask(
        usage,
        demand_charge.applicability,
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

    usage.drop(
        columns=["_masked_kw", "_peak_grouping", "_is_peak_interval", "_peak_demand", "_num_peaks"],
        inplace=True,
    )

    return demand_cost
