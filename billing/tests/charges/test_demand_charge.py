"""
Unit tests for demand charge logic.
"""

from datetime import date, time
from decimal import Decimal

import pytest

from billing.core.charges.demand import apply_demand_charge
from billing.core.types import ApplicabilityRule, DayType, DemandCharge, PeakType


@pytest.fixture
def monthly_demand_charge():
    """Monthly demand charge: $15/kW, no applicability restrictions."""
    return DemandCharge(
        name="Test Monthly Demand",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
    )


@pytest.fixture
def daily_demand_charge():
    """Daily demand charge: $5/kW, no applicability restrictions."""
    return DemandCharge(
        name="Test Daily Demand",
        rate_usd_per_kw=Decimal("5.00"),
        type=PeakType.DAILY,
    )


@pytest.fixture
def varying_demand_usage(usage_df_factory):
    """Create usage with varying kW values to test peak identification."""
    kw_values = [
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        45,
        40,
        35,  # Morning peak at hour 8 (50 kW)
        30,
        25,
        20,
        25,
        30,
        35,
        40,
        35,
        30,
        25,
        20,
        15,  # Afternoon (40 kW at hour 18)
    ]
    usage = usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=24,  # 24 hours
        freq="1h",
        kwh=Decimal("10.0"),
        kw=kw_values,
    )
    return usage


# Basic Peak Identification Tests


def test_single_peak_interval_monthly(varying_demand_usage, monthly_demand_charge):
    """
    One clear peak in a month.

    Expected: Only the peak interval (hour 8 with 50 kW) gets the full charge
    """
    result = apply_demand_charge(varying_demand_usage, monthly_demand_charge)

    # Peak is at hour 8 (index 8) with 50 kW
    peak_kw = Decimal("50")
    expected_charge = monthly_demand_charge.rate_usd_per_kw * peak_kw

    # Hour 8 should get the full charge
    assert result.iloc[8] == expected_charge

    # All other hours should be $0
    for i in range(24):
        if i != 8:
            assert result.iloc[i] == 0, f"Hour {i} should not be charged"


def test_single_peak_interval_daily(varying_demand_usage, daily_demand_charge):
    """
    One clear peak per day (daily peak type).

    Expected: Peak interval per day gets charged
    """
    result = apply_demand_charge(varying_demand_usage, daily_demand_charge)

    # Peak is at hour 8 with 50 kW (same as monthly since it's one day)
    peak_kw = Decimal("50")
    expected_charge = daily_demand_charge.rate_usd_per_kw * peak_kw

    # Hour 8 should get the full charge
    assert result.iloc[8] == expected_charge

    # All other hours should be $0
    for i in range(24):
        if i != 8:
            assert result.iloc[i] == 0, f"Hour {i} should not be charged"


# Multiple Peak Intervals Tests


def test_two_intervals_share_peak(usage_df_factory, monthly_demand_charge):
    """
    Two intervals both reach max demand.

    Expected: Cost split 50/50 between the two peak intervals
    """
    # Create usage where hours 8 and 17 both have 45 kW (tied for peak)
    kw_values = [
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,  # Hour 8: 45 kW
        40,
        35,
        30,
        25,
        20,
        15,
        10,
        15,
        20,
        45,  # Hour 17: 45 kW
        40,
        35,
        30,
        25,
        20,
        15,
    ]
    usage = usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=24,
        freq="1h",
        kw=kw_values,
    )

    result = apply_demand_charge(usage, monthly_demand_charge)

    # Total charge: $15 × 45 = $675
    # Split between 2 intervals = $337.50 each
    peak_kw = Decimal("45")
    total_charge = monthly_demand_charge.rate_usd_per_kw * peak_kw
    expected_per_interval = total_charge / 2

    # Hours 7 and 17 should each get half the charge (index shifted by 1 because 0-indexed)
    assert result.iloc[7] == expected_per_interval
    assert result.iloc[17] == expected_per_interval

    # All other hours should be $0
    for i in range(24):
        if i not in [7, 17]:
            assert result.iloc[i] == 0, f"Hour {i} should not be charged"


def test_all_intervals_same_demand(hourly_day_usage, monthly_demand_charge):
    """
    All intervals have identical kW.

    Expected: Cost split evenly across all 24 intervals
    """
    result = apply_demand_charge(hourly_day_usage, monthly_demand_charge)

    # All intervals are peaks, so charge is split evenly
    # Default kw from hourly_day_usage is 42
    peak_kw = Decimal("42")
    total_charge = monthly_demand_charge.rate_usd_per_kw * peak_kw
    expected_per_interval = total_charge / 24

    # All intervals should have the same charge
    assert (result == expected_per_interval).all()


# Peak Type Differences Tests


def test_monthly_vs_daily_peak_type(usage_df_factory):
    """
    Compare monthly vs daily for multi-day data.

    Expected:
    - Monthly: Peak identified once for whole week, only Wed peak interval charged
    - Daily: Peak identified per day, one interval per day charged
    """
    # Create 7 days of usage with different peaks each day
    # Day 1 (Mon): peak 40, Day 2 (Tue): peak 42, Day 3 (Wed): peak 50 (global max)
    # Day 4 (Thu): peak 45, Day 5 (Fri): peak 43, Day 6 (Sat): peak 41, Day 7 (Sun): peak 39
    kw_values = []
    daily_peaks = [40, 42, 50, 45, 43, 41, 39]

    for day_peak in daily_peaks:
        # Create 24 hours for each day, with peak at hour 12
        day_values = [day_peak - 10 if h != 12 else day_peak for h in range(24)]
        kw_values.extend(day_values)

    usage = usage_df_factory(
        start="2024-01-01 00:00:00",  # Monday
        periods=7 * 24,  # 7 days
        freq="1h",
        kw=kw_values,
    )

    # Test monthly peak type
    monthly_charge = DemandCharge(
        name="Monthly Peak",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
    )
    monthly_result = apply_demand_charge(usage, monthly_charge)

    # Only Wednesday (day 3) at hour 12 should be charged (global peak of 50)
    wed_peak_index = 2 * 24 + 12  # Day 3, hour 12 (0-indexed)
    assert monthly_result.iloc[wed_peak_index] > 0, "Wednesday peak should be charged"
    assert monthly_result.iloc[wed_peak_index] == Decimal("15.00") * 50

    # All other intervals should be $0
    non_peak_count = (monthly_result == 0).sum()
    assert non_peak_count == (7 * 24 - 1), "Only one interval should be charged"

    # Test daily peak type
    daily_charge = DemandCharge(
        name="Daily Peak",
        rate_usd_per_kw=Decimal("5.00"),
        type=PeakType.DAILY,
    )
    daily_result = apply_demand_charge(usage, daily_charge)

    # One interval per day should be charged (7 total)
    charged_count = (daily_result > 0).sum()
    assert charged_count == 7, "Exactly 7 intervals should be charged (one per day)"

    # Verify each day's peak hour (hour 12) is charged
    for day in range(7):
        day_peak_index = day * 24 + 12
        expected_charge = Decimal("5.00") * daily_peaks[day]
        assert daily_result.iloc[day_peak_index] == expected_charge, (
            f"Day {day + 1} peak should be charged"
        )


def test_daily_peak_type_multi_day(usage_df_factory):
    """
    Daily peaks across multiple days.

    Expected: One peak interval per day gets charged
    """
    # Create 3 days with varying demand patterns
    kw_values = (
        [30 + i for i in range(24)]  # Day 1: peak at hour 23 (53 kW)
        + [50 - i for i in range(24)]  # Day 2: peak at hour 0 (50 kW)
        + [20 + (i % 12) for i in range(24)]  # Day 3: peak at hours 11 and 23 (31 kW)
    )

    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=3 * 24, freq="1h", kw=kw_values)

    daily_charge = DemandCharge(
        name="Daily Peak",
        rate_usd_per_kw=Decimal("10.00"),
        type=PeakType.DAILY,
    )

    result = apply_demand_charge(usage, daily_charge)

    # Day 1: peak at hour 23 (index 23)
    assert result.iloc[23] == Decimal("10.00") * 53

    # Day 2: peak at hour 0 (index 24)
    assert result.iloc[24] == Decimal("10.00") * 50

    # Day 3: peaks at hours 11 and 23 (indices 48+11=59 and 48+23=71), split charge
    day3_charge = Decimal("10.00") * 31
    assert result.iloc[59] == day3_charge / 2
    assert result.iloc[71] == day3_charge / 2

    # Count non-zero entries: should be 4 (1 + 1 + 2)
    assert (result > 0).sum() == 4


# Multi-Month Scenarios


def test_monthly_peak_across_months(usage_df_factory):
    """
    Monthly peak type with 2+ months of data.

    Expected: Peak found separately per month
    """
    # Create 60 days (Jan-Feb 2024)
    # January peak: day 15, hour 12 → 60 kW
    # February peak: day 45, hour 8 → 55 kW
    kw_values = []
    for day in range(60):
        for hour in range(24):
            if day == 14 and hour == 12:  # Jan 15, 12pm
                kw_values.append(60)
            elif day == 44 and hour == 8:  # Feb 14, 8am
                kw_values.append(55)
            else:
                kw_values.append(35)

    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=60 * 24, freq="1h", kw=kw_values)

    monthly_charge = DemandCharge(
        name="Monthly Peak",
        rate_usd_per_kw=Decimal("12.00"),
        type=PeakType.MONTHLY,
    )

    result = apply_demand_charge(usage, monthly_charge)

    # January peak: day 15, hour 12 (index 14*24 + 12 = 348)
    jan_peak_index = 14 * 24 + 12
    assert result.iloc[jan_peak_index] == Decimal("12.00") * 60

    # February peak: day 45, hour 8 (index 44*24 + 8 = 1064)
    feb_peak_index = 44 * 24 + 8
    assert result.iloc[feb_peak_index] == Decimal("12.00") * 55

    # Only these 2 intervals should be charged
    assert (result > 0).sum() == 2


# Applicability Rules with Demand


def test_peak_hours_only(varying_demand_usage):
    """
    Demand charge only during peak hours (2pm-6pm).

    Expected: Peak is found ONLY among 2pm-6pm intervals, not the global max
    """
    # Global max is at hour 8 (50 kW), but that's outside peak hours
    # During 2pm-6pm (hours 14-17), max is 35 kW at hour 17
    charge = DemandCharge(
        name="Peak Hours Only",
        rate_usd_per_kw=Decimal("20.00"),
        type=PeakType.MONTHLY,
        applicability=ApplicabilityRule(
            period_start_local=time(14, 0), period_end_local=time(18, 0)
        ),
    )

    result = apply_demand_charge(varying_demand_usage, charge)

    # Peak within 2pm-6pm is at hour 17 (35 kW)
    expected_charge = Decimal("20.00") * 35
    assert result.iloc[17] == expected_charge

    # Hour 8 (global max) should NOT be charged
    assert result.iloc[8] == 0

    # Only hour 17 should be charged
    assert (result > 0).sum() == 1


def test_weekday_demand_only(usage_df_factory):
    """
    Demand charge on weekdays only.

    Expected: Peak found only among weekday intervals, weekend = $0
    """
    # Create a full week with Saturday having the global max
    kw_values = []
    for day in range(7):
        for hour in range(24):
            if day == 5 and hour == 12:  # Saturday, hour 12: 60 kW (global max)
                kw_values.append(60)
            elif day == 2 and hour == 15:  # Wednesday, hour 15: 55 kW (weekday max)
                kw_values.append(55)
            else:
                kw_values.append(40)

    usage = usage_df_factory(
        start="2024-01-01 00:00:00",  # Monday
        periods=7 * 24,
        freq="1h",
        kw=kw_values,
    )

    charge = DemandCharge(
        name="Weekday Demand",
        rate_usd_per_kw=Decimal("18.00"),
        type=PeakType.MONTHLY,
        applicability=ApplicabilityRule(day_types=frozenset([DayType.WEEKDAY])),
    )

    result = apply_demand_charge(usage, charge)

    # Wednesday peak (day 2, hour 15) should be charged
    wed_peak_index = 2 * 24 + 15
    expected_charge = Decimal("18.00") * 55
    assert result.iloc[wed_peak_index] == expected_charge

    # Saturday peak (day 5, hour 12) should NOT be charged
    sat_peak_index = 5 * 24 + 12
    assert result.iloc[sat_peak_index] == 0

    # Only Wednesday peak should be charged
    assert (result > 0).sum() == 1


def test_no_applicable_intervals(hourly_day_usage):
    """
    Applicability rule matches nothing.

    Expected: All charges = $0
    """
    # January data, but rule requires December
    charge = DemandCharge(
        name="December Only",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
        applicability=ApplicabilityRule(start_date=date(2023, 12, 1), end_date=date(2023, 12, 31)),
    )

    result = apply_demand_charge(hourly_day_usage, charge)

    assert (result == 0).all()


# Edge Cases


def test_zero_demand_all_intervals(usage_df_factory, monthly_demand_charge):
    """
    All kW = 0.

    Expected: All charges = $0 (no division by zero errors)
    """
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=24, freq="1h", kw=Decimal("0"))

    result = apply_demand_charge(usage, monthly_demand_charge)

    assert (result == 0).all()


def test_zero_rate(varying_demand_usage):
    """
    Rate = $0/kW.

    Expected: All charges = $0
    """
    charge = DemandCharge(
        name="Free Demand", rate_usd_per_kw=Decimal("0.00"), type=PeakType.MONTHLY
    )

    result = apply_demand_charge(varying_demand_usage, charge)

    assert (result == 0).all()


def test_single_interval_dataset(usage_df_factory, monthly_demand_charge):
    """
    Only 1 interval total.

    Expected: That interval is the peak, gets full charge
    """
    usage = usage_df_factory(start="2024-01-01 12:00:00", periods=1, freq="1h", kw=Decimal("48"))

    result = apply_demand_charge(usage, monthly_demand_charge)

    expected_charge = monthly_demand_charge.rate_usd_per_kw * Decimal("48")
    assert result.iloc[0] == expected_charge
    assert len(result) == 1
