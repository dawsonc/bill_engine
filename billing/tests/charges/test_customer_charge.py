"""
Unit tests for customer charge logic.
"""

from decimal import Decimal

import pytest

from billing.core.charges.customer import apply_customer_charge
from billing.core.types import CustomerCharge


@pytest.fixture
def customer_charge():
    return CustomerCharge(
        name="Test customer charge",
        amount_usd_per_month=Decimal(100.0),
    )


def test_single_day_usage(hourly_day_usage, customer_charge):
    """All intervals in the day should receive an even share of the customer charge."""
    customer_charge_series = apply_customer_charge(hourly_day_usage, customer_charge)
    expected_value = customer_charge.amount_usd_per_month / len(hourly_day_usage)
    assert (customer_charge_series == expected_value).all()  # Decimal comparison is OK


def test_multiple_month_usage(usage_df_factory, customer_charge):
    """Customer charge should be spread evenly across all hours in each month"""
    # Create data spanning Dec 2023 - Feb 2024
    usage = usage_df_factory(start="2023-12-15 00:00:00", periods=70 * 24, freq="1h")
    customer_charge_series = apply_customer_charge(usage, customer_charge)

    for month in usage["interval_start"].dt.month.unique():
        intervals_in_month = usage[usage["interval_start"].dt.month == month]
        charges_in_month = customer_charge_series[usage["interval_start"].dt.month == month]
        expected_value = customer_charge.amount_usd_per_month / len(intervals_in_month)
        assert (charges_in_month == expected_value).all()
