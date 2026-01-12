"""
Unit tests for applicability rules.

Tests ApplicabilityRule validation and construct_applicability_mask function.
"""

from datetime import date, time

import pandas as pd
from django.test import TestCase

from billing.core.applicability import construct_applicability_mask
from billing.core.types import ApplicabilityRule, DayType
from billing.tests.test_data import create_valid_usage_df


def create_usage_with_day_types(
    start: str = "2024-01-01 00:00:00",
    periods: int = 24,
    freq: str = "1h",
    tz: str = "US/Pacific",
    is_weekday: bool = True,
    is_weekend: bool = False,
    is_holiday: bool = False,
) -> pd.DataFrame:
    """Create usage DataFrame with specific day type flags."""
    interval_starts = pd.date_range(start=start, periods=periods, freq=freq, tz=tz)
    return pd.DataFrame(
        {
            "interval_start": interval_starts,
            "interval_end": interval_starts + pd.Timedelta(freq),
            "kwh": 10.5,
            "kw": 42.0,
            "is_weekday": [is_weekday] * periods,
            "is_weekend": [is_weekend] * periods,
            "is_holiday": [is_holiday] * periods,
        }
    )


def create_multi_day_usage(
    start: str = "2024-01-01 00:00:00",
    days: int = 7,
    freq: str = "15min",
    tz: str = "US/Pacific",
) -> pd.DataFrame:
    """Create usage DataFrame spanning multiple days with correct day type flags.

    Start date should be a Monday (2024-01-01 is a Monday).
    Sets is_weekday for Mon-Fri, is_weekend for Sat-Sun.
    """
    # Calculate number of periods based on frequency
    if freq.endswith("h"):
        # Hourly frequency (e.g., "1h")
        hours_per_period = int(freq.rstrip("h"))
        periods = days * 24 // hours_per_period
    elif freq.endswith("min"):
        # Minute frequency (e.g., "15min")
        minutes_per_period = int(freq.rstrip("min"))
        periods = days * 24 * (60 // minutes_per_period)
    else:
        raise ValueError(f"Unsupported frequency format: {freq}")

    interval_starts = pd.date_range(start=start, periods=periods, freq=freq, tz=tz)

    # Monday = 0, Sunday = 6
    day_of_week = interval_starts.dayofweek
    is_weekday = (day_of_week >= 0) & (day_of_week <= 4)  # Mon-Fri
    is_weekend = (day_of_week >= 5) & (day_of_week <= 6)  # Sat-Sun

    return pd.DataFrame(
        {
            "interval_start": interval_starts,
            "interval_end": interval_starts + pd.Timedelta(freq),
            "kwh": 10.5,
            "kw": 42.0,
            "is_weekday": is_weekday,
            "is_weekend": is_weekend,
            "is_holiday": [False] * periods,
        }
    )


class ApplicabilityRuleValidationTests(TestCase):
    """Tests for ApplicabilityRule dataclass validation logic."""

    def test_period_start_equals_period_end_raises_error(self):
        """Verify period_start >= period_end raises ValueError."""
        with self.assertRaises(ValueError) as context:
            ApplicabilityRule(period_start=time(9, 0), period_end=time(9, 0))

        self.assertIn("period_start must be strictly earlier", str(context.exception))

    def test_period_start_after_period_end_raises_error(self):
        """Verify period_start > period_end raises ValueError."""
        with self.assertRaises(ValueError) as context:
            ApplicabilityRule(period_start=time(17, 0), period_end=time(9, 0))

        self.assertIn("period_start must be strictly earlier", str(context.exception))

    def test_start_date_after_end_date_raises_error(self):
        """Verify start_date > end_date raises ValueError."""
        with self.assertRaises(ValueError) as context:
            ApplicabilityRule(
                start_date=date(2024, 12, 31), end_date=date(2024, 1, 1)
            )

        self.assertIn("start_date must be earlier", str(context.exception))

    def test_start_date_equals_end_date_is_valid(self):
        """Verify start_date == end_date is allowed."""
        rule = ApplicabilityRule(
            start_date=date(2024, 6, 15), end_date=date(2024, 6, 15)
        )

        self.assertEqual(rule.start_date, date(2024, 6, 15))
        self.assertEqual(rule.end_date, date(2024, 6, 15))


class ConstructApplicabilityMaskDayTypesTests(TestCase):
    """Tests for day type filtering logic."""

    def test_weekday_only_rule(self):
        """Rule applies only to weekdays."""
        usage = create_usage_with_day_types(is_weekday=True, is_weekend=False)
        rule = ApplicabilityRule(day_types=frozenset([DayType.WEEKDAY]))

        result = construct_applicability_mask(usage, rule)

        # All intervals should match (all are weekdays)
        self.assertTrue(result.all())

    def test_weekend_only_rule(self):
        """Rule applies only to weekends."""
        usage = create_usage_with_day_types(is_weekday=False, is_weekend=True)
        rule = ApplicabilityRule(day_types=frozenset([DayType.WEEKEND]))

        result = construct_applicability_mask(usage, rule)

        # All intervals should match (all are weekends)
        self.assertTrue(result.all())

    def test_holiday_only_rule(self):
        """Rule applies only to holidays."""
        usage = create_usage_with_day_types(is_weekday=True, is_holiday=True)
        rule = ApplicabilityRule(day_types=frozenset([DayType.HOLIDAY]))

        result = construct_applicability_mask(usage, rule)

        # All intervals should match (all are holidays)
        self.assertTrue(result.all())

    def test_weekday_and_weekend_rule(self):
        """Rule applies to both weekdays and weekends."""
        usage = create_multi_day_usage(days=7)  # Full week
        rule = ApplicabilityRule(
            day_types=frozenset([DayType.WEEKDAY, DayType.WEEKEND])
        )

        result = construct_applicability_mask(usage, rule)

        # All intervals should match (covers both weekdays and weekends)
        self.assertTrue(result.all())

    def test_all_day_types_rule(self):
        """Rule applies to all days (default behavior)."""
        usage = create_multi_day_usage(days=7)
        rule = ApplicabilityRule()  # Default includes all day types

        result = construct_applicability_mask(usage, rule)

        # All intervals should match (no restrictions)
        self.assertTrue(result.all())

    def test_empty_day_types_matches_nothing(self):
        """Empty day_types should match no rows."""
        usage = create_multi_day_usage(days=7)
        rule = ApplicabilityRule(day_types=frozenset())

        result = construct_applicability_mask(usage, rule)

        # No intervals should match
        self.assertFalse(result.any())

    def test_mixed_week_with_holiday(self):
        """Test dataset with mixed day types including holiday."""
        usage = create_multi_day_usage(days=7)
        # Mark Friday (day 4) as a holiday
        usage.loc[usage["interval_start"].dt.dayofweek == 4, "is_holiday"] = True

        # Rule for holidays only
        rule = ApplicabilityRule(day_types=frozenset([DayType.HOLIDAY]))
        result = construct_applicability_mask(usage, rule)

        # Only Friday intervals should match
        expected = usage["is_holiday"]
        pd.testing.assert_series_equal(result, expected, check_names=False)


class ConstructApplicabilityMaskTimeFilteringTests(TestCase):
    """Tests for time-of-day filtering logic."""

    def setUp(self):
        """Create fixture data for time filtering tests."""
        # Create 24 hours of hourly data starting at midnight
        self.usage = create_usage_with_day_types(
            start="2024-01-01 00:00:00", periods=24, freq="1h"
        )

    def test_period_start_only(self):
        """Filter with only period_start (no end)."""
        rule = ApplicabilityRule(period_start=time(12, 0))

        result = construct_applicability_mask(self.usage, rule)

        # Should match intervals from 12:00 onwards (12:00-23:00)
        expected_hours = list(range(12, 24))
        matching_indices = [i for i, row in self.usage.iterrows()
                           if row["interval_start"].hour in expected_hours]

        self.assertEqual(result.sum(), len(expected_hours))
        for idx in matching_indices:
            self.assertTrue(result.iloc[idx])

    def test_period_end_only(self):
        """Filter with only period_end (no start)."""
        rule = ApplicabilityRule(period_end=time(12, 0))

        result = construct_applicability_mask(self.usage, rule)

        # Should match intervals before 12:00 (00:00-11:00)
        expected_hours = list(range(0, 12))

        self.assertEqual(result.sum(), len(expected_hours))
        for i in expected_hours:
            self.assertTrue(result.iloc[i])

    def test_period_start_and_end(self):
        """Filter with both start and end times."""
        rule = ApplicabilityRule(period_start=time(9, 0), period_end=time(17, 0))

        result = construct_applicability_mask(self.usage, rule)

        # Should match intervals from 9:00 to 16:00 (9:00 <= t < 17:00)
        expected_hours = list(range(9, 17))

        self.assertEqual(result.sum(), len(expected_hours))
        for i in expected_hours:
            self.assertTrue(result.iloc[i])

    def test_period_boundary_inclusive_start(self):
        """Interval exactly at period_start is included."""
        rule = ApplicabilityRule(period_start=time(10, 0), period_end=time(15, 0))

        result = construct_applicability_mask(self.usage, rule)

        # 10:00 should be included
        self.assertTrue(result.iloc[10])

    def test_period_boundary_exclusive_end(self):
        """Interval exactly at period_end is excluded."""
        rule = ApplicabilityRule(period_start=time(10, 0), period_end=time(15, 0))

        result = construct_applicability_mask(self.usage, rule)

        # 15:00 should be excluded
        self.assertFalse(result.iloc[15])
        # 14:00 should be included
        self.assertTrue(result.iloc[14])

    def test_no_time_constraints(self):
        """Both None means apply to all times."""
        rule = ApplicabilityRule(period_start=None, period_end=None)

        result = construct_applicability_mask(self.usage, rule)

        # All intervals should match
        self.assertTrue(result.all())

    def test_midnight_boundary(self):
        """Test behavior at 00:00:00."""
        rule = ApplicabilityRule(period_start=time(0, 0), period_end=time(6, 0))

        result = construct_applicability_mask(self.usage, rule)

        # Should match 00:00 through 05:00
        self.assertTrue(result.iloc[0])  # 00:00
        self.assertTrue(result.iloc[5])  # 05:00
        self.assertFalse(result.iloc[6])  # 06:00

    def test_end_of_day_boundary(self):
        """Test behavior near 23:59:59."""
        rule = ApplicabilityRule(period_start=time(20, 0), period_end=time(23, 59, 59))

        result = construct_applicability_mask(self.usage, rule)

        # Should match 20:00 through 22:00 (23:00 is at 23:00:00, before 23:59:59)
        self.assertTrue(result.iloc[20])  # 20:00
        self.assertTrue(result.iloc[23])  # 23:00
        self.assertEqual(result.sum(), 4)  # 20:00, 21:00, 22:00, 23:00


class ConstructApplicabilityMaskDateFilteringTests(TestCase):
    """Tests for date range filtering logic."""

    def setUp(self):
        """Create fixture data for date filtering tests."""
        # Create data spanning full month of January 2024 (hourly)
        self.usage = create_usage_with_day_types(
            start="2024-01-01 00:00:00", periods=31 * 24, freq="1h"
        )

    def test_start_date_only(self):
        """Filter with only start_date (no end)."""
        rule = ApplicabilityRule(start_date=date(2024, 1, 15))

        result = construct_applicability_mask(self.usage, rule)

        # Should match intervals from Jan 15 onwards
        matched_dates = self.usage[result]["interval_start"].dt.date.unique()

        self.assertTrue(all(d >= date(2024, 1, 15) for d in matched_dates))
        # Should include Jan 15 through Jan 31 (17 days)
        self.assertEqual(result.sum(), 17 * 24)

    def test_end_date_only(self):
        """Filter with only end_date (no start)."""
        rule = ApplicabilityRule(end_date=date(2024, 1, 15))

        result = construct_applicability_mask(self.usage, rule)

        # Should match intervals before Jan 15 (Jan 1-14)
        matched_dates = self.usage[result]["interval_start"].dt.date.unique()

        self.assertTrue(all(d < date(2024, 1, 15) for d in matched_dates))
        # Should include Jan 1 through Jan 14 (14 days)
        self.assertEqual(result.sum(), 14 * 24)

    def test_start_and_end_date(self):
        """Filter with both start and end dates."""
        rule = ApplicabilityRule(
            start_date=date(2024, 1, 10), end_date=date(2024, 1, 20)
        )

        result = construct_applicability_mask(self.usage, rule)

        # Should match Jan 10-19 (10 days)
        matched_dates = self.usage[result]["interval_start"].dt.date.unique()

        self.assertTrue(all(date(2024, 1, 10) <= d < date(2024, 1, 20)
                           for d in matched_dates))
        self.assertEqual(result.sum(), 10 * 24)

    def test_date_boundary_inclusive_start(self):
        """Interval on start_date is included."""
        rule = ApplicabilityRule(
            start_date=date(2024, 1, 10), end_date=date(2024, 1, 15)
        )

        result = construct_applicability_mask(self.usage, rule)

        # First interval on Jan 10 should be included
        jan_10_intervals = self.usage[
            self.usage["interval_start"].dt.date == date(2024, 1, 10)
        ]
        first_jan_10_idx = jan_10_intervals.index[0]

        self.assertTrue(result.loc[first_jan_10_idx])

    def test_date_boundary_exclusive_end(self):
        """Interval on end_date is excluded."""
        rule = ApplicabilityRule(
            start_date=date(2024, 1, 10), end_date=date(2024, 1, 15)
        )

        result = construct_applicability_mask(self.usage, rule)

        # All intervals on Jan 15 should be excluded
        jan_15_intervals = self.usage[
            self.usage["interval_start"].dt.date == date(2024, 1, 15)
        ]

        for idx in jan_15_intervals.index:
            self.assertFalse(result.loc[idx])

    def test_no_date_constraints(self):
        """Both None means apply to all dates."""
        rule = ApplicabilityRule(start_date=None, end_date=None)

        result = construct_applicability_mask(self.usage, rule)

        # All intervals should match
        self.assertTrue(result.all())

    def test_single_day_rule(self):
        """start_date == end_date should match nothing (exclusive end)."""
        rule = ApplicabilityRule(
            start_date=date(2024, 1, 15), end_date=date(2024, 1, 15)
        )

        result = construct_applicability_mask(self.usage, rule)

        # No intervals should match (date >= 2024-01-15 AND date < 2024-01-15 is impossible)
        self.assertFalse(result.any())

    def test_multi_month_date_range(self):
        """Date range spanning multiple months."""
        # Create data spanning Dec 2023 - Feb 2024
        usage = create_usage_with_day_types(
            start="2023-12-15 00:00:00", periods=60 * 24, freq="1h"
        )

        rule = ApplicabilityRule(
            start_date=date(2024, 1, 1), end_date=date(2024, 2, 1)
        )

        result = construct_applicability_mask(usage, rule)

        # Should match all of January 2024 only
        matched_dates = usage[result]["interval_start"].dt.date.unique()

        self.assertTrue(all(date(2024, 1, 1) <= d < date(2024, 2, 1)
                           for d in matched_dates))
        # Should be 31 days in January
        self.assertEqual(result.sum(), 31 * 24)


class ConstructApplicabilityMaskCombinedTests(TestCase):
    """Tests for combined filtering (day types + times + dates together)."""

    def setUp(self):
        """Create fixture data for combined filtering tests."""
        # Create a full week of hourly data starting Monday Jan 1, 2024
        self.usage = create_multi_day_usage(
            start="2024-01-01 00:00:00", days=7, freq="1h"
        )

    def test_weekday_peak_hours(self):
        """Weekdays during peak hours (9am-5pm)."""
        rule = ApplicabilityRule(
            day_types=frozenset([DayType.WEEKDAY]),
            period_start=time(9, 0),
            period_end=time(17, 0),
        )

        result = construct_applicability_mask(self.usage, rule)

        # Should only match weekday intervals between 9am-5pm
        matched_data = self.usage[result]

        # All matched intervals should be weekdays
        self.assertTrue(matched_data["is_weekday"].all())
        # All matched intervals should be in time range [9, 17)
        matched_hours = matched_data["interval_start"].dt.hour
        self.assertTrue(all((9 <= h < 17) for h in matched_hours))

        # Should be 5 weekdays * 8 hours = 40 intervals
        self.assertEqual(result.sum(), 5 * 8)

    def test_summer_weekday_afternoon(self):
        """Date range + day type + time."""
        # Create data spanning May-August 2024
        usage = create_multi_day_usage(
            start="2024-05-01 00:00:00", days=120, freq="1h"
        )

        rule = ApplicabilityRule(
            day_types=frozenset([DayType.WEEKDAY]),
            period_start=time(12, 0),
            period_end=time(18, 0),
            start_date=date(2024, 6, 1),
            end_date=date(2024, 9, 1),
        )

        result = construct_applicability_mask(usage, rule)

        matched_data = usage[result]

        # All matched intervals should be weekdays
        self.assertTrue(matched_data["is_weekday"].all())
        # All matched intervals should be in time range [12, 18)
        matched_hours = matched_data["interval_start"].dt.hour
        self.assertTrue(all((12 <= h < 18) for h in matched_hours))
        # All matched dates should be in June-August
        matched_dates = matched_data["interval_start"].dt.date
        self.assertTrue(all(date(2024, 6, 1) <= d < date(2024, 9, 1)
                           for d in matched_dates))

    def test_all_constraints_none_applies_everywhere(self):
        """No constraints = all intervals match."""
        rule = ApplicabilityRule()

        result = construct_applicability_mask(self.usage, rule)

        # All intervals should match
        self.assertTrue(result.all())
        self.assertEqual(result.sum(), len(self.usage))

    def test_restrictive_combined_filters(self):
        """Very restrictive combination."""
        # Mark Tuesday as a holiday
        self.usage.loc[
            self.usage["interval_start"].dt.dayofweek == 1, "is_holiday"
        ] = True

        rule = ApplicabilityRule(
            day_types=frozenset([DayType.HOLIDAY]),
            period_start=time(14, 0),
            period_end=time(15, 0),
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 3),
        )

        result = construct_applicability_mask(self.usage, rule)

        matched_data = self.usage[result]

        # Should only match Tuesday Jan 2 at 14:00 (1 interval)
        self.assertEqual(result.sum(), 1)
        if result.sum() > 0:
            matched_interval = matched_data.iloc[0]
            self.assertTrue(matched_interval["is_holiday"])
            self.assertEqual(matched_interval["interval_start"].hour, 14)
            self.assertEqual(matched_interval["interval_start"].date(), date(2024, 1, 2))


class ConstructApplicabilityMaskEdgeCasesTests(TestCase):
    """Tests for edge cases and error handling."""

    def test_dst_transition_time_handling(self):
        """DST transition handled correctly."""
        # DST spring forward in US/Pacific: 2024-03-10 02:00 -> 03:00
        # Create intervals spanning this transition
        usage = create_usage_with_day_types(
            start="2024-03-10 00:00:00", periods=24, freq="1h", tz="US/Pacific"
        )

        # Rule that would include the "missing" 2am hour if it existed
        rule = ApplicabilityRule(period_start=time(0, 0), period_end=time(12, 0))

        result = construct_applicability_mask(usage, rule)

        # Should handle DST transition gracefully
        # The function works with local times, so intervals exist for all local hours
        matched_data = usage[result]
        matched_hours = matched_data["interval_start"].dt.hour

        # Should include hours 0-11
        self.assertTrue(all(h < 12 for h in matched_hours))

    def test_leap_day_handling(self):
        """Feb 29 on leap year works correctly."""
        # 2024 is a leap year
        usage = create_usage_with_day_types(
            start="2024-02-28 00:00:00", periods=72, freq="1h"  # 3 days
        )

        rule = ApplicabilityRule(
            start_date=date(2024, 2, 29), end_date=date(2024, 3, 1)
        )

        result = construct_applicability_mask(usage, rule)

        # Should match only Feb 29
        matched_data = usage[result]
        matched_dates = matched_data["interval_start"].dt.date.unique()

        self.assertEqual(len(matched_dates), 1)
        self.assertEqual(matched_dates[0], date(2024, 2, 29))
        self.assertEqual(result.sum(), 24)  # 24 hours on Feb 29
