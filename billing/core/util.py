"""Helper functions for billing engine."""

from decimal import Decimal

import pandas as pd


def _to_decimal_series(values: pd.Series) -> pd.Series:
    """
    Convert a numeric pandas Series to Decimals safely.

    Notes:
        Uses str(x) to avoid embedding binary-float artefacts into Decimal.
    """
    return values.map(lambda x: Decimal(str(x)))
