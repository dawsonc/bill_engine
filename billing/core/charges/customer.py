"""
Logic for applying customer charges to bills.
"""

import pandas as pd

from ..types import CustomerCharge


def apply_customer_charge(
    usage: pd.DataFrame,
    customer_charge: CustomerCharge,
) -> pd.Series:
    """
    Estimate the customer charge by allocating it evenly to all intervals in each month.

    Args:
        usage: a dataframe of usage, as validated by `billing.core.data.validate_usage_dataframe
        customer_charge: the charge to apply
    """
    # Customer charges are applicable to all intervals,
    # but they are spread across each month
    usage["_year_month"] = usage["interval_start"].dt.strftime("%Y-%m")
    intervals_per_month = usage.groupby("_year_month").size()
    allocated_customer_charge = usage["_year_month"].map(
        lambda ym: customer_charge.amount_usd_per_month / intervals_per_month[ym]
    )

    # Clean up temporary columns
    usage.drop(columns=["_year_month"], inplace=True)

    return allocated_customer_charge
