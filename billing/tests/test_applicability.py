"""
Unit tests for applicability rules.

Tests ApplicabilityRule validation and construct_applicability_mask function.
"""

from datetime import date, time

import pandas as pd
import pytest

from billing.core.applicability import construct_applicability_mask
from billing.core.types import ApplicabilityRule, DayType

# Validation Tests


@pytest.mark.parametrize(
    "period_start_local,period_end_local,start_date,end_date,should_raise,error_msg",
    [
        # Time validations - invalid cases
        (
            time(9, 0),
            time(9, 0),
            None,
            None,
            True,
            "period_start_local must be strictly earlier",
        ),
        (
            time(17, 0),
            time(9, 0),
            None,
            None,
            True,
            "period_start_local must be strictly earlier",
        ),
        # Date validations - invalid case (using year 2000 convention)
        (
            None,
            None,
            date(2000, 12, 31),
            date(2000, 1, 1),
            True,
            "start_date must be earlier",
        ),
        # Date validations - valid case (equal dates allowed)
        (None, None, date(2000, 6, 15), date(2000, 6, 15), False, None),
    ],
)
def test_applicability_rule_validation(
    period_start_local, period_end_local, start_date, end_date, should_raise, error_msg
):
    """Test ApplicabilityRule validation for time and date constraints."""
    if should_raise:
        with pytest.raises(ValueError) as exc_info:
            ApplicabilityRule(
                period_start_local=period_start_local,
                period_end_local=period_end_local,
                start_date=start_date,
                end_date=end_date,
            )
        assert error_msg in str(exc_info.value)
    else:
        rule = ApplicabilityRule(
            period_start_local=period_start_local,
            period_end_local=period_end_local,
            start_date=start_date,
            end_date=end_date,
        )
        assert rule.start_date == start_date
        assert rule.end_date == end_date


# Day Type Filtering Tests


def test_mixed_week(full_week_usage):
    """Rule applies correctly to weekdays and weekends."""
    weekday_rule = ApplicabilityRule(day_types=frozenset([DayType.WEEKDAY]))
    result = construct_applicability_mask(full_week_usage, (weekday_rule,))
    assert result.sum() == 5 * 24  # five weekdays in a week

    weekend_rule = ApplicabilityRule(day_types=frozenset([DayType.WEEKEND]))
    result = construct_applicability_mask(full_week_usage, (weekend_rule,))
    assert result.sum() == 2 * 24  # two weekends in a week


def test_mixed_week_with_holiday(full_week_usage):
    """Test dataset with mixed day types including holiday."""
    # Mark Friday (day 4) as a holiday
    full_week_usage.loc[full_week_usage["interval_start"].dt.dayofweek == 4, "is_holiday"] = True

    # Rule for holidays only
    rule = ApplicabilityRule(day_types=frozenset([DayType.HOLIDAY]))
    result = construct_applicability_mask(full_week_usage, (rule,))

    # Only Friday intervals should match
    expected = full_week_usage["is_holiday"]
    pd.testing.assert_series_equal(result, expected, check_names=False)


# Time Filtering Tests


def test_period_start_local_only(hourly_day_usage):
    """Filter with only period_start_local (no end)."""
    rule = ApplicabilityRule(period_start_local=time(12, 0))

    result = construct_applicability_mask(hourly_day_usage, (rule,))

    # Should match intervals from 12:00 onwards (12:00-23:00)
    expected_hours = list(range(12, 24))
    matching_indices = [
        i for i, row in hourly_day_usage.iterrows() if row["interval_start"].hour in expected_hours
    ]

    assert result.sum() == len(expected_hours)
    for idx in matching_indices:
        assert result.iloc[idx]


def test_period_end_local_only(hourly_day_usage):
    """Filter with only period_end_local (no start)."""
    rule = ApplicabilityRule(period_end_local=time(12, 0))

    result = construct_applicability_mask(hourly_day_usage, (rule,))

    # Should match intervals before 12:00 (00:00-11:00)
    expected_hours = list(range(0, 12))

    assert result.sum() == len(expected_hours)
    for i in expected_hours:
        assert result.iloc[i]


def test_period_start_local_and_end(hourly_day_usage):
    """Filter with both start and end times."""
    rule = ApplicabilityRule(period_start_local=time(9, 0), period_end_local=time(17, 0))

    result = construct_applicability_mask(hourly_day_usage, (rule,))

    # Should match intervals from 9:00 to 16:00 (9:00 <= t < 17:00)
    expected_hours = list(range(9, 17))

    assert result.sum() == len(expected_hours)
    for i in expected_hours:
        assert result.iloc[i]


@pytest.mark.parametrize(
    "period_start_local,period_end_local,expected_hours,inclusive_hour,exclusive_hour",
    [
        # Normal range with explicit boundary checks
        (time(10, 0), time(15, 0), list(range(10, 15)), 10, 15),
        # Midnight boundary
        (time(0, 0), time(6, 0), list(range(0, 6)), 0, 6),
        # End of day boundary
        (time(20, 0), time(23, 59, 59), list(range(20, 24)), 20, None),
    ],
)
def test_time_boundary_filtering(
    hourly_day_usage,
    period_start_local,
    period_end_local,
    expected_hours,
    inclusive_hour,
    exclusive_hour,
):
    """Test time filtering with various boundary conditions (inclusive start, exclusive end)."""
    rule = ApplicabilityRule(
        period_start_local=period_start_local, period_end_local=period_end_local
    )
    result = construct_applicability_mask(hourly_day_usage, (rule,))

    assert result.sum() == len(expected_hours)
    for hour in expected_hours:
        assert result.iloc[hour]

    # Verify boundary conditions
    assert result.iloc[inclusive_hour]  # Start is inclusive
    if exclusive_hour is not None:
        assert not result.iloc[exclusive_hour]  # End is exclusive


def test_no_time_constraints(hourly_day_usage):
    """Both None means apply to all times."""
    rule = ApplicabilityRule(period_start_local=None, period_end_local=None)

    result = construct_applicability_mask(hourly_day_usage, (rule,))

    # All intervals should match
    assert result.all()


# Date Filtering Tests


def test_start_date_only(month_usage):
    """Filter with only start_date (no end), using year 2000 convention."""
    # Rule uses year 2000, but should match usage from any year (month_usage is 2024)
    rule = ApplicabilityRule(start_date=date(2000, 1, 15))

    result = construct_applicability_mask(month_usage, (rule,))

    # Should match intervals from Jan 15 onwards (month/day only)
    matched_dates = month_usage[result]["interval_start"].dt.date.unique()

    assert all(d.month == 1 and d.day >= 15 for d in matched_dates)
    # Should include Jan 15 through Jan 31 (17 days)
    assert result.sum() == 17 * 24


def test_end_date_only(month_usage):
    """Filter with only end_date (no start), using year 2000 convention."""
    # Rule uses year 2000, but should match usage from any year (month_usage is 2024)
    rule = ApplicabilityRule(end_date=date(2000, 1, 15))

    result = construct_applicability_mask(month_usage, (rule,))

    # Should match intervals through Jan 15 (Jan 1-15)
    matched_dates = month_usage[result]["interval_start"].dt.date.unique()

    # Should include Jan 1 through Jan 15 (15 days)
    assert all(d.month == 1 and d.day <= 15 for d in matched_dates)
    assert result.sum() == 15 * 24


def test_start_and_end_date(month_usage):
    """Filter with both start and end dates, using year 2000 convention."""
    # Rule uses year 2000, but should match usage from any year (month_usage is 2024)
    rule = ApplicabilityRule(start_date=date(2000, 1, 10), end_date=date(2000, 1, 20))

    result = construct_applicability_mask(month_usage, (rule,))

    # Should match Jan 10-20 (11 days)
    matched_dates = month_usage[result]["interval_start"].dt.date.unique()

    assert all(d.month == 1 and 10 <= d.day <= 20 for d in matched_dates)
    assert result.sum() == 11 * 24


@pytest.mark.parametrize(
    "test_date,should_match",
    [
        (date(2024, 1, 9), False),  # outside range
        (date(2024, 1, 10), True),  # start_date: inclusive
        (date(2024, 1, 14), True),  # within range
        (date(2024, 1, 15), True),  # end_date: inclusive
        (date(2024, 1, 16), False),  # outside range
    ],
)
def test_date_boundary_filtering(month_usage, test_date, should_match):
    """Test date filtering boundary conditions (inclusive start, inclusive end)."""
    # Rule uses year 2000, but should match usage from 2024 (month_usage fixture)
    rule = ApplicabilityRule(start_date=date(2000, 1, 10), end_date=date(2000, 1, 15))
    result = construct_applicability_mask(month_usage, (rule,))

    test_intervals = month_usage[month_usage["interval_start"].dt.date == test_date]
    for idx in test_intervals.index:
        assert result.loc[idx] == should_match


def test_no_date_constraints(month_usage):
    """Both None means apply to all dates."""
    rule = ApplicabilityRule(start_date=None, end_date=None)

    result = construct_applicability_mask(month_usage, (rule,))

    # All intervals should match
    assert result.all()


def test_single_day_rule(month_usage):
    """start_date == end_date should match just one day (inclusive end)."""
    # Rule uses year 2000, but should match usage from 2024
    rule = ApplicabilityRule(start_date=date(2000, 1, 15), end_date=date(2000, 1, 15))

    result = construct_applicability_mask(month_usage, (rule,))

    # One day should match (Jan 15 regardless of year)
    # since both start and end dates are inclusive.
    matched_dates = month_usage[result]["interval_start"].dt.date.unique()
    assert all(d.month == 1 and d.day == 15 for d in matched_dates)
    assert result.sum() == 1 * 24


def test_multi_month_date_range(usage_df_factory):
    """Date range spanning multiple months, using year 2000 convention."""
    # Create data spanning Dec 2023 - Feb 2024
    usage = usage_df_factory(start="2023-12-15 00:00:00", periods=60 * 24, freq="1h")

    # Rule uses year 2000 for month/day only comparison
    rule = ApplicabilityRule(start_date=date(2000, 1, 1), end_date=date(2000, 1, 31))

    result = construct_applicability_mask(usage, (rule,))

    # Should match all January dates from both 2023 and 2024 data
    matched_dates = usage[result]["interval_start"].dt.date.unique()

    assert all(d.month == 1 and 1 <= d.day <= 31 for d in matched_dates)
    # Should be 31 days in January (all from 2024 since Dec 2023 doesn't have Jan)
    assert result.sum() == 31 * 24


def test_date_matches_across_years(usage_df_factory):
    """Dates with year 2000 should match usage from any year."""
    # Create data from 2025
    usage_2025 = usage_df_factory(start="2025-06-01 00:00:00", periods=30 * 24, freq="1h")

    # Rule uses year 2000 - should still match June 2025 data
    rule = ApplicabilityRule(start_date=date(2000, 6, 1), end_date=date(2000, 6, 30))

    result = construct_applicability_mask(usage_2025, (rule,))

    # All 30 days of June should match, regardless of year
    matched_dates = usage_2025[result]["interval_start"].dt.date.unique()
    assert len(matched_dates) == 30
    assert all(d.month == 6 for d in matched_dates)
    assert result.sum() == 30 * 24


# Combined Filtering Tests


def test_weekday_peak_hours(full_week_usage):
    """Weekdays during peak hours (9am-5pm)."""
    rule = ApplicabilityRule(
        day_types=frozenset([DayType.WEEKDAY]),
        period_start_local=time(9, 0),
        period_end_local=time(17, 0),
    )

    result = construct_applicability_mask(full_week_usage, (rule,))

    # Should only match weekday intervals between 9am-5pm
    matched_data = full_week_usage[result]

    # All matched intervals should be weekdays
    assert matched_data["is_weekday"].all()
    # All matched intervals should be in time range [9, 17)
    matched_hours = matched_data["interval_start"].dt.hour
    assert all((9 <= h < 17) for h in matched_hours)

    # Should be 5 weekdays * 8 hours = 40 intervals
    assert result.sum() == 5 * 8


def test_summer_weekday_afternoon(usage_df_factory):
    """Date range + day type + time, using year 2000 convention."""
    # Create data spanning May-September 2024
    usage = usage_df_factory(start="2024-05-01 00:00:00", periods=150 * 24, freq="1h")

    # Rule uses year 2000 for month/day only comparison
    rule = ApplicabilityRule(
        day_types=frozenset([DayType.WEEKDAY]),
        period_start_local=time(12, 0),
        period_end_local=time(18, 0),
        start_date=date(2000, 6, 1),
        end_date=date(2000, 9, 1),
    )

    result = construct_applicability_mask(usage, (rule,))

    matched_data = usage[result]

    # All matched intervals should be weekdays
    assert matched_data["is_weekday"].all()
    # All matched intervals should be in time range [12, 18)
    matched_hours = matched_data["interval_start"].dt.hour
    assert all((12 <= h < 18) for h in matched_hours)
    # All matched dates should be in June-September (month/day only)
    matched_dates = matched_data["interval_start"].dt.date
    assert all(6 <= d.month <= 9 or (d.month == 9 and d.day == 1) for d in matched_dates)


def test_all_constraints_none_applies_everywhere(full_week_usage):
    """No constraints = all intervals match."""
    rule = ApplicabilityRule()

    result = construct_applicability_mask(full_week_usage, (rule,))

    # All intervals should match
    assert result.all()
    assert result.sum() == len(full_week_usage)


def test_restrictive_combined_filters(full_week_usage):
    """Very restrictive combination, using year 2000 convention."""
    # Mark Tuesday as a holiday
    full_week_usage.loc[full_week_usage["interval_start"].dt.dayofweek == 1, "is_holiday"] = True

    # Rule uses year 2000 for month/day only comparison
    rule = ApplicabilityRule(
        day_types=frozenset([DayType.HOLIDAY]),
        period_start_local=time(14, 0),
        period_end_local=time(15, 0),
        start_date=date(2000, 1, 2),
        end_date=date(2000, 1, 3),
    )

    result = construct_applicability_mask(full_week_usage, (rule,))

    matched_data = full_week_usage[result]

    # Should only match Tuesday Jan 2 at 14:00 (1 interval)
    assert result.sum() == 1
    if result.sum() > 0:
        matched_interval = matched_data.iloc[0]
        assert matched_interval["is_holiday"]
        assert matched_interval["interval_start"].hour == 14
        assert matched_interval["interval_start"].month == 1
        assert matched_interval["interval_start"].day == 2


# Edge Case Tests


@pytest.mark.parametrize(
    "start,periods,freq,rule_params,expected_match_count,description",
    [
        # DST spring forward in US/Pacific: 2024-03-10 02:00 -> 03:00
        (
            "2024-03-10 00:00:00",
            24,
            "1h",
            {"period_start_local": time(0, 0), "period_end_local": time(12, 0)},
            12,
            "DST transition handles missing hour",
        ),
        # Leap day test (2024 is leap year) - using year 2000 convention
        (
            "2024-02-28 00:00:00",
            72,
            "1h",
            {"start_date": date(2000, 2, 28), "end_date": date(2000, 3, 1)},
            24 * 3,
            "Leap day Feb 29 handled correctly with year 2000 dates",
        ),
    ],
)
def test_edge_cases(
    usage_df_factory, start, periods, freq, rule_params, expected_match_count, description
):
    """Test edge cases: DST transitions and leap days."""
    usage = usage_df_factory(start=start, periods=periods, freq=freq, tz="US/Pacific")
    rule = ApplicabilityRule(**rule_params)
    result = construct_applicability_mask(usage, (rule,))

    assert result.sum() == expected_match_count, f"{description} failed"


# Multiple Rules (OR Logic) Tests


def test_multiple_rules_or_logic_basic(hourly_day_usage):
    """Two time windows combined with OR logic (morning 8-12 OR evening 16-20).

    Expected: Union of both time windows should match (8 hours total)
    """
    morning_rule = ApplicabilityRule(
        period_start_local=time(8, 0), period_end_local=time(12, 0)
    )
    evening_rule = ApplicabilityRule(
        period_start_local=time(16, 0), period_end_local=time(20, 0)
    )

    result = construct_applicability_mask(hourly_day_usage, (morning_rule, evening_rule))

    # Should match hours 8-11 (4 hours) + 16-19 (4 hours) = 8 hours
    assert result.sum() == 8

    # Verify specific hours are matched
    for hour in [8, 9, 10, 11, 16, 17, 18, 19]:
        assert result.iloc[hour], f"Hour {hour} should be matched"

    # Verify non-matched hours
    for hour in [0, 1, 2, 3, 4, 5, 6, 7, 12, 13, 14, 15, 20, 21, 22, 23]:
        assert not result.iloc[hour], f"Hour {hour} should not be matched"


def test_multiple_rules_different_day_types(full_week_usage):
    """Weekday peak hours (9-17) OR all weekend hours.

    Expected: Weekdays 9am-5pm + all weekend hours
    """
    weekday_peak_rule = ApplicabilityRule(
        day_types=frozenset([DayType.WEEKDAY]),
        period_start_local=time(9, 0),
        period_end_local=time(17, 0),
    )
    weekend_rule = ApplicabilityRule(
        day_types=frozenset([DayType.WEEKEND]),
    )

    result = construct_applicability_mask(full_week_usage, (weekday_peak_rule, weekend_rule))

    # Weekdays (5 days) * 8 peak hours + Weekend (2 days) * 24 hours
    expected_count = 5 * 8 + 2 * 24
    assert result.sum() == expected_count

    # Verify weekday intervals match only during peak hours
    weekday_data = full_week_usage[full_week_usage["is_weekday"]]
    for idx in weekday_data.index:
        hour = weekday_data.loc[idx, "interval_start"].hour
        if 9 <= hour < 17:
            assert result.loc[idx], f"Weekday hour {hour} should match"
        else:
            assert not result.loc[idx], f"Weekday hour {hour} should not match"

    # Verify all weekend intervals match
    weekend_data = full_week_usage[full_week_usage["is_weekend"]]
    for idx in weekend_data.index:
        assert result.loc[idx], "All weekend hours should match"


def test_multiple_rules_seasonal(usage_df_factory):
    """Summer afternoons (Jun-Aug, 12-18) OR winter mornings (Dec-Feb, 6-10).

    Tests OR logic with date range constraints.
    """
    # Create data spanning full year
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=365 * 24, freq="1h")

    summer_afternoon_rule = ApplicabilityRule(
        start_date=date(2000, 6, 1),
        end_date=date(2000, 8, 31),
        period_start_local=time(12, 0),
        period_end_local=time(18, 0),
    )
    winter_morning_rule = ApplicabilityRule(
        start_date=date(2000, 12, 1),
        end_date=date(2000, 12, 31),  # Just December for simpler counting
        period_start_local=time(6, 0),
        period_end_local=time(10, 0),
    )

    result = construct_applicability_mask(usage, (summer_afternoon_rule, winter_morning_rule))

    # Verify summer afternoon intervals match
    summer_data = usage[
        (usage["interval_start"].dt.month >= 6) & (usage["interval_start"].dt.month <= 8)
    ]
    for idx in summer_data.index:
        hour = summer_data.loc[idx, "interval_start"].hour
        if 12 <= hour < 18:
            assert result.loc[idx], f"Summer hour {hour} should match"

    # Verify December morning intervals match
    december_data = usage[usage["interval_start"].dt.month == 12]
    for idx in december_data.index:
        hour = december_data.loc[idx, "interval_start"].hour
        if 6 <= hour < 10:
            assert result.loc[idx], f"December hour {hour} should match"


def test_multiple_rules_with_overlap(hourly_day_usage):
    """Two overlapping time rules should not double-count (OR is idempotent).

    Rule 1: 8-14, Rule 2: 12-18
    Overlap: 12-14
    Expected: Union = 8-18 (10 hours), not 12 hours
    """
    rule1 = ApplicabilityRule(period_start_local=time(8, 0), period_end_local=time(14, 0))
    rule2 = ApplicabilityRule(period_start_local=time(12, 0), period_end_local=time(18, 0))

    result = construct_applicability_mask(hourly_day_usage, (rule1, rule2))

    # Should be union: hours 8-17 = 10 hours (not 6+6=12)
    assert result.sum() == 10

    # Verify each hour in the union
    for hour in range(8, 18):
        assert result.iloc[hour], f"Hour {hour} should be in union"


def test_empty_rules_tuple_matches_all(hourly_day_usage):
    """Empty rules tuple means charge applies everywhere (no restrictions).

    This is the default behavior - no applicability rules = always applicable.
    """
    result = construct_applicability_mask(hourly_day_usage, ())

    # All intervals should match
    assert result.all()
    assert result.sum() == 24
