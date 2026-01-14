"""
Logic for applying customer charges to bills.
"""

import pandas as pd

from ..types import CustomerCharge, CustomerChargeType


def apply_customer_charge(
    usage: pd.DataFrame,
    customer_charge: CustomerCharge,
) -> pd.Series:
    """
    Apply customer charge to usage data based on charge type.

    - MONTHLY: Allocate monthly amount evenly to all intervals in each billing period
    - DAILY: Allocate daily amount evenly to all intervals in each day

    Args:
        usage: DataFrame with usage data. Required columns:
            - interval_start: datetime for each interval
            - billing_period: str identifier for billing period (required for MONTHLY charges)
        customer_charge: the charge to apply

    Returns:
        Series with per-interval customer charge amounts
    """
    if customer_charge.type == CustomerChargeType.DAILY:
        # Group by date and allocate daily charge evenly across intervals
        usage["_customer_charge_period"] = usage["interval_start"].dt.date
    else:
        # Allocate monthly charge evenly across intervals
        usage["_customer_charge_period"] = usage["billing_period"]

    intervals_per_period = usage.groupby("_customer_charge_period").size()
    allocated_charge = usage["_customer_charge_period"].map(
        lambda d: customer_charge.amount_usd / intervals_per_period[d]
    )
    usage.drop(columns=["_customer_charge_period"], inplace=True)
    return allocated_charge
