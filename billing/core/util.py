"""Helper functions for billing engine."""

from datetime import date
from decimal import Decimal

import pandas as pd


def _to_decimal_series(values: pd.Series) -> pd.Series:
    """
    Convert a numeric pandas Series to Decimals safely.

    Notes:
        Uses str(x) to avoid embedding binary-float artefacts into Decimal.
    """
    return values.map(lambda x: Decimal(str(x)))


def _trim_to_date_range(df: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    """
    Filter DataFrame to only include intervals within a date range.

    Args:
        df: DataFrame with interval_start column
        start_date: Start of date range (inclusive)
        end_date: End of date range (inclusive)

    Returns:
        Filtered DataFrame containing only intervals within the date range
    """
    mask = (df["interval_start"].dt.date >= start_date) & (
        df["interval_start"].dt.date <= end_date
    )
    return df[mask].copy()


def _derive_calendar_months(billing_df: pd.DataFrame) -> list[tuple[date, date]]:
    """
    Derive calendar month billing periods from usage data.

    Args:
        billing_df: DataFrame with interval_start column

    Returns:
        List of (start_date, end_date) tuples for each calendar month in the data
    """
    billing_df_with_month = billing_df.copy()
    billing_df_with_month["_month_period"] = billing_df_with_month["interval_start"].dt.to_period(
        "M"
    )

    calendar_months: list[tuple[date, date]] = []
    for period in sorted(billing_df_with_month["_month_period"].unique()):
        month_start = period.start_time.date()
        month_end = period.end_time.date()
        calendar_months.append((month_start, month_end))

    return calendar_months
