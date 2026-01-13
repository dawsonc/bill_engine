"""
Unit tests for billing calculator functions.

Tests apply_charges() and calculate_monthly_bills() functions.
"""

from datetime import date
from decimal import Decimal

import pytest

from billing.core.calculator import apply_charges, calculate_monthly_bills
from billing.core.types import CustomerCharge, DemandCharge, EnergyCharge, PeakType, Tariff

# Fixtures for test charges


@pytest.fixture
def simple_energy_charge():
    """Basic energy charge: $0.10/kWh."""
    return EnergyCharge(
        name="Test Energy",
        rate_usd_per_kwh=Decimal("0.10"),
    )


@pytest.fixture
def simple_demand_charge():
    """Basic monthly demand charge: $15/kW."""
    return DemandCharge(
        name="Test Demand",
        rate_usd_per_kw=Decimal("15.00"),
        type=PeakType.MONTHLY,
    )


@pytest.fixture
def simple_customer_charge():
    """Basic customer charge: $25/month."""
    return CustomerCharge(
        name="Test Customer",
        amount_usd=Decimal("25.00"),
    )


# Tests for apply_charges()


def test_apply_charges_empty_charges(hourly_day_usage):
    """
    Empty Tariff returns usage DataFrame unchanged.

    Expected: No charge columns added, only original usage columns
    """
    empty_charges = Tariff(
        energy_charges=tuple(),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    result = apply_charges(hourly_day_usage, empty_charges)

    # Should have only the original usage columns
    assert len(result.columns) == hourly_day_usage.shape[1]
    assert set(result.columns) == set(hourly_day_usage.columns)


def test_apply_charges_single_energy_charge(hourly_day_usage, simple_energy_charge):
    """
    Single energy charge adds one column with correct values.

    Expected: Original 7 columns + 1 charge column with energy charge values
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    result = apply_charges(hourly_day_usage, charges)

    # Should have 8 columns (7 usage + 1 charge)
    assert len(result.columns) == hourly_day_usage.shape[1] + 1

    # Find the charge column
    charge_columns = [col for col in result.columns if col not in hourly_day_usage.columns]
    assert len(charge_columns) == 1

    # Verify charge column is labeled with charge_id UUID
    charge_col = charge_columns[0]
    assert charge_col == str(simple_energy_charge.charge_id.value)

    # Verify values are correct (rate × kwh for each interval)
    expected_charge = simple_energy_charge.rate_usd_per_kwh * Decimal(
        str(hourly_day_usage["kwh"].iloc[0])
    )
    assert (result[charge_col] == expected_charge).all()


def test_apply_charges_single_demand_charge(hourly_day_usage, simple_demand_charge):
    """
    Single demand charge adds one column.

    Expected: Demand charge applied correctly with peak identification
    """
    charges = Tariff(
        energy_charges=tuple(),
        demand_charges=(simple_demand_charge,),
        customer_charges=tuple(),
    )

    result = apply_charges(hourly_day_usage, charges)

    # Should have 8 columns (7 usage + 1 charge)
    assert len(result.columns) == hourly_day_usage.shape[1] + 1

    # Find charge column
    charge_columns = [col for col in result.columns if col not in hourly_day_usage.columns]
    assert len(charge_columns) == 1

    charge_col = charge_columns[0]
    assert charge_col == str(simple_demand_charge.charge_id.value)

    # Demand charge should sum to rate × peak_kw
    peak_kw = hourly_day_usage["kw"].max()
    expected_total = simple_demand_charge.rate_usd_per_kw * Decimal(str(peak_kw))
    actual_total = result[charge_col].sum()
    assert actual_total == expected_total


def test_apply_charges_single_customer_charge(hourly_day_usage, simple_customer_charge):
    """
    Single customer charge adds one column.

    Expected: Customer charge distributed across intervals
    """
    charges = Tariff(
        energy_charges=tuple(),
        demand_charges=tuple(),
        customer_charges=(simple_customer_charge,),
    )

    result = apply_charges(hourly_day_usage, charges)

    # Should have 8 columns
    assert len(result.columns) == hourly_day_usage.shape[1] + 1

    # Find charge column
    charge_columns = [col for col in result.columns if col not in hourly_day_usage.columns]
    assert len(charge_columns) == 1

    charge_col = charge_columns[0]
    assert charge_col == str(simple_customer_charge.charge_id.value)

    # Customer charge should sum to monthly amount (prorated for usage duration)
    assert result[charge_col].sum() > 0


def test_apply_charges_multiple_charges(
    hourly_day_usage, simple_energy_charge, simple_demand_charge, simple_customer_charge
):
    """
    Multiple charges of different types all applied.

    Expected: Each charge gets its own column, all independent
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=(simple_demand_charge,),
        customer_charges=(simple_customer_charge,),
    )

    result = apply_charges(hourly_day_usage, charges)

    # Should have 10 columns (7 usage + 3 charges)
    assert len(result.columns) == hourly_day_usage.shape[1] + 3

    # Find charge columns
    charge_columns = [col for col in result.columns if col not in hourly_day_usage.columns]
    assert len(charge_columns) == 3

    # Verify all charge_ids are present
    expected_ids = {
        str(simple_energy_charge.charge_id.value),
        str(simple_demand_charge.charge_id.value),
        str(simple_customer_charge.charge_id.value),
    }
    assert set(charge_columns) == expected_ids


def test_apply_charges_preserves_usage_columns(hourly_day_usage, simple_energy_charge):
    """
    Original usage columns unchanged after applying charges.

    Expected: Usage data identical before and after
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    result = apply_charges(hourly_day_usage, charges)

    # Check that original columns are preserved
    for col in hourly_day_usage.columns:
        assert (result[col] == hourly_day_usage[col]).all()


# Tests for calculate_monthly_bills()


def test_calculate_monthly_bills_single_month(hourly_day_usage, simple_energy_charge):
    """
    Single month of usage creates one BillingMonthResult.

    Expected: One result with correct line items and total
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    results, _ = calculate_monthly_bills(hourly_day_usage, charges)

    # Should have exactly 1 monthly result
    assert len(results) == 1

    result = results[0]
    assert result.period_start == date(2024, 1, 1)
    assert result.period_end == date(2024, 1, 31)

    # Should have 1 energy line item, 0 demand, 0 customer
    assert len(result.energy_line_items) == 1
    assert len(result.demand_line_items) == 0
    assert len(result.customer_line_items) == 0

    # Energy line item should have correct description and charge_id
    energy_item = result.energy_line_items[0]
    assert energy_item.description == "Test Energy"
    assert energy_item.charge_id == simple_energy_charge.charge_id
    assert energy_item.amount_usd > 0

    # Total should match sum of line items
    assert result.total_usd == energy_item.amount_usd


def test_calculate_monthly_bills_multi_month(usage_df_factory, simple_energy_charge):
    """
    Multi-month usage creates separate results per month.

    Expected: One result per month, sorted chronologically
    """
    # Create 3 months of usage (Jan-Mar 2024)
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=90 * 24, freq="1h")

    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    results, _ = calculate_monthly_bills(usage, charges)

    # Should have 3 monthly results
    assert len(results) == 3

    # Results should be sorted by period_start
    assert results[0].period_start == date(2024, 1, 1)
    assert results[1].period_start == date(2024, 2, 1)
    assert results[2].period_start == date(2024, 3, 1)

    # Each month should have charges
    for result in results:
        assert len(result.energy_line_items) == 1
        assert result.total_usd > 0


def test_calculate_monthly_bills_line_item_grouping(
    month_usage, simple_energy_charge, simple_demand_charge, simple_customer_charge
):
    """
    Line items correctly separated by type.

    Expected: Energy, demand, customer items in separate tuples
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=(simple_demand_charge,),
        customer_charges=(simple_customer_charge,),
    )

    results, _ = calculate_monthly_bills(month_usage, charges)

    assert len(results) == 1
    result = results[0]

    # Should have 1 of each type
    assert len(result.energy_line_items) == 1
    assert len(result.demand_line_items) == 1
    assert len(result.customer_line_items) == 1

    # Verify descriptions match
    assert result.energy_line_items[0].description == "Test Energy"
    assert result.demand_line_items[0].description == "Test Demand"
    assert result.customer_line_items[0].description == "Test Customer"


def test_calculate_monthly_bills_total_calculation(
    month_usage, simple_energy_charge, simple_demand_charge, simple_customer_charge
):
    """
    Total matches sum of all line items.

    Expected: total_usd = sum of energy + demand + customer
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=(simple_demand_charge,),
        customer_charges=(simple_customer_charge,),
    )

    results, _ = calculate_monthly_bills(month_usage, charges)

    result = results[0]

    # Calculate expected total
    expected_total = (
        result.energy_line_items[0].amount_usd
        + result.demand_line_items[0].amount_usd
        + result.customer_line_items[0].amount_usd
    )

    assert result.total_usd == expected_total


def test_calculate_monthly_bills_month_boundary_splitting(usage_df_factory, simple_energy_charge):
    """
    Usage spanning month boundary splits correctly.

    Expected: Jan 15 - Feb 15 creates 2 bills, one for each month
    """
    # Create usage from Jan 15 to Feb 15
    usage = usage_df_factory(start="2024-01-15 00:00:00", periods=32 * 24, freq="1h")

    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    results, _ = calculate_monthly_bills(usage, charges)

    # Should have 2 monthly results
    assert len(results) == 2

    # First result is January
    assert results[0].period_start == date(2024, 1, 1)
    assert results[0].period_end == date(2024, 1, 31)

    # Second result is February
    assert results[1].period_start == date(2024, 2, 1)
    assert results[1].period_end == date(2024, 2, 29)  # 2024 is a leap year

    # Both months should have charges
    assert results[0].total_usd > 0
    assert results[1].total_usd > 0


def test_calculate_monthly_bills_returns_billing_df(hourly_day_usage, simple_energy_charge):
    """
    Second return value matches apply_charges() output.

    Expected: billing_df has usage columns + charge columns
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    _, billing_df = calculate_monthly_bills(hourly_day_usage, charges)

    # Should have 8 columns (7 usage + 1 charge)
    assert len(billing_df.columns) == 8

    # Should match apply_charges output
    expected_df = apply_charges(hourly_day_usage, charges)
    assert set(billing_df.columns) == set(expected_df.columns)

    # Verify charge column exists
    charge_col = str(simple_energy_charge.charge_id.value)
    assert charge_col in billing_df.columns


def test_calculate_monthly_bills_empty_charges(hourly_day_usage):
    """
    Empty Tariff creates valid result with no line items.

    Expected: MonthlyBillResult with empty line item tuples and $0 total
    """
    empty_charges = Tariff(
        energy_charges=tuple(),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    results, _ = calculate_monthly_bills(hourly_day_usage, empty_charges)

    # Should have 1 monthly result
    assert len(results) == 1

    result = results[0]
    assert len(result.energy_line_items) == 0
    assert len(result.demand_line_items) == 0
    assert len(result.customer_line_items) == 0
    assert result.total_usd == 0


def test_calculate_monthly_bills_decimal_precision(month_usage, simple_energy_charge):
    """
    All monetary amounts are Decimal type.

    Expected: amount_usd and total_usd are Decimal, not float
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    results, billing_df = calculate_monthly_bills(month_usage, charges)

    result = results[0]

    # Check line item amount is Decimal
    assert isinstance(result.energy_line_items[0].amount_usd, Decimal)

    # Check total is Decimal
    assert isinstance(result.total_usd, Decimal)


# Tests for custom billing_months parameter


def test_calculate_bills_billing_months_single_calendar_month(
    usage_df_factory, simple_energy_charge
):
    """
    Custom billing month within a single calendar month.

    Expected: One BillingMonthResult with one MonthlyBillResult in monthly_breakdowns
    """
    from billing.core.types import BillingMonthResult

    # Create January 2024 usage
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=31 * 24, freq="1h")

    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    # Billing month is Jan 10-20 (within single calendar month)
    billing_months = [(date(2024, 1, 10), date(2024, 1, 20))]
    results, _ = calculate_monthly_bills(usage, charges, billing_months)

    assert len(results) == 1
    assert isinstance(results[0], BillingMonthResult)

    result = results[0]
    assert result.period_start == date(2024, 1, 10)
    assert result.period_end == date(2024, 1, 20)

    # Should have exactly 1 monthly breakdown (single calendar month)
    assert len(result.monthly_breakdowns) == 1
    assert result.monthly_breakdowns[0].month_start == date(2024, 1, 10)
    assert result.monthly_breakdowns[0].month_end == date(2024, 1, 20)

    # Should have energy line items
    assert len(result.energy_line_items) == 1
    assert result.total_usd > 0


def test_calculate_bills_billing_months_spans_two_months(
    usage_df_factory, simple_customer_charge
):
    """
    Custom billing month spanning two calendar months with weighted customer charge.

    Expected: Customer charge is weighted by days in each calendar month
    """
    from billing.core.types import BillingMonthResult

    # Create Jan-Feb 2024 usage (60 days)
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=60 * 24, freq="1h")

    charges = Tariff(
        energy_charges=tuple(),
        demand_charges=tuple(),
        customer_charges=(simple_customer_charge,),  # $25/month
    )

    # Billing month is Jan 15 - Feb 14 (31 days: 17 in Jan, 14 in Feb)
    billing_months = [(date(2024, 1, 15), date(2024, 2, 14))]
    results, _ = calculate_monthly_bills(usage, charges, billing_months)

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, BillingMonthResult)

    # Should have 2 monthly breakdowns
    assert len(result.monthly_breakdowns) == 2

    # First breakdown is January portion
    jan_breakdown = result.monthly_breakdowns[0]
    assert jan_breakdown.month_start == date(2024, 1, 15)
    assert jan_breakdown.month_end == date(2024, 1, 31)

    # Second breakdown is February portion
    feb_breakdown = result.monthly_breakdowns[1]
    assert feb_breakdown.month_start == date(2024, 2, 1)
    assert feb_breakdown.month_end == date(2024, 2, 14)

    # The aggregated customer charge should be weighted
    # Jan portion: 17 days, Feb portion: 14 days, Total: 31 days
    # Expected weighted total: ($25 * 17/31) + ($25 * 14/31) = $25.00
    assert len(result.customer_line_items) == 1
    # The weighted sum should equal the monthly amount since we're spanning exactly one "month" worth of days
    expected_total = Decimal("25.00")
    assert result.customer_line_items[0].amount_usd == expected_total


def test_calculate_bills_billing_months_energy_not_weighted(
    usage_df_factory, simple_energy_charge
):
    """
    Energy charges are summed across calendar months, not weighted.

    Expected: Energy total is simple sum of all energy charges in the billing month
    """
    # Create Jan-Feb 2024 usage
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=60 * 24, freq="1h")

    charges = Tariff(
        energy_charges=(simple_energy_charge,),  # $0.10/kWh
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    # Billing month spans Jan 15 - Feb 14
    billing_months = [(date(2024, 1, 15), date(2024, 2, 14))]
    results, _ = calculate_monthly_bills(usage, charges, billing_months)

    result = results[0]

    # Calculate expected energy: sum of all breakdowns
    expected_energy = sum(
        item.amount_usd
        for breakdown in result.monthly_breakdowns
        for item in breakdown.energy_line_items
    )

    # Aggregated energy should be simple sum (not weighted)
    assert len(result.energy_line_items) == 1
    assert result.energy_line_items[0].amount_usd == expected_energy


def test_calculate_bills_billing_months_empty_list(hourly_day_usage, simple_energy_charge):
    """
    Empty billing_months list returns empty results list.

    Expected: Empty list of BillingMonthResult
    """
    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    billing_months: list[tuple[date, date]] = []
    results, _ = calculate_monthly_bills(hourly_day_usage, charges, billing_months)

    assert len(results) == 0


def test_calculate_bills_billing_months_no_data(usage_df_factory, simple_energy_charge):
    """
    Billing month with no usage data returns zeros.

    Expected: BillingMonthResult with empty line items and $0 total
    """
    from billing.core.types import BillingMonthResult

    # Create January 2024 usage
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=31 * 24, freq="1h")

    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    # Billing month is in February (no usage data)
    billing_months = [(date(2024, 2, 1), date(2024, 2, 28))]
    results, _ = calculate_monthly_bills(usage, charges, billing_months)

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, BillingMonthResult)
    assert result.period_start == date(2024, 2, 1)
    assert result.period_end == date(2024, 2, 28)
    assert result.monthly_breakdowns == ()
    assert result.energy_line_items == ()
    assert result.total_usd == Decimal("0")


def test_calculate_bills_without_billing_months(hourly_day_usage, simple_energy_charge):
    """
    Without billing_months argument, uses calendar months from usage data.

    Expected: List of BillingMonthResult objects aligned to calendar months
    """
    from billing.core.types import BillingMonthResult

    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=tuple(),
    )

    # Call without billing_months - derives calendar months from data
    results, _ = calculate_monthly_bills(hourly_day_usage, charges)

    assert len(results) == 1
    assert isinstance(results[0], BillingMonthResult)
    assert results[0].period_start == date(2024, 1, 1)
    assert results[0].period_end == date(2024, 1, 31)


def test_calculate_bills_billing_months_multiple_periods(
    usage_df_factory, simple_energy_charge, simple_customer_charge
):
    """
    Multiple billing months in one call.

    Expected: One BillingMonthResult per billing month
    """
    from billing.core.types import BillingMonthResult

    # Create 3 months of usage
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=90 * 24, freq="1h")

    charges = Tariff(
        energy_charges=(simple_energy_charge,),
        demand_charges=tuple(),
        customer_charges=(simple_customer_charge,),
    )

    # Two billing months
    billing_months = [
        (date(2024, 1, 15), date(2024, 2, 14)),  # Spans Jan-Feb
        (date(2024, 2, 15), date(2024, 3, 14)),  # Spans Feb-Mar
    ]
    results, _ = calculate_monthly_bills(usage, charges, billing_months)

    assert len(results) == 2
    assert all(isinstance(r, BillingMonthResult) for r in results)

    assert results[0].period_start == date(2024, 1, 15)
    assert results[0].period_end == date(2024, 2, 14)

    assert results[1].period_start == date(2024, 2, 15)
    assert results[1].period_end == date(2024, 3, 14)


def test_calculate_bills_billing_months_demand_weighted(
    usage_df_factory, simple_demand_charge
):
    """
    Demand charges are weighted by days in each calendar month.

    Expected: Demand charge is weighted sum across calendar months
    """
    from billing.core.types import BillingMonthResult

    # Create Jan-Feb 2024 usage
    usage = usage_df_factory(start="2024-01-01 00:00:00", periods=60 * 24, freq="1h")

    charges = Tariff(
        energy_charges=tuple(),
        demand_charges=(simple_demand_charge,),  # $15/kW
        customer_charges=tuple(),
    )

    # Billing month spans Jan 15 - Feb 14 (31 days: 17 in Jan, 14 in Feb)
    billing_months = [(date(2024, 1, 15), date(2024, 2, 14))]
    results, _ = calculate_monthly_bills(usage, charges, billing_months)

    assert len(results) == 1
    result = results[0]
    assert isinstance(result, BillingMonthResult)

    # Should have demand line items
    assert len(result.demand_line_items) == 1

    # Calculate expected weighted demand
    jan_weight = Decimal("17") / Decimal("31")
    feb_weight = Decimal("14") / Decimal("31")

    jan_demand = result.monthly_breakdowns[0].demand_line_items[0].amount_usd
    feb_demand = result.monthly_breakdowns[1].demand_line_items[0].amount_usd

    expected_weighted = (jan_demand * jan_weight) + (feb_demand * feb_weight)

    assert result.demand_line_items[0].amount_usd == expected_weighted
