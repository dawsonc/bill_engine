"""
Unit tests for billing data validation and repair.

Tests data preparation functions used before billing calculations.
"""

import numpy as np
import pandas as pd
from django.test import TestCase

from billing.core.data import (
    fill_missing_data,
    validate_usage_dataframe,
)


def create_valid_usage_df(
    start: str = "2024-01-01 00:00:00",
    periods: int = 4,
    freq: str = "15min",
    tz: str = "US/Pacific",
) -> pd.DataFrame:
    """Create a valid usage DataFrame for testing."""
    interval_starts = pd.date_range(start=start, periods=periods, freq=freq, tz=tz)
    return pd.DataFrame(
        {
            "interval_start": interval_starts,
            "interval_end": interval_starts + pd.Timedelta(freq),
            "kwh": 10.5,
            "kw": 42.0,
            "is_weekend": [False] * periods,
            "is_holiday": [False] * periods,
        }
    )


class FillMissingDataTests(TestCase):
    """Tests for fill_missing_data function."""

    def test_complete_data_unchanged(self):
        """Verify no modifications when data is already complete."""
        df = create_valid_usage_df(periods=5)
        result = fill_missing_data(df)

        # Should have same number of rows
        self.assertEqual(len(result), len(df))

        # All values should be preserved
        pd.testing.assert_frame_equal(
            result.sort_index(axis=1), df.sort_index(axis=1), check_dtype=False
        )

    def test_fills_missing_intervals(self):
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
                "is_weekend": [False, False, False, False],
                "is_holiday": [False, False, False, False],
            }
        )

        result = fill_missing_data(df_with_gaps)

        # Should have all 5 intervals (including the filled gap)
        self.assertEqual(len(result), 5)

        # First values should be preserved
        self.assertEqual(result.iloc[0]["kwh"], 10.0)
        self.assertEqual(result.iloc[1]["kwh"], 11.0)

        # Gap-filled value at index 2 should be forward-filled from index 1
        self.assertEqual(result.iloc[2]["kwh"], result.iloc[1]["kwh"])

    def test_fills_nan_values(self):
        """Verify NaN values are forward-filled."""
        df = create_valid_usage_df(periods=5)

        # Set some values to NaN
        df.loc[2, "kwh"] = np.nan
        df.loc[3, "kw"] = np.nan

        result = fill_missing_data(df)

        # No NaNs should remain
        self.assertFalse(result.isna().any().any())

        # Values should be forward-filled
        self.assertEqual(result.iloc[2]["kwh"], result.iloc[1]["kwh"])
        self.assertEqual(result.iloc[3]["kw"], result.iloc[2]["kw"])

    def test_infers_interval_duration(self):
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
                "is_weekend": [False, False, False, False],
                "is_holiday": [False, False, False, False],
            }
        )

        result = fill_missing_data(df)

        # Should infer 15min and fill the gap
        self.assertEqual(len(result), 5)

        # Check that intervals are evenly spaced at 15 minutes
        diffs = result["interval_start"].diff().dropna()
        self.assertTrue((diffs == pd.Timedelta("15min")).all())

        # Check that usage in the 30 min interval has been halved in the new intervals
        self.assertEqual(result.iloc[1]["kwh"], df.iloc[1]["kwh"] / 2)
        self.assertEqual(result.iloc[2]["kwh"], df.iloc[1]["kwh"] / 2)

    def test_handles_duplicate_starts(self):
        """Verify duplicate interval_start values are handled (keep last)."""
        df = create_valid_usage_df(periods=4)

        # Add a duplicate row with different value
        duplicate_row = df.iloc[1].copy()
        duplicate_row["kwh"] = 99.9
        df = pd.concat([df, pd.DataFrame([duplicate_row])]).reset_index(drop=True)

        result = fill_missing_data(df)

        # Should have 4 unique intervals
        self.assertEqual(len(result), 4)

        # Should keep the last occurrence (99.9)
        self.assertEqual(result.iloc[1]["kwh"], 99.9)

    def test_rejects_overlapping_intervals(self):
        """Verify that overlapping intervals causes an error."""
        df = create_valid_usage_df(periods=4)

        # Mess up interval_end values
        df.loc[1, "interval_end"] = df.loc[1, "interval_start"] + pd.Timedelta("30min")

        with self.assertRaises(ValueError) as context:
            result = fill_missing_data(df)

        self.assertIn("overlap", str(context.exception))

    def test_single_interval_with_nans_raises_error(self):
        """Verify error when cannot forward-fill (no previous value)."""
        df = create_valid_usage_df(periods=1)
        df.loc[0, "kwh"] = np.nan

        with self.assertRaises(ValueError) as context:
            fill_missing_data(df)

        self.assertIn("Cannot fill NaNs", str(context.exception))

    def test_single_interval_complete_returns_unchanged(self):
        """Verify single complete row passes through."""
        df = create_valid_usage_df(periods=1)

        result = fill_missing_data(df)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["kwh"], 10.5)

    def test_missing_required_columns_raises_error(self):
        """Verify error on missing interval_start or interval_end."""
        df = pd.DataFrame(
            {
                "kwh": [10.0, 11.0],
                "kw": [40.0, 44.0],
            }
        )

        with self.assertRaises(KeyError):
            fill_missing_data(df)

    def test_timezone_aware_datetimes(self):
        """Verify function preserves timezone information."""
        df = create_valid_usage_df(periods=3, tz="US/Pacific")

        result = fill_missing_data(df)

        # Check timezone is preserved
        self.assertIsNotNone(result["interval_start"].dt.tz)
        self.assertIsNotNone(result["interval_end"].dt.tz)
        self.assertEqual(str(result["interval_start"].dt.tz), "US/Pacific")


class ValidateUsageDataframeTests(TestCase):
    """Tests for validate_usage_dataframe function."""

    def test_valid_dataframe_passes(self):
        """Verify valid usage DataFrame passes all checks."""
        df = create_valid_usage_df(periods=10)

        # Should not raise any exception
        validate_usage_dataframe(df)

    def test_missing_required_columns_raises_error(self):
        """Verify error when required columns are missing."""
        df = create_valid_usage_df(periods=3)
        df = df.drop(columns=["kwh"])

        with self.assertRaises(ValueError) as context:
            validate_usage_dataframe(df)

        self.assertIn("Missing required columns", str(context.exception))
        self.assertIn("kwh", str(context.exception))

    def test_empty_dataframe_raises_error(self):
        """Verify error on empty DataFrame."""
        df = pd.DataFrame(
            {
                "interval_start": pd.Series(dtype="datetime64[ns, US/Pacific]"),
                "interval_end": pd.Series(dtype="datetime64[ns, US/Pacific]"),
                "kwh": pd.Series(dtype=float),
                "kw": pd.Series(dtype=float),
                "is_weekend": pd.Series(dtype=bool),
                "is_holiday": pd.Series(dtype=bool),
            }
        )

        with self.assertRaises(ValueError) as context:
            validate_usage_dataframe(df)

        self.assertIn("empty", str(context.exception).lower())

    def test_non_timezone_aware_raises_error(self):
        """Verify error when timestamps lack timezone."""
        df = create_valid_usage_df(periods=3)

        # Remove timezone
        df["interval_start"] = df["interval_start"].dt.tz_localize(None)
        df["interval_end"] = df["interval_end"].dt.tz_localize(None)

        with self.assertRaises(ValueError) as context:
            validate_usage_dataframe(df)

        self.assertIn("timezone-aware", str(context.exception))

    def test_interval_end_before_start_raises_error(self):
        """Verify error when interval_end <= interval_start."""
        df = create_valid_usage_df(periods=3)

        # Swap start and end for one row
        df.loc[1, "interval_end"] = df.loc[1, "interval_start"] - pd.Timedelta("1min")

        with self.assertRaises(ValueError) as context:
            validate_usage_dataframe(df)

        self.assertIn("interval_end > interval_start", str(context.exception))

    def test_duplicate_interval_starts_raises_error(self):
        """Verify error on duplicate interval_start (same UTC time)."""
        df = create_valid_usage_df(periods=4)

        # Duplicate the second row
        duplicate_row = df.iloc[1].copy()
        df = pd.concat([df, pd.DataFrame([duplicate_row])]).reset_index(drop=True)

        with self.assertRaises(ValueError) as context:
            validate_usage_dataframe(df)

        self.assertIn("Duplicate", str(context.exception))

    def test_inconsistent_interval_widths_raises_error(self):
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
                "is_weekend": [False] * 4,
                "is_holiday": [False] * 4,
            }
        )

        with self.assertRaises(ValueError) as context:
            validate_usage_dataframe(df)

        self.assertIn("consistent interval width", str(context.exception))

    def test_missing_intervals_raises_error(self):
        """Verify error when gaps exist in time series."""
        df = create_valid_usage_df(periods=5)

        # Remove row at index 2 to create gap
        df = df.drop([2]).reset_index(drop=True)

        with self.assertRaises(ValueError) as context:
            validate_usage_dataframe(df)

        self.assertIn("missing or irregular intervals", str(context.exception))

    def test_nan_values_raise_error(self):
        """Verify error when any column has NaN."""
        df = create_valid_usage_df(periods=4)

        # Add NaN to kwh column
        df.loc[2, "kwh"] = np.nan

        with self.assertRaises(ValueError) as context:
            validate_usage_dataframe(df)

        self.assertIn("Incomplete usage data", str(context.exception))
        self.assertIn("NaN", str(context.exception))

    def test_dst_transition_handling(self):
        """Verify DST transitions handled correctly (UTC validation)."""
        # DST spring forward in US/Pacific: 2024-03-10 02:00 -> 03:00
        # Create intervals that span this transition
        # In UTC, these should still be evenly spaced

        # Start before DST transition
        starts = pd.date_range(start="2024-03-10 00:00:00", periods=8, freq="1h", tz="US/Pacific")

        df = pd.DataFrame(
            {
                "interval_start": starts,
                "interval_end": starts + pd.Timedelta("1h"),
                "kwh": 10.5,
                "kw": 42.0,
                "is_weekend": [False] * len(starts),
                "is_holiday": [False] * len(starts),
            }
        )

        # Should pass validation because UTC intervals are consistent
        validate_usage_dataframe(df)
