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
        # Date validations - invalid case
        (
            None,
            None,
            date(2024, 12, 31),
            date(2024, 1, 1),
            True,
            "start_date must be earlier",
        ),
        # Date validations - valid case (equal dates allowed)
        (None, None, date(2024, 6, 15), date(2024, 6, 15), False, None),
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
    result = construct_applicability_mask(full_week_usage, weekday_rule)
    assert result.sum() == 5 * 24  # five weekdays in a week

    weekend_rule = ApplicabilityRule(day_types=frozenset([DayType.WEEKEND]))
    result = construct_applicability_mask(full_week_usage, weekend_rule)
    assert result.sum() == 2 * 24  # two weekends in a week


def test_mixed_week_with_holiday(full_week_usage):
    """Test dataset with mixed day types including holiday."""
    # Mark Friday (day 4) as a holiday
    full_week_usage.loc[full_week_usage["interval_start"].dt.dayofweek == 4, "is_holiday"] = True

    # Rule for holidays only
    rule = ApplicabilityRule(day_types=frozenset([DayType.HOLIDAY]))
    result = construct_applicability_mask(full_week_usage, rule)

    # Only Friday intervals should match
    expected = full_week_usage["is_holiday"]
    pd.testing.assert_series_equal(result, expected, check_names=False)


# Time Filtering Tests


def test_period_start_local_only(hourly_day_usage):
    """Filter with only period_start_local (no end)."""
    rule = ApplicabilityRule(period_start_local=time(12, 0))

    result = construct_applicability_mask(hourly_day_usage, rule)

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

    result = construct_applicability_mask(hourly_day_usage, rule)

    # Should match intervals before 12:00 (00:00-11:00)
    expected_hours = list(range(0, 12))

    assert result.sum() == len(expected_hours)
    for i in expected_hours:
        assert result.iloc[i]


def test_period_start_local_and_end(hourly_day_usage):
    """Filter with both start and end times."""
    rule = ApplicabilityRule(period_start_local=time(9, 0), period_end_local=time(17, 0))

    result = construct_applicability_mask(hourly_day_usage, rule)

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
    hourly_day_usage, period_start_local, period_end_local, expected_hours, inclusive_hour, exclusive_hour
):
    """Test time filtering with various boundary conditions (inclusive start, exclusive end)."""
    rule = ApplicabilityRule(period_start_local=period_start_local, period_end_local=period_end_local)
    result = construct_applicability_mask(hourly_day_usage, rule)

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

    result = construct_applicability_mask(hourly_day_usage, rule)

    # All intervals should match
    assert result.all()


# Date Filtering Tests


def test_start_date_only(month_usage):
    """Filter with only start_date (no end)."""
    rule = ApplicabilityRule(start_date=date(2024, 1, 15))

    result = construct_applicability_mask(month_usage, rule)

    # Should match intervals from Jan 15 onwards
    matched_dates = month_usage[result]["interval_start"].dt.date.unique()

    assert all(d >= date(2024, 1, 15) for d in matched_dates)
    # Should include Jan 15 through Jan 31 (17 days)
    assert result.sum() == 17 * 24


def test_end_date_only(month_usage):
    """Filter with only end_date (no start)."""
    rule = ApplicabilityRule(end_date=date(2024, 1, 15))

    result = construct_applicability_mask(month_usage, rule)

    # Should match intervals through Jan 15 (Jan 1-15)
    matched_dates = month_usage[result]["interval_start"].dt.date.unique()

    # Should include Jan 1 through Jan 15 (15 days)
    assert all(d <= date(2024, 1, 15) for d in matched_dates)
    assert result.sum() == 15 * 24


def test_start_and_end_date(month_usage):
    """Filter with both start and end dates."""
    rule = ApplicabilityRule(start_date=date(2024, 1, 10), end_date=date(2024, 1, 20))

    result = construct_applicability_mask(month_usage, rule)

    # Should match Jan 10-20 (11 days)
    matched_dates = month_usage[result]["interval_start"].dt.date.unique()

    assert all(date(2024, 1, 10) <= d <= date(2024, 1, 20) for d in matched_dates)
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
    """Test date filtering boundary conditions (inclusive start, exclusive end)."""
    rule = ApplicabilityRule(start_date=date(2024, 1, 10), end_date=date(2024, 1, 15))
    result = construct_applicability_mask(month_usage, rule)

    test_intervals = month_usage[month_usage["interval_start"].dt.date == test_date]
    for idx in test_intervals.index:
        assert result.loc[idx] == should_match


def test_no_date_constraints(month_usage):
    """Both None means apply to all dates."""
    rule = ApplicabilityRule(start_date=None, end_date=None)

    result = construct_applicability_mask(month_usage, rule)

    # All intervals should match
    assert result.all()


def test_single_day_rule(month_usage):
    """start_date == end_date should match just one day (inclusive end)."""
    rule = ApplicabilityRule(start_date=date(2024, 1, 15), end_date=date(2024, 1, 15))

    result = construct_applicability_mask(month_usage, rule)

    # One day should match (date >= 2024-01-15 AND date <= 2024-01-15)
    # since both start and end dates are inclusive.
    matched_dates = month_usage[result]["interval_start"].dt.date.unique()
    assert all(date(2024, 1, 15) <= d <= date(2024, 1, 15) for d in matched_dates)
    assert result.sum() == 1 * 24


def test_multi_month_date_range(usage_df_factory):
    """Date range spanning multiple months."""
    # Create data spanning Dec 2023 - Feb 2024
    usage = usage_df_factory(start="2023-12-15 00:00:00", periods=60 * 24, freq="1h")

    rule = ApplicabilityRule(start_date=date(2024, 1, 1), end_date=date(2024, 1, 31))

    result = construct_applicability_mask(usage, rule)

    # Should match all of January 2024 only
    matched_dates = usage[result]["interval_start"].dt.date.unique()

    assert all(date(2024, 1, 1) <= d <= date(2024, 1, 31) for d in matched_dates)
    # Should be 31 days in January
    assert result.sum() == 31 * 24


# Combined Filtering Tests


def test_weekday_peak_hours(full_week_usage):
    """Weekdays during peak hours (9am-5pm)."""
    rule = ApplicabilityRule(
        day_types=frozenset([DayType.WEEKDAY]),
        period_start_local=time(9, 0),
        period_end_local=time(17, 0),
    )

    result = construct_applicability_mask(full_week_usage, rule)

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
    """Date range + day type + time."""
    # Create data spanning May-September 2024
    usage = usage_df_factory(start="2024-05-01 00:00:00", periods=150 * 24, freq="1h")

    rule = ApplicabilityRule(
        day_types=frozenset([DayType.WEEKDAY]),
        period_start_local=time(12, 0),
        period_end_local=time(18, 0),
        start_date=date(2024, 6, 1),
        end_date=date(2024, 9, 1),  # FIX TODO
    )

    result = construct_applicability_mask(usage, rule)

    matched_data = usage[result]

    # All matched intervals should be weekdays
    assert matched_data["is_weekday"].all()
    # All matched intervals should be in time range [12, 18)
    matched_hours = matched_data["interval_start"].dt.hour
    assert all((12 <= h < 18) for h in matched_hours)
    # All matched dates should be in June-August
    matched_dates = matched_data["interval_start"].dt.date
    assert all(date(2024, 6, 1) <= d <= date(2024, 9, 1) for d in matched_dates)


def test_all_constraints_none_applies_everywhere(full_week_usage):
    """No constraints = all intervals match."""
    rule = ApplicabilityRule()

    result = construct_applicability_mask(full_week_usage, rule)

    # All intervals should match
    assert result.all()
    assert result.sum() == len(full_week_usage)


def test_restrictive_combined_filters(full_week_usage):
    """Very restrictive combination."""
    # Mark Tuesday as a holiday
    full_week_usage.loc[full_week_usage["interval_start"].dt.dayofweek == 1, "is_holiday"] = True

    rule = ApplicabilityRule(
        day_types=frozenset([DayType.HOLIDAY]),
        period_start_local=time(14, 0),
        period_end_local=time(15, 0),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
    )

    result = construct_applicability_mask(full_week_usage, rule)

    matched_data = full_week_usage[result]

    # Should only match Tuesday Jan 2 at 14:00 (1 interval)
    assert result.sum() == 1
    if result.sum() > 0:
        matched_interval = matched_data.iloc[0]
        assert matched_interval["is_holiday"]
        assert matched_interval["interval_start"].hour == 14
        assert matched_interval["interval_start"].date() == date(2024, 1, 2)


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
        # Leap day test (2024 is leap year)
        (
            "2024-02-28 00:00:00",
            72,
            "1h",
            {"start_date": date(2024, 2, 28), "end_date": date(2024, 3, 1)},
            24 * 3,
            "Leap day Feb 29 handled correctly",
        ),
    ],
)
def test_edge_cases(
    usage_df_factory, start, periods, freq, rule_params, expected_match_count, description
):
    """Test edge cases: DST transitions and leap days."""
    usage = usage_df_factory(start=start, periods=periods, freq=freq, tz="US/Pacific")
    rule = ApplicabilityRule(**rule_params)
    result = construct_applicability_mask(usage, rule)

    assert result.sum() == expected_match_count, f"{description} failed"
