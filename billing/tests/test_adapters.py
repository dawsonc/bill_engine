"""
Unit tests for billing adapters.

Tests conversion from Django ORM models to billing DTOs.
"""

from datetime import date, time
from decimal import Decimal

import pytest

from billing.adapters import (
    build_applicability_rule,
    build_day_types,
    customer_charge_to_dto,
    demand_charge_to_dto,
    energy_charge_to_dto,
    generate_charge_id,
    tariff_to_charge_list,
    tariffs_to_charge_lists,
)
from billing.core.types import DayType, PeakType
from tariffs.models import CustomerCharge, DemandCharge, EnergyCharge, Tariff

# ChargeId Generation Tests


def test_charge_id_deterministic():
    """Same model and PK should produce same ChargeId."""
    charge_id_1 = generate_charge_id("EnergyCharge", 42)
    charge_id_2 = generate_charge_id("EnergyCharge", 42)
    assert charge_id_1 == charge_id_2
    assert charge_id_1.value == charge_id_2.value


def test_charge_id_different_models_different_ids():
    """Different models with same PK should produce different ChargeIds."""
    energy_id = generate_charge_id("EnergyCharge", 1)
    demand_id = generate_charge_id("DemandCharge", 1)
    assert energy_id.value != demand_id.value


def test_charge_id_different_pks_different_ids():
    """Same model with different PKs should produce different ChargeIds."""
    charge_id_1 = generate_charge_id("EnergyCharge", 1)
    charge_id_2 = generate_charge_id("EnergyCharge", 2)
    assert charge_id_1.value != charge_id_2.value


# Day Types Conversion Tests


@pytest.mark.parametrize(
    "weekdays,weekends,holidays,expected",
    [
        (True, False, False, frozenset({DayType.WEEKDAY})),
        (True, True, False, frozenset({DayType.WEEKDAY, DayType.WEEKEND})),
        (False, False, False, frozenset()),
    ],
)
def test_build_day_types(weekdays, weekends, holidays, expected):
    """Test day types conversion for various combinations."""
    result = build_day_types(
        applies_weekdays=weekdays,
        applies_weekends=weekends,
        applies_holidays=holidays,
    )
    assert result == expected


# ApplicabilityRule Construction Tests


def test_full_applicability_rule():
    """Test creating ApplicabilityRule with all fields."""
    rule = build_applicability_rule(
        period_start_time_local=time(8, 0),
        period_end_time_local=time(17, 0),
        applies_start_date=date(2024, 6, 1),
        applies_end_date=date(2024, 8, 31),
        applies_weekdays=True,
        applies_weekends=False,
        applies_holidays=False,
    )

    assert rule.period_start_local == time(8, 0)
    assert rule.period_end_local == time(17, 0)
    assert rule.start_date == date(2024, 6, 1)
    assert rule.end_date == date(2024, 8, 31)
    assert rule.day_types == frozenset({DayType.WEEKDAY})


def test_applicability_rule_with_nulls():
    """Test ApplicabilityRule with None dates (year-round)."""
    rule = build_applicability_rule(
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_start_date=None,
        applies_end_date=None,
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    assert rule.start_date is None
    assert rule.end_date is None
    assert rule.day_types == frozenset({DayType.WEEKDAY, DayType.WEEKEND, DayType.HOLIDAY})


# EnergyCharge Conversion Tests


def test_energy_charge_conversion(tariff):
    """Test converting EnergyCharge model to DTO."""
    charge = EnergyCharge.objects.create(
        tariff=tariff,
        name="Peak Energy",
        rate_usd_per_kwh=Decimal("0.25"),
        period_start_time_local=time(12, 0),
        period_end_time_local=time(18, 0),
        applies_weekdays=True,
        applies_weekends=False,
        applies_holidays=False,
    )

    dto = energy_charge_to_dto(charge)

    assert dto.name == "Peak Energy"
    assert dto.rate_usd_per_kwh == Decimal("0.25")
    assert dto.applicability.period_start_local == time(12, 0)
    assert dto.applicability.period_end_local == time(18, 0)
    assert dto.applicability.day_types == frozenset({DayType.WEEKDAY})


def test_energy_charge_id_stability(tariff):
    """ChargeId should be stable across multiple conversions."""
    charge = EnergyCharge.objects.create(
        tariff=tariff,
        name="Off Peak",
        rate_usd_per_kwh=Decimal("0.10"),
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    dto1 = energy_charge_to_dto(charge)
    dto2 = energy_charge_to_dto(charge)

    assert dto1.charge_id == dto2.charge_id


# DemandCharge Conversion Tests


@pytest.mark.parametrize(
    "peak_type,expected_enum",
    [
        ("monthly", PeakType.MONTHLY),
        ("daily", PeakType.DAILY),
    ],
)
def test_demand_charge_conversion(tariff, peak_type, expected_enum):
    """Test converting DemandCharge to DTO for different peak types."""
    charge = DemandCharge.objects.create(
        tariff=tariff,
        name=f"{peak_type.title()} Demand",
        rate_usd_per_kw=Decimal("15.00"),
        peak_type=peak_type,
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    dto = demand_charge_to_dto(charge)

    assert dto.name == f"{peak_type.title()} Demand"
    assert dto.rate_usd_per_kw == Decimal("15.00")
    assert dto.type == expected_enum


def test_demand_charge_invalid_peak_type_raises_error(tariff):
    """Invalid peak_type should raise ValueError."""
    charge = DemandCharge.objects.create(
        tariff=tariff,
        name="Invalid Demand",
        rate_usd_per_kw=Decimal("10.00"),
        peak_type="invalid",  # Will bypass Django validation in tests
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    # Manually set invalid value to test adapter error handling
    charge.peak_type = "invalid"

    with pytest.raises(ValueError) as exc_info:
        demand_charge_to_dto(charge)

    assert "Invalid peak_type" in str(exc_info.value)


# CustomerCharge Conversion Tests


def test_customer_charge_conversion(tariff):
    """Test converting CustomerCharge model to DTO."""
    charge = CustomerCharge.objects.create(
        tariff=tariff, name="Monthly Service Fee", usd_per_month=Decimal("25.00")
    )

    dto = customer_charge_to_dto(charge)

    assert dto.name == "Monthly Service Fee"
    assert dto.amount_usd_per_month == Decimal("25.00")
    # CustomerCharge has no applicability rule
    assert dto.charge_id is not None


# Full Tariff Conversion Tests


def test_tariff_to_charge_list_counts(utility):
    """Test converting full tariff produces correct charge counts."""
    tariff = Tariff.objects.create(utility=utility, name="Complete Tariff")

    # Create multiple charges of each type
    EnergyCharge.objects.create(
        tariff=tariff,
        name="Off Peak",
        rate_usd_per_kwh=Decimal("0.10"),
        period_start_time_local=time(0, 0),
        period_end_time_local=time(12, 0),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )
    EnergyCharge.objects.create(
        tariff=tariff,
        name="On Peak",
        rate_usd_per_kwh=Decimal("0.20"),
        period_start_time_local=time(12, 0),
        period_end_time_local=time(18, 0),
        applies_weekdays=True,
        applies_weekends=False,
        applies_holidays=False,
    )

    DemandCharge.objects.create(
        tariff=tariff,
        name="Demand",
        rate_usd_per_kw=Decimal("10.00"),
        peak_type="monthly",
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    CustomerCharge.objects.create(tariff=tariff, name="Service Fee", usd_per_month=Decimal("20.00"))

    tariff = Tariff.objects.prefetch_related(
        "energy_charges", "demand_charges", "customer_charges"
    ).get(pk=tariff.pk)

    charge_list = tariff_to_charge_list(tariff)

    assert len(charge_list.energy_charges) == 2
    assert len(charge_list.demand_charges) == 1
    assert len(charge_list.customer_charges) == 1


def test_tariff_to_charge_list_immutability(utility):
    """Test that ChargeList uses tuples (immutable)."""
    tariff = Tariff.objects.create(utility=utility, name="Test Tariff")

    EnergyCharge.objects.create(
        tariff=tariff,
        name="Test Charge",
        rate_usd_per_kwh=Decimal("0.15"),
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    tariff = Tariff.objects.prefetch_related(
        "energy_charges", "demand_charges", "customer_charges"
    ).get(pk=tariff.pk)

    charge_list = tariff_to_charge_list(tariff)

    assert isinstance(charge_list.energy_charges, tuple)
    assert isinstance(charge_list.demand_charges, tuple)
    assert isinstance(charge_list.customer_charges, tuple)


def test_empty_tariff_conversion(utility):
    """Test converting tariff with no charges."""
    empty_tariff = Tariff.objects.create(utility=utility, name="Empty Tariff")

    charge_list = tariff_to_charge_list(empty_tariff)

    assert len(charge_list.energy_charges) == 0
    assert len(charge_list.demand_charges) == 0
    assert len(charge_list.customer_charges) == 0


# Batch Tariff Conversion Tests


def test_batch_conversion(utility):
    """Test batch converting multiple tariffs."""
    tariff1 = Tariff.objects.create(utility=utility, name="Tariff 1")
    EnergyCharge.objects.create(
        tariff=tariff1,
        name="Energy 1",
        rate_usd_per_kwh=Decimal("0.15"),
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    tariff2 = Tariff.objects.create(utility=utility, name="Tariff 2")
    DemandCharge.objects.create(
        tariff=tariff2,
        name="Demand 2",
        rate_usd_per_kw=Decimal("12.00"),
        peak_type="monthly",
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    queryset = Tariff.objects.all()
    charge_lists = tariffs_to_charge_lists(queryset)

    assert len(charge_lists) == 2
    assert tariff1.pk in charge_lists
    assert tariff2.pk in charge_lists

    # Verify contents
    assert len(charge_lists[tariff1.pk].energy_charges) == 1
    assert len(charge_lists[tariff2.pk].demand_charges) == 1


def test_batch_conversion_returns_dict(utility):
    """Test batch conversion returns dictionary keyed by tariff PK."""
    Tariff.objects.create(utility=utility, name="Tariff 1")
    Tariff.objects.create(utility=utility, name="Tariff 2")

    queryset = Tariff.objects.all()
    charge_lists = tariffs_to_charge_lists(queryset)

    assert isinstance(charge_lists, dict)
    for key in charge_lists.keys():
        assert isinstance(key, int)  # PKs are integers
