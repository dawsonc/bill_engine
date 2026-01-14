"""
Data validation and repair functionality for billing data
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

import pandas as pd


@dataclass
class GapAnalysis:
    """Results of analyzing gaps in usage data."""

    total_missing: int
    longest_gap_intervals: int
    longest_gap_duration: timedelta
    missing_by_month: dict[str, int]  # "2024-01" -> count


def analyze_gaps(
    usage_df: pd.DataFrame,
    expected_grain: timedelta,
) -> GapAnalysis:
    """
    Analyze gaps in usage data before filling.

    Args:
        usage_df: DataFrame with interval_start and interval_end columns (tz-aware)
        expected_grain: Expected interval duration (e.g., timedelta(minutes=5))

    Returns:
        GapAnalysis with total missing, longest gap, and missing by month
    """
    if usage_df.empty:
        return GapAnalysis(
            total_missing=0,
            longest_gap_intervals=0,
            longest_gap_duration=timedelta(0),
            missing_by_month={},
        )

    df = usage_df.copy()
    df["interval_start"] = pd.to_datetime(df["interval_start"])

    # Work in UTC for consistent calculations
    tz = df["interval_start"].dt.tz
    if tz:
        start_utc = df["interval_start"].dt.tz_convert("UTC")
    else:
        start_utc = df["interval_start"]

    df = df.sort_values("interval_start")
    start_utc = start_utc.sort_values()

    # Calculate expected full range
    min_time = start_utc.min()
    max_time = start_utc.max()

    # Calculate expected number of intervals
    total_duration = max_time - min_time
    expected_intervals = int(total_duration / expected_grain) + 1
    actual_intervals = len(df)
    total_missing = max(0, expected_intervals - actual_intervals)

    if total_missing == 0:
        return GapAnalysis(
            total_missing=0,
            longest_gap_intervals=0,
            longest_gap_duration=timedelta(0),
            missing_by_month={},
        )

    # Find gaps by looking at differences between consecutive intervals
    start_diffs = start_utc.diff().dropna()
    expected_grain_td = pd.Timedelta(expected_grain)

    # Identify where gaps exist (diff > expected grain)
    gap_mask = start_diffs > expected_grain_td
    gaps = start_diffs[gap_mask]

    # Calculate longest gap
    if len(gaps) > 0:
        longest_gap_td = gaps.max()
        longest_gap_intervals = int(longest_gap_td / expected_grain_td) - 1
        longest_gap_duration = timedelta(
            seconds=longest_gap_td.total_seconds() - expected_grain.total_seconds()
        )
    else:
        longest_gap_intervals = 0
        longest_gap_duration = timedelta(0)

    # Calculate missing by month
    # Create full expected range
    full_range = pd.date_range(
        start=min_time,
        end=max_time,
        freq=expected_grain_td,
        tz="UTC" if tz else None,
    )

    # Find missing timestamps
    existing_set = set(start_utc.values)
    missing_timestamps = [ts for ts in full_range if ts not in existing_set]

    # Group by month
    missing_by_month: dict[str, int] = defaultdict(int)
    for ts in missing_timestamps:
        month_key = pd.Timestamp(ts).strftime("%Y-%m")
        missing_by_month[month_key] += 1

    # Sort by month
    missing_by_month = dict(sorted(missing_by_month.items()))

    return GapAnalysis(
        total_missing=total_missing,
        longest_gap_intervals=longest_gap_intervals,
        longest_gap_duration=longest_gap_duration,
        missing_by_month=missing_by_month,
    )


class ImputationStrategy(str, Enum):
    """Specify how to fill in missing data."""

    EXTRAPOLATE_LAST = "extrapolate_last"
    # Could support interpolation in future


def fill_missing_data(
    usage: pd.DataFrame,
    strategy: ImputationStrategy = ImputationStrategy.EXTRAPOLATE_LAST,
) -> pd.DataFrame:
    """
    Fill missing intervals and/or NaN values in interval usage data.

    This function also normalises mixed-grain input by converting all intervals to the
    inferred target grain (the minimum start-to-start delta), splitting longer
    intervals as needed.

    Semantics:
      - kwh is treated as ENERGY over the interval and is allocated proportionally when
        splitting (e.g., 30 min -> two 15 min rows gets half kWh each).
      - kw is treated as an INTERVAL AVERAGE demand and is copied to each split row.

    Requirements:
      - DataFrame must contain 'interval_start' and 'interval_end'.
      - Datetimes must be tz-aware (recommended), or convertible.

    Args:
        usage: Interval usage data.
        strategy: How to fill missing values/intervals.

    Returns:
        A new DataFrame with a complete interval grid at the target grain and imputed values.

    Raises:
        ValueError: If duration cannot be inferred, or intervals cannot be split cleanly.
        KeyError: If required columns are missing.
    """
    if usage.empty:
        return usage

    required_cols = {"interval_start", "interval_end"}
    if not required_cols.issubset(usage.columns):
        raise KeyError(f"Missing required columns: {required_cols - set(usage.columns)}")

    df = usage.copy()

    # 1. Normalize to UTC for internal calculations
    df["interval_start"] = pd.to_datetime(df["interval_start"])
    df["interval_end"] = pd.to_datetime(df["interval_end"])

    # Capture original timezone from the first valid entry
    tz = df["interval_start"].dt.tz

    # Work in UTC to avoid DST ambiguities during math
    df["_start_utc"] = df["interval_start"].dt.tz_convert("UTC") if tz else df["interval_start"]
    df["_end_utc"] = df["interval_end"].dt.tz_convert("UTC") if tz else df["interval_end"]

    # Sort and remove duplicates
    df = df.sort_values("_start_utc").drop_duplicates(subset=["_start_utc"], keep="last")

    if len(df) <= 1:
        if df.isna().any(axis=None):
            raise ValueError("Cannot fill NaNs in a dataset with only one interval.")
        return df.drop(columns=["_start_utc", "_end_utc"])

    # 2. Infer target grain (mode of start-to-start deltas)
    target_grain = df["_start_utc"].diff().min()
    if pd.isna(target_grain) or target_grain <= pd.Timedelta(0):
        raise ValueError("Could not infer a valid interval duration.")

    # 3. Handle Mixed Grain (Splitting longer intervals)
    durations = df["_end_utc"] - df["_start_utc"]

    # Error if intervals cannot be split into the target grain
    if not (durations % target_grain == pd.Timedelta(0)).all():
        # Identify problematic rows for better error messaging
        invalid = df[durations % target_grain != pd.Timedelta(0)]
        raise ValueError(
            f"Intervals found that aren't multiples of {target_grain}: {invalid['interval_start'].tolist()}"
        )

    # Error if intervals overlap (ambiguous what to do)
    gaps = df["_start_utc"].shift(-1) - df["_end_utc"]
    if (gaps < pd.Timedelta(0)).any():
        invalid = df[gaps < pd.Timedelta(0)]
        after_invalid = df[(gaps < pd.Timedelta(0)).shift(1).fillna(False)]
        raise ValueError(
            "Intervals found that overlap with subsequent intervals:\n"
            + "\n".join(
                f"{start} -- {end}"
                for start, end in zip(
                    invalid.interval_start.tolist(), invalid.interval_end.tolist()
                )
            )
            + "\noverlap with\n"
            + "\n".join(
                f"{start} -- {end}"
                for start, end in zip(
                    after_invalid.interval_start.tolist(), after_invalid.interval_end.tolist()
                )
            )
        )

    # Calculate repeat counts
    repeats = (durations / target_grain).astype(int)

    # kWh (Energy) is divided proportionally
    if "kwh" in df.columns:
        df["kwh"] = df["kwh"] / repeats

    # kW (Demand) remains as-is (independent of interval length)

    # Vectorized expansion of the dataframe
    df = df.loc[df.index.repeat(repeats)]

    # Correct the energy/demand values and timestamps in the expanded DF
    group_idx = df.groupby(df.index).cumcount()

    # Update timestamps for sub-intervals
    df["_start_utc"] = df["_start_utc"] + (group_idx * target_grain)
    df["_end_utc"] = df["_start_utc"] + target_grain

    # 4. Reindex to a complete time grid
    full_range = pd.date_range(
        start=df["_start_utc"].min(),
        end=df["_end_utc"].max() - target_grain,
        freq=target_grain,
        tz="UTC" if tz else None,
        name="_start_utc",
    )

    df = df.set_index("_start_utc").reindex(full_range).reset_index()

    # 5. Finalize columns and Impute
    if tz:
        df["interval_start"] = df["_start_utc"].dt.tz_convert(tz)
        df["interval_end"] = (df["_start_utc"] + target_grain).dt.tz_convert(tz)
    else:
        df["interval_start"] = df["_start_utc"]
        df["interval_end"] = df["_start_utc"] + target_grain

    # Drop internal helper columns
    df = df.drop(columns=["_end_utc"])

    # Apply Imputation Strategy
    if strategy == ImputationStrategy.EXTRAPOLATE_LAST:
        impute_cols = [
            c for c in df.columns if c not in ("interval_start", "interval_end", "_start_utc")
        ]
        df[impute_cols] = df[impute_cols].ffill().infer_objects(copy=False)
    else:
        raise ValueError(f"Unsupported strategy: {strategy}")

    return df.drop(columns=["_start_utc"]).reset_index(drop=True)


def validate_usage_dataframe(usage: pd.DataFrame) -> None:
    """
    Validate that the usage DataFrame is in the correct format and complete.

    Checks:
      - Required columns exist
      - interval_start/interval_end are tz-aware and interval_end > interval_start
      - No duplicate interval_start values
      - Grain consistency and missing-interval checks are done in UTC (DST-safe)
      - kwh/kw are numeric; is_weekend/is_holiday are boolean-ish
      - No NaNs anywhere

    Raises:
        ValueError: If validation fails.
    """
    required_columns = [
        "interval_start",
        "interval_end",
        "kwh",
        "kw",
        "is_weekday",
        "is_weekend",
        "is_holiday",
    ]
    missing = [c for c in required_columns if c not in usage.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Got: {list(usage.columns)}")

    if len(usage) == 0:
        raise ValueError("Usage dataframe is empty.")

    df = usage.copy()

    # Parse datetimes
    df["interval_start"] = pd.to_datetime(df["interval_start"], errors="raise")
    df["interval_end"] = pd.to_datetime(df["interval_end"], errors="raise")

    # tz-aware check
    if (
        getattr(df["interval_start"].dt, "tz", None) is None
        or getattr(df["interval_end"].dt, "tz", None) is None
    ):
        raise ValueError("interval_start and interval_end must be timezone-aware datetimes.")

    # Sort before diff-based checks
    df = df.sort_values("interval_start")

    # Basic interval validity (in absolute time; tz-aware subtraction is fine)
    if not (df["interval_end"] > df["interval_start"]).all():
        raise ValueError("All rows must satisfy interval_end > interval_start.")

    # UTC validation for grain and missing intervals (DST-safe)
    start_utc = df["interval_start"].dt.tz_convert("UTC")
    end_utc = df["interval_end"].dt.tz_convert("UTC")

    if start_utc.duplicated().any():
        dupes = df.loc[start_utc.duplicated(), "interval_start"].head(5).tolist()
        raise ValueError(
            "Duplicate interval_start instants found (same UTC time). "
            f"Local timestamps (showing up to 5): {dupes}"
        )

    widths_utc = end_utc - start_utc
    min_w = widths_utc.min()
    max_w = widths_utc.max()
    if min_w != max_w:
        raise ValueError(
            f"Expected consistent interval width in UTC; got min={min_w}, max={max_w}."
        )

    expected = max_w
    start_diffs_utc = start_utc.diff().dropna()
    if not (start_diffs_utc == expected).all():
        bad = start_diffs_utc[start_diffs_utc != expected].head(5)
        raise ValueError(
            "Usage data has missing or irregular intervals (checked in UTC). "
            f"Expected start-to-start delta {expected}; first mismatches: {bad.to_dict()}."
        )

    # No missing data
    if df.isna().any(axis=None):
        counts = df.isna().sum()
        nonzero = counts[counts > 0].to_dict()
        raise ValueError(f"Incomplete usage data; NaN counts by column: {nonzero}.")
