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
        applicability_rules=(
            ApplicabilityRule(
                period_start_local=time(14, 0), period_end_local=time(18, 0)
            ),
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
        applicability_rules=(ApplicabilityRule(day_types=frozenset([DayType.WEEKDAY])),),
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
        applicability_rules=(
            ApplicabilityRule(start_date=date(2023, 12, 1), end_date=date(2023, 12, 31)),
        ),
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


# --- Non-Calendar Billing Period Tests ---


def test_monthly_peak_non_calendar_single_period(usage_df_factory, monthly_demand_charge):
    """Monthly peak should be identified within a non-calendar billing period."""
    # Non-calendar billing period: Jan 15 - Feb 14
    billing_periods = [(date(2024, 1, 15), date(2024, 2, 14))]

    # Create usage with peak at Jan 20 (50 kW)
    kw_values = [35] * (31 * 24)  # Base demand
    peak_index = 5 * 24 + 12  # Jan 20, hour 12 (5 days after Jan 15)
    kw_values[peak_index] = 50

    usage = usage_df_factory(
        start="2024-01-15 00:00:00",
        periods=31 * 24,
        freq="1h",
        kw=kw_values,
        billing_periods=billing_periods,
    )

    result = apply_demand_charge(usage, monthly_demand_charge)

    # Peak interval should get the full charge
    expected_charge = monthly_demand_charge.rate_usd_per_kw * Decimal("50")
    assert result.iloc[peak_index] == expected_charge

    # Only one interval should be charged
    assert (result > 0).sum() == 1


def test_monthly_peak_non_calendar_multiple_periods(usage_df_factory, monthly_demand_charge):
    """Separate peaks should be identified for each non-calendar billing period."""
    # Two non-calendar billing periods
    billing_periods = [
        (date(2024, 1, 15), date(2024, 2, 14)),
        (date(2024, 2, 15), date(2024, 3, 14)),
    ]

    # Create usage spanning both periods with different peaks
    kw_values = [35] * (59 * 24)  # ~59 days of base demand

    # Period 1 peak: Jan 20 (day 5), hour 12 -> 50 kW
    period1_peak_index = 5 * 24 + 12
    kw_values[period1_peak_index] = 50

    # Period 2 peak: Feb 25 (day 41 from start), hour 8 -> 45 kW
    period2_peak_index = 41 * 24 + 8
    kw_values[period2_peak_index] = 45

    usage = usage_df_factory(
        start="2024-01-15 00:00:00",
        periods=59 * 24,
        freq="1h",
        kw=kw_values,
        billing_periods=billing_periods,
    )

    result = apply_demand_charge(usage, monthly_demand_charge)

    # Period 1 peak should be charged
    expected_charge_1 = monthly_demand_charge.rate_usd_per_kw * Decimal("50")
    assert result.iloc[period1_peak_index] == expected_charge_1

    # Period 2 peak should be charged
    expected_charge_2 = monthly_demand_charge.rate_usd_per_kw * Decimal("45")
    assert result.iloc[period2_peak_index] == expected_charge_2

    # Exactly 2 intervals should be charged (one per billing period)
    assert (result > 0).sum() == 2


def test_daily_peak_non_calendar_billing_period(usage_df_factory, daily_demand_charge):
    """Daily peaks should work correctly regardless of non-calendar billing periods."""
    # Non-calendar billing period
    billing_periods = [(date(2024, 1, 15), date(2024, 1, 19))]

    # 5 days with different daily peaks
    daily_peaks = [40, 45, 50, 42, 38]
    kw_values = []
    for day_peak in daily_peaks:
        # Peak at hour 12 each day
        day_values = [day_peak - 10 if h != 12 else day_peak for h in range(24)]
        kw_values.extend(day_values)

    usage = usage_df_factory(
        start="2024-01-15 00:00:00",
        periods=5 * 24,
        freq="1h",
        kw=kw_values,
        billing_periods=billing_periods,
    )

    result = apply_demand_charge(usage, daily_demand_charge)

    # Each day should have one peak charged at hour 12
    for day in range(5):
        peak_index = day * 24 + 12
        expected_charge = daily_demand_charge.rate_usd_per_kw * daily_peaks[day]
        assert result.iloc[peak_index] == expected_charge

    # Exactly 5 intervals should be charged (one per day)
    assert (result > 0).sum() == 5


# --- Applicability Date Scaling Tests (TDD - Will Fail Until Implemented) ---


def test_applicability_start_date_mid_billing_period_scales_charge(usage_df_factory):
    """Charge should be scaled when applicability start_date falls mid-billing period.

    Billing period: Jan 1 - Jan 31 (31 days)
    Applicability: start_date=Jan 15 (17 applicable days: Jan 15-31)
    Expected: Charge scaled by 17/31
    """
    billing_periods = [(date(2024, 1, 1), date(2024, 1, 31))]

    # Peak at Jan 20 (within applicable range)
    kw_values = [35] * (31 * 24)
    peak_index = 19 * 24 + 12  # Jan 20, hour 12
    kw_values[peak_index] = 50

    usage = usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=31 * 24,
        freq="1h",
        kw=kw_values,
        billing_periods=billing_periods,
    )

    charge = DemandCharge(
        name="Mid-period start",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
        applicability_rules=(
            ApplicabilityRule(start_date=date(2000, 1, 15)),  # Year 2000 for normalization
        ),
    )

    result = apply_demand_charge(usage, charge)

    # Full charge would be $15 * 50 = $750
    # Scaled by 17/31 applicable days
    full_charge = Decimal("15.00") * Decimal("50")
    scaling_factor = Decimal("17") / Decimal("31")
    expected_charge = full_charge * scaling_factor

    assert abs(result.sum() - expected_charge) < Decimal("0.01")


def test_applicability_end_date_mid_billing_period_scales_charge(usage_df_factory):
    """Charge should be scaled when applicability end_date falls mid-billing period.

    Billing period: Jan 1 - Jan 31 (31 days)
    Applicability: end_date=Jan 20 (20 applicable days: Jan 1-20)
    Expected: Charge scaled by 20/31
    """
    billing_periods = [(date(2024, 1, 1), date(2024, 1, 31))]

    # Peak at Jan 10 (within applicable range)
    kw_values = [35] * (31 * 24)
    peak_index = 9 * 24 + 12  # Jan 10, hour 12
    kw_values[peak_index] = 50

    usage = usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=31 * 24,
        freq="1h",
        kw=kw_values,
        billing_periods=billing_periods,
    )

    charge = DemandCharge(
        name="Mid-period end",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
        applicability_rules=(
            ApplicabilityRule(end_date=date(2000, 1, 20)),  # Year 2000 for normalization
        ),
    )

    result = apply_demand_charge(usage, charge)

    # Full charge would be $15 * 50 = $750
    # Scaled by 20/31 applicable days
    full_charge = Decimal("15.00") * Decimal("50")
    scaling_factor = Decimal("20") / Decimal("31")
    expected_charge = full_charge * scaling_factor

    assert abs(result.sum() - expected_charge) < Decimal("0.01")


def test_applicability_both_dates_mid_billing_period_scales_charge(usage_df_factory):
    """Charge should be scaled when both start_date and end_date fall mid-billing period.

    Billing period: Jan 1 - Jan 31 (31 days)
    Applicability: start_date=Jan 10, end_date=Jan 20 (11 applicable days)
    Expected: Charge scaled by 11/31
    """
    billing_periods = [(date(2024, 1, 1), date(2024, 1, 31))]

    # Peak at Jan 15 (within applicable range)
    kw_values = [35] * (31 * 24)
    peak_index = 14 * 24 + 12  # Jan 15, hour 12
    kw_values[peak_index] = 50

    usage = usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=31 * 24,
        freq="1h",
        kw=kw_values,
        billing_periods=billing_periods,
    )

    charge = DemandCharge(
        name="Mid-period both",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
        applicability_rules=(
            ApplicabilityRule(
                start_date=date(2000, 1, 10),
                end_date=date(2000, 1, 20),
            ),
        ),
    )

    result = apply_demand_charge(usage, charge)

    # Full charge would be $15 * 50 = $750
    # Scaled by 11/31 applicable days
    full_charge = Decimal("15.00") * Decimal("50")
    scaling_factor = Decimal("11") / Decimal("31")
    expected_charge = full_charge * scaling_factor

    assert abs(result.sum() - expected_charge) < Decimal("0.01")


def test_applicability_dates_fully_cover_billing_period_no_scaling(usage_df_factory):
    """No scaling when applicability dates fully cover the billing period.

    Billing period: Jan 15 - Feb 14
    Applicability: start_date=Jan 1, end_date=Feb 28 (fully covers billing period)
    Expected: Full charge, no scaling
    """
    billing_periods = [(date(2024, 1, 15), date(2024, 2, 14))]

    # Peak at Jan 25
    kw_values = [35] * (31 * 24)
    peak_index = 10 * 24 + 12  # 10 days after Jan 15, hour 12
    kw_values[peak_index] = 50

    usage = usage_df_factory(
        start="2024-01-15 00:00:00",
        periods=31 * 24,
        freq="1h",
        kw=kw_values,
        billing_periods=billing_periods,
    )

    charge = DemandCharge(
        name="Full coverage",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
        applicability_rules=(
            ApplicabilityRule(
                start_date=date(2000, 1, 1),
                end_date=date(2000, 2, 28),
            ),
        ),
    )

    result = apply_demand_charge(usage, charge)

    # Full charge: $15 * 50 = $750 (no scaling)
    expected_charge = Decimal("15.00") * Decimal("50")

    assert abs(result.sum() - expected_charge) < Decimal("0.01")


# Multiple Applicability Rules Tests


def test_demand_multiple_time_windows(usage_df_factory):
    """
    Demand charge from morning peak (8-12) OR evening peak (16-20).

    Peak should be found across both time windows combined.
    """
    # Create 24 hours with peaks in both windows
    # Morning peak at hour 10: 45 kW
    # Evening peak at hour 18: 50 kW (global max in applicable windows)
    kw_values = [30] * 24
    kw_values[10] = 45  # Morning peak
    kw_values[18] = 50  # Evening peak (higher)
    kw_values[14] = 60  # Global max but outside applicable windows

    usage = usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=24,
        freq="1h",
        kw=kw_values,
    )

    charge = DemandCharge(
        name="Dual Window Demand",
        rate_usd_per_kw=Decimal("20.00"),
        type=PeakType.MONTHLY,
        applicability_rules=(
            ApplicabilityRule(period_start_local=time(8, 0), period_end_local=time(12, 0)),
            ApplicabilityRule(period_start_local=time(16, 0), period_end_local=time(20, 0)),
        ),
    )

    result = apply_demand_charge(usage, charge)

    # Peak within applicable windows is at hour 18 (50 kW)
    expected_charge = Decimal("20.00") * 50
    assert result.iloc[18] == expected_charge

    # Hour 14 (global max) should NOT be charged - outside applicable windows
    assert result.iloc[14] == 0

    # Hour 10 (morning peak) should NOT be charged - not the max across both windows
    assert result.iloc[10] == 0

    # Only one interval should be charged
    assert (result > 0).sum() == 1


def test_demand_weekday_peak_or_weekend(usage_df_factory):
    """
    Demand charge from weekday peak hours (9-17) OR all weekend hours.

    Peak should be found across the union of both rules.
    """
    # Create a week with different peaks:
    # Wednesday (weekday) hour 12: 55 kW
    # Saturday (weekend) hour 20: 60 kW (global max in applicable intervals)
    # Thursday hour 22: 70 kW (outside weekday peak hours, not weekend)
    kw_values = [40] * (7 * 24)

    # Wednesday hour 12 (day 2, hour 12): weekday peak
    wed_peak_index = 2 * 24 + 12
    kw_values[wed_peak_index] = 55

    # Saturday hour 20 (day 5, hour 20): weekend peak (should be the max)
    sat_peak_index = 5 * 24 + 20
    kw_values[sat_peak_index] = 60

    # Thursday hour 22 (day 3, hour 22): outside applicable hours
    thu_off_peak_index = 3 * 24 + 22
    kw_values[thu_off_peak_index] = 70

    usage = usage_df_factory(
        start="2024-01-01 00:00:00",  # Monday
        periods=7 * 24,
        freq="1h",
        kw=kw_values,
    )

    charge = DemandCharge(
        name="Weekday Peak or Weekend Demand",
        rate_usd_per_kw=Decimal("18.00"),
        type=PeakType.MONTHLY,
        applicability_rules=(
            ApplicabilityRule(
                day_types=frozenset([DayType.WEEKDAY]),
                period_start_local=time(9, 0),
                period_end_local=time(17, 0),
            ),
            ApplicabilityRule(day_types=frozenset([DayType.WEEKEND])),
        ),
    )

    result = apply_demand_charge(usage, charge)

    # Peak across applicable intervals is Saturday hour 20 (60 kW)
    expected_charge = Decimal("18.00") * 60
    assert result.iloc[sat_peak_index] == expected_charge

    # Wednesday peak and Thursday off-peak should NOT be charged
    assert result.iloc[wed_peak_index] == 0
    assert result.iloc[thu_off_peak_index] == 0

    # Only one interval should be charged
    assert (result > 0).sum() == 1


def test_demand_seasonal_rules(usage_df_factory):
    """
    Demand charge from summer afternoons (Jun-Aug, 14-18) OR winter mornings (Dec, 6-10).

    Tests multiple rules with date and time constraints for demand charges.
    """
    # Create data for July and December with different peaks
    # July: 31 days, December: 31 days (simplified to just these months)
    # July hour 16: 55 kW (summer afternoon peak)
    # December hour 8: 50 kW (winter morning peak)

    # Create July data
    july_kw = [40] * (31 * 24)
    july_peak_index = 15 * 24 + 16  # July 16, hour 16
    july_kw[july_peak_index] = 55

    usage_july = usage_df_factory(
        start="2024-07-01 00:00:00",
        periods=31 * 24,
        freq="1h",
        kw=july_kw,
    )

    charge = DemandCharge(
        name="Seasonal Demand",
        rate_usd_per_kw=Decimal("25.00"),
        type=PeakType.MONTHLY,
        applicability_rules=(
            ApplicabilityRule(
                start_date=date(2000, 6, 1),
                end_date=date(2000, 8, 31),
                period_start_local=time(14, 0),
                period_end_local=time(18, 0),
            ),
            ApplicabilityRule(
                start_date=date(2000, 12, 1),
                end_date=date(2000, 12, 31),
                period_start_local=time(6, 0),
                period_end_local=time(10, 0),
            ),
        ),
    )

    result = apply_demand_charge(usage_july, charge)

    # July peak should be charged
    expected_charge = Decimal("25.00") * 55
    assert result.iloc[july_peak_index] == expected_charge

    # Only one interval should be charged
    assert (result > 0).sum() == 1


def test_demand_multiple_rules_scaling_uses_max(usage_df_factory):
    """
    When multiple rules have date constraints, scaling should use max (OR logic).

    Two rules with different date ranges that partially cover the billing period.
    The scaling factor should be the maximum of the two rules' coverage.
    """
    billing_periods = [(date(2024, 1, 1), date(2024, 1, 31))]

    # Peak at Jan 15
    kw_values = [35] * (31 * 24)
    peak_index = 14 * 24 + 12  # Jan 15, hour 12
    kw_values[peak_index] = 50

    usage = usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=31 * 24,
        freq="1h",
        kw=kw_values,
        billing_periods=billing_periods,
    )

    # Rule 1: Jan 1-15 (15 days) -> scaling = 15/31
    # Rule 2: Jan 10-25 (16 days) -> scaling = 16/31
    # Max scaling should be 16/31 (OR logic: most permissive wins)
    charge = DemandCharge(
        name="Overlapping Rules",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
        applicability_rules=(
            ApplicabilityRule(start_date=date(2000, 1, 1), end_date=date(2000, 1, 15)),
            ApplicabilityRule(start_date=date(2000, 1, 10), end_date=date(2000, 1, 25)),
        ),
    )

    result = apply_demand_charge(usage, charge)

    # Full charge would be $15 * 50 = $750
    # Scaled by max(15/31, 16/31) = 16/31
    full_charge = Decimal("15.00") * Decimal("50")
    scaling_factor = Decimal("16") / Decimal("31")
    expected_charge = full_charge * scaling_factor

    assert abs(result.sum() - expected_charge) < Decimal("0.01")
