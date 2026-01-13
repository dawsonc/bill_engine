"""
Unit tests for customer charge logic.
"""

from datetime import date
from decimal import Decimal

import pytest

from billing.core.charges.customer import apply_customer_charge
from billing.core.types import CustomerCharge, CustomerChargeType


@pytest.fixture
def monthly_customer_charge():
    return CustomerCharge(
        name="Test monthly customer charge",
        amount_usd=Decimal(100.0),
        type=CustomerChargeType.MONTHLY,
    )


@pytest.fixture
def daily_customer_charge():
    return CustomerCharge(
        name="Test daily customer charge",
        amount_usd=Decimal(5.0),
        type=CustomerChargeType.DAILY,
    )


def test_single_day_usage_monthly(hourly_day_usage, monthly_customer_charge):
    """All intervals in the day should receive an even share of the monthly customer charge."""
    customer_charge_series = apply_customer_charge(hourly_day_usage, monthly_customer_charge)
    expected_value = monthly_customer_charge.amount_usd / len(hourly_day_usage)
    assert (customer_charge_series == expected_value).all()


def test_multiple_month_usage_monthly(usage_df_factory, monthly_customer_charge):
    """Monthly customer charge should be spread evenly across all hours in each month."""
    # Create data spanning Dec 2023 - Feb 2024
    usage = usage_df_factory(start="2023-12-15 00:00:00", periods=70 * 24, freq="1h")
    customer_charge_series = apply_customer_charge(usage, monthly_customer_charge)

    for month in usage["interval_start"].dt.month.unique():
        intervals_in_month = usage[usage["interval_start"].dt.month == month]
        charges_in_month = customer_charge_series[usage["interval_start"].dt.month == month]
        expected_value = monthly_customer_charge.amount_usd / len(intervals_in_month)
        assert (charges_in_month == expected_value).all()


def test_single_day_usage_daily(hourly_day_usage, daily_customer_charge):
    """All intervals in a single day should receive an even share of the daily charge."""
    customer_charge_series = apply_customer_charge(hourly_day_usage, daily_customer_charge)
    # 24 hourly intervals in a day, each gets $5/24
    expected_value = daily_customer_charge.amount_usd / 24
    assert (customer_charge_series == expected_value).all()
    # Total should equal the daily amount (use approximate comparison for Decimal precision)
    assert abs(customer_charge_series.sum() - daily_customer_charge.amount_usd) < Decimal("0.0001")


def test_multiple_day_usage_daily(usage_df_factory, daily_customer_charge):
    """Daily customer charge should be spread evenly across intervals in each day."""
    # Create data spanning 3 days
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=3 * 24, freq="1h")
    customer_charge_series = apply_customer_charge(usage, daily_customer_charge)

    for day in usage["interval_start"].dt.date.unique():
        intervals_in_day = usage[usage["interval_start"].dt.date == day]
        charges_in_day = customer_charge_series[usage["interval_start"].dt.date == day]
        expected_value = daily_customer_charge.amount_usd / len(intervals_in_day)
        assert (charges_in_day == expected_value).all()

    # Total should equal daily amount * 3 days (use approximate comparison for Decimal precision)
    expected_total = daily_customer_charge.amount_usd * 3
    assert abs(customer_charge_series.sum() - expected_total) < Decimal("0.0001")


def test_monthly_vs_daily_different_results(usage_df_factory):
    """Monthly and daily charges should produce different results for multi-day usage."""
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=31 * 24, freq="1h")

    monthly_charge = CustomerCharge(
        name="Monthly",
        amount_usd=Decimal("100.00"),
        type=CustomerChargeType.MONTHLY,
    )
    daily_charge = CustomerCharge(
        name="Daily",
        amount_usd=Decimal("100.00"),
        type=CustomerChargeType.DAILY,
    )

    monthly_series = apply_customer_charge(usage, monthly_charge)
    daily_series = apply_customer_charge(usage.copy(), daily_charge)

    # Monthly charge totals to $100 (one month) - use approximate comparison for Decimal precision
    assert abs(monthly_series.sum() - Decimal("100.00")) < Decimal("0.0001")

    # Daily charge totals to $100 * 31 = $3100 (31 days) - use approximate comparison
    assert abs(daily_series.sum() - Decimal("3100.00")) < Decimal("0.0001")


# --- Non-calendar billing period tests ---


def test_monthly_charge_non_calendar_single_period(usage_df_factory, monthly_customer_charge):
    """Monthly charge should spread evenly across a non-calendar billing period."""
    # Billing period from Jan 15 to Feb 14 (non-calendar month)
    billing_periods = [(date(2024, 1, 15), date(2024, 2, 14))]
    usage = usage_df_factory(
        start="2024-01-15 00:00:00",
        periods=31 * 24,  # 31 days of hourly data
        freq="1h",
        billing_periods=billing_periods,
    )

    customer_charge_series = apply_customer_charge(usage, monthly_customer_charge)

    # All intervals should have the same charge (evenly distributed)
    expected_value = monthly_customer_charge.amount_usd / len(usage)
    assert (customer_charge_series == expected_value).all()

    # Total should equal the monthly amount
    assert abs(customer_charge_series.sum() - monthly_customer_charge.amount_usd) < Decimal("0.0001")


def test_monthly_charge_non_calendar_multiple_periods(usage_df_factory, monthly_customer_charge):
    """Monthly charge should be applied separately to each non-calendar billing period."""
    # Two non-calendar billing periods
    billing_periods = [
        (date(2024, 1, 15), date(2024, 2, 14)),
        (date(2024, 2, 15), date(2024, 3, 14)),
    ]
    usage = usage_df_factory(
        start="2024-01-15 00:00:00",
        periods=59 * 24,  # ~59 days of hourly data to cover both periods
        freq="1h",
        billing_periods=billing_periods,
    )

    customer_charge_series = apply_customer_charge(usage, monthly_customer_charge)

    # Check each billing period separately
    for period_start, period_end in billing_periods:
        period_mask = (usage["interval_start"].dt.date >= period_start) & (
            usage["interval_start"].dt.date <= period_end
        )
        intervals_in_period = usage[period_mask]
        charges_in_period = customer_charge_series[period_mask]

        expected_value = monthly_customer_charge.amount_usd / len(intervals_in_period)
        assert (charges_in_period == expected_value).all()

    # Total should equal monthly amount * 2 periods
    expected_total = monthly_customer_charge.amount_usd * 2
    assert abs(customer_charge_series.sum() - expected_total) < Decimal("0.0001")


def test_daily_charge_non_calendar_billing_period(usage_df_factory, daily_customer_charge):
    """Daily charge should still apply per-day regardless of non-calendar billing periods."""
    # Non-calendar billing period spanning mid-month
    billing_periods = [(date(2024, 1, 15), date(2024, 1, 19))]
    usage = usage_df_factory(
        start="2024-01-15 00:00:00",
        periods=5 * 24,  # 5 days
        freq="1h",
        billing_periods=billing_periods,
    )

    customer_charge_series = apply_customer_charge(usage, daily_customer_charge)

    # Each day should have charge spread evenly across its intervals
    for day in usage["interval_start"].dt.date.unique():
        intervals_in_day = usage[usage["interval_start"].dt.date == day]
        charges_in_day = customer_charge_series[usage["interval_start"].dt.date == day]
        expected_value = daily_customer_charge.amount_usd / len(intervals_in_day)
        assert (charges_in_day == expected_value).all()

    # Total should equal daily amount * 5 days
    expected_total = daily_customer_charge.amount_usd * 5
    assert abs(customer_charge_series.sum() - expected_total) < Decimal("0.0001")


def test_monthly_charge_unequal_billing_periods(usage_df_factory, monthly_customer_charge):
    """Monthly charge should handle billing periods of different lengths."""
    # First period: 20 days, Second period: 35 days
    billing_periods = [
        (date(2024, 1, 10), date(2024, 1, 29)),  # 20 days
        (date(2024, 1, 30), date(2024, 3, 4)),   # ~35 days
    ]
    usage = usage_df_factory(
        start="2024-01-10 00:00:00",
        periods=55 * 24,  # Enough to cover both periods
        freq="1h",
        billing_periods=billing_periods,
    )

    customer_charge_series = apply_customer_charge(usage, monthly_customer_charge)

    # Each billing period should have the full monthly charge spread across it
    for period_start, period_end in billing_periods:
        period_mask = (usage["interval_start"].dt.date >= period_start) & (
            usage["interval_start"].dt.date <= period_end
        )
        charges_in_period = customer_charge_series[period_mask]

        # Total for this period should equal the monthly amount
        assert abs(charges_in_period.sum() - monthly_customer_charge.amount_usd) < Decimal("0.0001")
