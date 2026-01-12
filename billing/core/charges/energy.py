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

    Args:
        usage: a dataframe of usage, as validated by `billing.core.data.validate_usage_dataframe
        energy_charge: the charge to apply
    """
    # The energy charge is equal to the rate times the usage in applicable intervals
    energy_cost = energy_charge.rate_usd_per_kwh * _to_decimal_series(usage["kwh"])
    applicable_intervals = construct_applicability_mask(
        usage,
        energy_charge.applicability,
    )
    energy_cost = energy_cost * applicable_intervals

    return energy_cost
