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
