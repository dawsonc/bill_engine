"""
Logic for applying energy charges to bills.
"""

import pandas as pd

from ..applicability import construct_applicability_mask
from ..types import EnergyCharge
from ..util import _to_decimal_series


def apply_energy_charge(
    usage: pd.DataFrame,
    energy_charge: EnergyCharge,
) -> pd.Series:
    """
    Estimate the energy charge in each interval.

    Multiplies the rate by the energy usage, filtered by applicability rules.

    Args:
        usage: DataFrame with usage data. Required columns:
            - interval_start: datetime for each interval
            - kwh: energy usage in kWh for each interval
            - is_weekday, is_weekend, is_holiday: booleans for applicability filtering
        energy_charge: the charge to apply

    Returns:
        Series with per-interval energy charge amounts
    """
    # The energy charge is equal to the rate times the usage in applicable intervals
    energy_cost = energy_charge.rate_usd_per_kwh * _to_decimal_series(usage["kwh"])
    applicable_intervals = construct_applicability_mask(
        usage,
        energy_charge.applicability,
    )
    energy_cost = energy_cost * applicable_intervals

    return energy_cost
