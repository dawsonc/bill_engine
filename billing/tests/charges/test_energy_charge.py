"""
Unit tests for energy charge logic.
"""

from datetime import date, time
from decimal import Decimal

import pytest

from billing.core.charges.energy import apply_energy_charge
from billing.core.types import ApplicabilityRule, DayType, EnergyCharge


@pytest.fixture
def energy_charge():
    """Basic energy charge: $0.25/kWh, no applicability restrictions."""
    return EnergyCharge(
        name="Test Energy Charge",
        rate_usd_per_kwh=Decimal("0.25"),
    )


# Basic Functionality Tests


def test_single_interval_usage(usage_df_factory, energy_charge):
    """
    Verify rate × usage calculation for a single interval.

    Expected: charge = rate × kwh for the single interval
    """
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=1, freq="1h")
    result = apply_energy_charge(usage, energy_charge)

    # Default kwh is 10.5 from usage_df_factory
    expected_charge = energy_charge.rate_usd_per_kwh * Decimal("10.5")
    assert result[0] == expected_charge


def test_multiple_intervals_uniform_rate(hourly_day_usage, energy_charge):
    """
    All intervals get charged at the same rate.

    Expected: All 24 hourly intervals have same charge (rate × kwh)
    """
    result = apply_energy_charge(hourly_day_usage, energy_charge)

    # All intervals have same kwh value
    expected_charge = energy_charge.rate_usd_per_kwh * Decimal(str(hourly_day_usage["kwh"].iloc[0]))
    assert (result == expected_charge).all()
    assert len(result) == 24


def test_zero_usage_intervals(usage_df_factory, energy_charge):
    """
    Intervals with 0 kWh get $0 charge.

    Expected: charge = $0 when kwh = 0
    """
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=5, freq="1h", kwh=Decimal("0"))
    result = apply_energy_charge(usage, energy_charge)

    assert (result == Decimal("0")).all()


# Applicability Rule Tests


def test_no_applicability_rules(hourly_day_usage):
    """
    No applicability rules means charge applies to all intervals.

    Expected: All intervals charged when no applicability restrictions
    """
    # Create charge with no applicability rules (applies everywhere)
    charge = EnergyCharge(
        name="All Hours Energy",
        rate_usd_per_kwh=Decimal("0.30"),
        applicability_rules=(),  # Empty tuple: applies everywhere
    )

    result = apply_energy_charge(hourly_day_usage, charge)

    # All intervals should have non-zero charges
    assert (result > 0).all()
    assert len(result) == 24


def test_time_of_day_filtering(hourly_day_usage):
    """
    Energy charge only during peak hours (12:00-18:00).

    Expected: Only 12:00-17:00 intervals are charged, rest are $0
    """
    charge = EnergyCharge(
        name="Peak Hours Energy",
        rate_usd_per_kwh=Decimal("0.35"),
        applicability_rules=(
            ApplicabilityRule(
                period_start_local=time(12, 0), period_end_local=time(18, 0)
            ),
        ),
    )

    result = apply_energy_charge(hourly_day_usage, charge)

    # Hours 12-17 (indices 12-17) should be charged
    for hour in range(12, 18):
        assert result.iloc[hour] > 0, f"Hour {hour} should be charged"

    # Hours 0-11 and 18-23 should be $0
    for hour in list(range(0, 12)) + list(range(18, 24)):
        assert result.iloc[hour] == 0, f"Hour {hour} should not be charged"


def test_weekday_only(full_week_usage):
    """
    Energy charge applies only on weekdays.

    Expected: Weekday intervals charged, weekend intervals = $0
    """
    charge = EnergyCharge(
        name="Weekday Energy",
        rate_usd_per_kwh=Decimal("0.20"),
        applicability_rules=(ApplicabilityRule(day_types=frozenset([DayType.WEEKDAY])),),
    )

    result = apply_energy_charge(full_week_usage, charge)

    # Check weekday intervals are charged
    weekday_intervals = full_week_usage[full_week_usage["is_weekday"]]
    for idx in weekday_intervals.index:
        assert result.loc[idx] > 0, f"Weekday interval {idx} should be charged"

    # Check weekend intervals are not charged
    weekend_intervals = full_week_usage[full_week_usage["is_weekend"]]
    for idx in weekend_intervals.index:
        assert result.loc[idx] == 0, f"Weekend interval {idx} should not be charged"


def test_date_range_filtering(month_usage):
    """
    Energy charge only in specific date range.

    Expected: Only Jan 15-20 charged
    """
    charge = EnergyCharge(
        name="Limited Period Energy",
        rate_usd_per_kwh=Decimal("0.28"),
        applicability_rules=(
            ApplicabilityRule(start_date=date(2024, 1, 15), end_date=date(2024, 1, 20)),
        ),
    )

    result = apply_energy_charge(month_usage, charge)

    # Extract dates from usage
    dates = month_usage["interval_start"].dt.date

    # Check intervals within date range are charged
    in_range = (dates >= date(2024, 1, 15)) & (dates <= date(2024, 1, 20))
    for idx in month_usage[in_range].index:
        assert result.loc[idx] > 0, f"Interval on {dates.loc[idx]} should be charged"

    # Check intervals outside date range are not charged
    out_of_range = ~in_range
    for idx in month_usage[out_of_range].index:
        assert result.loc[idx] == 0, f"Interval on {dates.loc[idx]} should not be charged"


def test_combined_applicability_rules(usage_df_factory):
    """
    Multiple constraints at once: Weekdays, 9am-5pm, June-August only.

    Expected: Only intervals matching ALL constraints are charged
    """
    # Create summer usage (June 1 - Aug 31, 2024)
    usage = usage_df_factory(
        start="2024-06-01 00:00:00",
        periods=92 * 24,
        freq="1h",  # ~3 months
    )

    charge = EnergyCharge(
        name="Summer Weekday Business Hours",
        rate_usd_per_kwh=Decimal("0.40"),
        applicability_rules=(
            ApplicabilityRule(
                period_start_local=time(9, 0),
                period_end_local=time(17, 0),
                start_date=date(2024, 6, 1),
                end_date=date(2024, 8, 31),
                day_types=frozenset([DayType.WEEKDAY]),
            ),
        ),
    )

    result = apply_energy_charge(usage, charge)

    # Extract time and date components
    times = usage["interval_start"].dt.time
    dates = usage["interval_start"].dt.date
    is_weekday = usage["is_weekday"]

    # Check that charged intervals meet ALL criteria
    charged_intervals = result > 0
    for idx in usage[charged_intervals].index:
        assert times.loc[idx] >= time(9, 0) and times.loc[idx] < time(17, 0), (
            "Charged interval not in time range"
        )
        assert dates.loc[idx] >= date(2024, 6, 1) and dates.loc[idx] <= date(2024, 8, 31), (
            "Charged interval not in date range"
        )
        assert is_weekday.loc[idx], "Charged interval not a weekday"

    # Verify at least some intervals are charged
    assert charged_intervals.sum() > 0, "No intervals were charged"


# Edge Cases


def test_zero_rate(hourly_day_usage):
    """
    Rate = $0/kWh should produce $0 charges everywhere.

    Expected: All charges = $0
    """
    charge = EnergyCharge(name="Free Energy", rate_usd_per_kwh=Decimal("0.00"))

    result = apply_energy_charge(hourly_day_usage, charge)

    assert (result == 0).all()


def test_no_matching_intervals(hourly_day_usage):
    """
    Applicability rule matches 0 intervals (all $0).

    Expected: All charges = $0 when no intervals match rule
    """
    # January data, but rule requires December
    charge = EnergyCharge(
        name="December Only Energy",
        rate_usd_per_kwh=Decimal("0.25"),
        applicability_rules=(
            ApplicabilityRule(start_date=date(2023, 12, 1), end_date=date(2023, 12, 31)),
        ),
    )

    result = apply_energy_charge(hourly_day_usage, charge)

    assert (result == 0).all()


def test_varying_usage_values(usage_df_factory):
    """
    Different kWh per interval, verify each charged correctly.

    Expected: Each interval charged proportional to its usage
    """
    # Create usage with varying kwh values
    kwh_values = [5, 10, 15, 20, 25]
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=5, freq="1h", kwh=kwh_values)

    charge = EnergyCharge(name="Variable Usage Energy", rate_usd_per_kwh=Decimal("0.30"))

    result = apply_energy_charge(usage, charge)

    # Verify each charge matches rate × kwh for that interval
    for i, kwh in enumerate(kwh_values):
        expected = charge.rate_usd_per_kwh * Decimal(str(kwh))
        assert result.iloc[i] == expected, f"Interval {i} charge mismatch"


# Multiple Applicability Rules Tests


def test_multiple_time_windows(hourly_day_usage):
    """
    Energy charge applies during morning peak (8-12) OR evening peak (16-20).

    Expected: Both time windows are charged, others are $0
    """
    charge = EnergyCharge(
        name="Dual Peak Energy",
        rate_usd_per_kwh=Decimal("0.35"),
        applicability_rules=(
            ApplicabilityRule(period_start_local=time(8, 0), period_end_local=time(12, 0)),
            ApplicabilityRule(period_start_local=time(16, 0), period_end_local=time(20, 0)),
        ),
    )

    result = apply_energy_charge(hourly_day_usage, charge)

    # Morning peak (8-11) and evening peak (16-19) should be charged
    peak_hours = [8, 9, 10, 11, 16, 17, 18, 19]
    for hour in peak_hours:
        assert result.iloc[hour] > 0, f"Hour {hour} should be charged"

    # Off-peak hours should be $0
    off_peak_hours = [h for h in range(24) if h not in peak_hours]
    for hour in off_peak_hours:
        assert result.iloc[hour] == 0, f"Hour {hour} should not be charged"

    # Verify total charged intervals
    assert (result > 0).sum() == 8  # 4 morning + 4 evening


def test_weekday_peak_or_weekend_all(full_week_usage):
    """
    Energy charge applies during weekday peak hours (9-17) OR all weekend hours.

    Expected: Weekdays charged only 9am-5pm, weekends charged all hours
    """
    charge = EnergyCharge(
        name="Weekday Peak or Weekend",
        rate_usd_per_kwh=Decimal("0.28"),
        applicability_rules=(
            ApplicabilityRule(
                day_types=frozenset([DayType.WEEKDAY]),
                period_start_local=time(9, 0),
                period_end_local=time(17, 0),
            ),
            ApplicabilityRule(day_types=frozenset([DayType.WEEKEND])),
        ),
    )

    result = apply_energy_charge(full_week_usage, charge)

    # Verify weekday peak hours are charged
    weekday_data = full_week_usage[full_week_usage["is_weekday"]]
    for idx in weekday_data.index:
        hour = weekday_data.loc[idx, "interval_start"].hour
        if 9 <= hour < 17:
            assert result.loc[idx] > 0, f"Weekday hour {hour} should be charged"
        else:
            assert result.loc[idx] == 0, f"Weekday hour {hour} should not be charged"

    # Verify all weekend hours are charged
    weekend_data = full_week_usage[full_week_usage["is_weekend"]]
    for idx in weekend_data.index:
        assert result.loc[idx] > 0, "All weekend hours should be charged"

    # Total: 5 weekdays * 8 peak hours + 2 weekend days * 24 hours = 88
    assert (result > 0).sum() == 5 * 8 + 2 * 24


def test_summer_or_winter_peak(usage_df_factory):
    """
    Energy charge applies during summer afternoons (Jun-Aug, 14-20) OR winter mornings (Dec, 6-10).

    Tests multiple rules with both date and time constraints.
    """
    # Create data spanning June through December
    usage = usage_df_factory(start="2024-06-01 00:00:00", periods=214 * 24, freq="1h")

    charge = EnergyCharge(
        name="Seasonal Peak Energy",
        rate_usd_per_kwh=Decimal("0.40"),
        applicability_rules=(
            ApplicabilityRule(
                start_date=date(2000, 6, 1),
                end_date=date(2000, 8, 31),
                period_start_local=time(14, 0),
                period_end_local=time(20, 0),
            ),
            ApplicabilityRule(
                start_date=date(2000, 12, 1),
                end_date=date(2000, 12, 31),
                period_start_local=time(6, 0),
                period_end_local=time(10, 0),
            ),
        ),
    )

    result = apply_energy_charge(usage, charge)

    # Verify summer afternoon intervals are charged
    summer_data = usage[
        (usage["interval_start"].dt.month >= 6) & (usage["interval_start"].dt.month <= 8)
    ]
    summer_charged = 0
    for idx in summer_data.index:
        hour = summer_data.loc[idx, "interval_start"].hour
        if 14 <= hour < 20:
            assert result.loc[idx] > 0, f"Summer hour {hour} should be charged"
            summer_charged += 1
        else:
            assert result.loc[idx] == 0, f"Summer hour {hour} should not be charged"

    # Verify December morning intervals are charged
    december_data = usage[usage["interval_start"].dt.month == 12]
    december_charged = 0
    for idx in december_data.index:
        hour = december_data.loc[idx, "interval_start"].hour
        if 6 <= hour < 10:
            assert result.loc[idx] > 0, f"December hour {hour} should be charged"
            december_charged += 1
        else:
            assert result.loc[idx] == 0, f"December hour {hour} should not be charged"

    # Verify some intervals were charged in both seasons
    assert summer_charged > 0, "Some summer intervals should be charged"
    assert december_charged > 0, "Some December intervals should be charged"
