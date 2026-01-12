"""
Unit tests for billing data validation and repair.

Tests data preparation functions used before billing calculations.
"""

import numpy as np
import pandas as pd
import pytest

from billing.core.data import (
    fill_missing_data,
    validate_usage_dataframe,
)


# Fill Missing Data Tests


def test_complete_data_unchanged(usage_df_factory):
    """Verify no modifications when data is already complete."""
    df = usage_df_factory(periods=5)
    result = fill_missing_data(df)

    # Should have same number of rows
    assert len(result) == len(df)

    # All values should be preserved
    pd.testing.assert_frame_equal(
        result.sort_index(axis=1), df.sort_index(axis=1), check_dtype=False
    )


def test_fills_missing_intervals():
    """Verify missing intervals are added to create complete sequence."""
    # Create dataframe with explicit timestamps to control gaps
    starts = pd.date_range("2024-01-01", periods=5, freq="15min", tz="US/Pacific")

    # Create data with missing interval at index 2
    df_with_gaps = pd.DataFrame(
        {
            "interval_start": [starts[0], starts[1], starts[3], starts[4]],  # Skip starts[2]
            "interval_end": [
                starts[0] + pd.Timedelta("15min"),
                starts[1] + pd.Timedelta("15min"),
                starts[3] + pd.Timedelta("15min"),
                starts[4] + pd.Timedelta("15min"),
            ],
            "kwh": [10.0, 11.0, 13.0, 14.0],
            "kw": [40.0, 44.0, 52.0, 56.0],
            "is_weekday": [True, True, True, True],
            "is_weekend": [False, False, False, False],
            "is_holiday": [False, False, False, False],
        }
    )

    result = fill_missing_data(df_with_gaps)

    # Should have all 5 intervals (including the filled gap)
    assert len(result) == 5

    # First values should be preserved
    assert result.iloc[0]["kwh"] == 10.0
    assert result.iloc[1]["kwh"] == 11.0

    # Gap-filled value at index 2 should be forward-filled from index 1
    assert result.iloc[2]["kwh"] == result.iloc[1]["kwh"]


def test_fills_nan_values(usage_df_factory):
    """Verify NaN values are forward-filled."""
    df = usage_df_factory(periods=5)

    # Set some values to NaN
    df.loc[2, "kwh"] = np.nan
    df.loc[3, "kw"] = np.nan

    result = fill_missing_data(df)

    # No NaNs should remain
    assert not result.isna().any().any()

    # Values should be forward-filled
    assert result.iloc[2]["kwh"] == result.iloc[1]["kwh"]
    assert result.iloc[3]["kw"] == result.iloc[2]["kw"]


def test_infers_interval_duration():
    """Verify correct interval duration inference from mode."""
    # Create mostly 15-min intervals with one 30-min gap
    starts = pd.date_range("2024-01-01", periods=5, freq="15min", tz="US/Pacific")
    df = pd.DataFrame(
        {
            "interval_start": [starts[0], starts[1], starts[3], starts[4]],  # Skip starts[2]
            "interval_end": [
                starts[0] + pd.Timedelta("15min"),
                starts[1] + pd.Timedelta("30min"),
                starts[3] + pd.Timedelta("15min"),
                starts[4] + pd.Timedelta("15min"),
            ],
            "kwh": [10.0, 2 * 11.0, 13.0, 14.0],
            "kw": [40.0, 44.0, 52.0, 56.0],
            "is_weekday": [True, True, True, True],
            "is_weekend": [False, False, False, False],
            "is_holiday": [False, False, False, False],
        }
    )

    result = fill_missing_data(df)

    # Should infer 15min and fill the gap
    assert len(result) == 5

    # Check that intervals are evenly spaced at 15 minutes
    diffs = result["interval_start"].diff().dropna()
    assert (diffs == pd.Timedelta("15min")).all()

    # Check that usage in the 30 min interval has been halved in the new intervals
    assert result.iloc[1]["kwh"] == df.iloc[1]["kwh"] / 2
    assert result.iloc[2]["kwh"] == df.iloc[1]["kwh"] / 2


def test_handles_duplicate_starts(usage_df_factory):
    """Verify duplicate interval_start values are handled (keep last)."""
    df = usage_df_factory(periods=4)

    # Add a duplicate row with different value
    duplicate_row = df.iloc[1].copy()
    duplicate_row["kwh"] = 99.9
    df = pd.concat([df, pd.DataFrame([duplicate_row])]).reset_index(drop=True)

    result = fill_missing_data(df)

    # Should have 4 unique intervals
    assert len(result) == 4

    # Should keep the last occurrence (99.9)
    assert result.iloc[1]["kwh"] == 99.9


def test_rejects_overlapping_intervals(usage_df_factory):
    """Verify that overlapping intervals causes an error."""
    df = usage_df_factory(periods=4)

    # Mess up interval_end values
    df.loc[1, "interval_end"] = df.loc[1, "interval_start"] + pd.Timedelta("30min")

    with pytest.raises(ValueError) as exc_info:
        result = fill_missing_data(df)

    assert "overlap" in str(exc_info.value)


def test_single_interval_with_nans_raises_error(usage_df_factory):
    """Verify error when cannot forward-fill (no previous value)."""
    df = usage_df_factory(periods=1)
    df.loc[0, "kwh"] = np.nan

    with pytest.raises(ValueError) as exc_info:
        fill_missing_data(df)

    assert "Cannot fill NaNs" in str(exc_info.value)


def test_single_interval_complete_returns_unchanged(usage_df_factory):
    """Verify single complete row passes through."""
    df = usage_df_factory(periods=1)

    result = fill_missing_data(df)

    assert len(result) == 1
    assert result.iloc[0]["kwh"] == 10.5


def test_missing_required_columns_raises_error():
    """Verify error on missing interval_start or interval_end."""
    df = pd.DataFrame(
        {
            "kwh": [10.0, 11.0],
            "kw": [40.0, 44.0],
        }
    )

    with pytest.raises(KeyError):
        fill_missing_data(df)


def test_timezone_aware_datetimes(usage_df_factory):
    """Verify function preserves timezone information."""
    df = usage_df_factory(periods=3, tz="US/Pacific")

    result = fill_missing_data(df)

    # Check timezone is preserved
    assert result["interval_start"].dt.tz is not None
    assert result["interval_end"].dt.tz is not None
    assert str(result["interval_start"].dt.tz) == "US/Pacific"


# Validate Usage DataFrame Tests


def test_valid_dataframe_passes(usage_df_factory):
    """Verify valid usage DataFrame passes all checks."""
    df = usage_df_factory(periods=10)

    # Should not raise any exception
    validate_usage_dataframe(df)


def test_missing_required_columns_raises_error(usage_df_factory):
    """Verify error when required columns are missing."""
    df = usage_df_factory(periods=3)
    df = df.drop(columns=["kwh"])

    with pytest.raises(ValueError) as exc_info:
        validate_usage_dataframe(df)

    assert "Missing required columns" in str(exc_info.value)
    assert "kwh" in str(exc_info.value)


def test_empty_dataframe_raises_error():
    """Verify error on empty DataFrame."""
    df = pd.DataFrame(
        {
            "interval_start": pd.Series(dtype="datetime64[ns, US/Pacific]"),
            "interval_end": pd.Series(dtype="datetime64[ns, US/Pacific]"),
            "kwh": pd.Series(dtype=float),
            "kw": pd.Series(dtype=float),
            "is_weekday": pd.Series(dtype=bool),
            "is_weekend": pd.Series(dtype=bool),
            "is_holiday": pd.Series(dtype=bool),
        }
    )

    with pytest.raises(ValueError) as exc_info:
        validate_usage_dataframe(df)

    assert "empty" in str(exc_info.value).lower()


def test_non_timezone_aware_raises_error(usage_df_factory):
    """Verify error when timestamps lack timezone."""
    df = usage_df_factory(periods=3)

    # Remove timezone
    df["interval_start"] = df["interval_start"].dt.tz_localize(None)
    df["interval_end"] = df["interval_end"].dt.tz_localize(None)

    with pytest.raises(ValueError) as exc_info:
        validate_usage_dataframe(df)

    assert "timezone-aware" in str(exc_info.value)


def test_interval_end_before_start_raises_error(usage_df_factory):
    """Verify error when interval_end <= interval_start."""
    df = usage_df_factory(periods=3)

    # Swap start and end for one row
    df.loc[1, "interval_end"] = df.loc[1, "interval_start"] - pd.Timedelta("1min")

    with pytest.raises(ValueError) as exc_info:
        validate_usage_dataframe(df)

    assert "interval_end > interval_start" in str(exc_info.value)


def test_duplicate_interval_starts_raises_error(usage_df_factory):
    """Verify error on duplicate interval_start (same UTC time)."""
    df = usage_df_factory(periods=4)

    # Duplicate the second row
    duplicate_row = df.iloc[1].copy()
    df = pd.concat([df, pd.DataFrame([duplicate_row])]).reset_index(drop=True)

    with pytest.raises(ValueError) as exc_info:
        validate_usage_dataframe(df)

    assert "Duplicate" in str(exc_info.value)


def test_inconsistent_interval_widths_raises_error():
    """Verify error when interval durations vary (UTC-based)."""
    starts = pd.date_range("2024-01-01", periods=4, freq="15min", tz="US/Pacific")
    df = pd.DataFrame(
        {
            "interval_start": starts,
            "interval_end": [
                starts[0] + pd.Timedelta("15min"),
                starts[1] + pd.Timedelta("15min"),
                starts[2] + pd.Timedelta("30min"),  # Different width
                starts[3] + pd.Timedelta("15min"),
            ],
            "kwh": 10.5,
            "kw": 42.0,
            "is_weekday": [True] * 4,
            "is_weekend": [False] * 4,
            "is_holiday": [False] * 4,
        }
    )

    with pytest.raises(ValueError) as exc_info:
        validate_usage_dataframe(df)

    assert "consistent interval width" in str(exc_info.value)


def test_missing_intervals_raises_error(usage_df_factory):
    """Verify error when gaps exist in time series."""
    df = usage_df_factory(periods=5)

    # Remove row at index 2 to create gap
    df = df.drop([2]).reset_index(drop=True)

    with pytest.raises(ValueError) as exc_info:
        validate_usage_dataframe(df)

    assert "missing or irregular intervals" in str(exc_info.value)


def test_nan_values_raise_error(usage_df_factory):
    """Verify error when any column has NaN."""
    df = usage_df_factory(periods=4)

    # Add NaN to kwh column
    df.loc[2, "kwh"] = np.nan

    with pytest.raises(ValueError) as exc_info:
        validate_usage_dataframe(df)

    assert "Incomplete usage data" in str(exc_info.value)
    assert "NaN" in str(exc_info.value)


def test_dst_transition_handling():
    """Verify DST transitions handled correctly (UTC validation)."""
    # DST spring forward in US/Pacific: 2024-03-10 02:00 -> 03:00
    # Create intervals that span this transition
    # In UTC, these should still be evenly spaced

    # Start before DST transition
    starts = pd.date_range(
        start="2024-03-10 00:00:00", periods=8, freq="1h", tz="US/Pacific"
    )

    df = pd.DataFrame(
        {
            "interval_start": starts,
            "interval_end": starts + pd.Timedelta("1h"),
            "kwh": 10.5,
            "kw": 42.0,
            "is_weekday": [True] * len(starts),
            "is_weekend": [False] * len(starts),
            "is_holiday": [False] * len(starts),
        }
    )

    # Should pass validation because UTC intervals are consistent
    validate_usage_dataframe(df)
