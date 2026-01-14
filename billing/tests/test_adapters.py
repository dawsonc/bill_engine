"""
Unit tests for billing adapters.

Tests conversion from Django ORM models to billing DTOs.
"""

from datetime import date, time
from decimal import Decimal

import pytest

from billing.adapters import (
    applicability_rule_to_dto,
    build_day_types,
    customer_charge_to_dto,
    demand_charge_to_dto,
    energy_charge_to_dto,
    generate_charge_id,
    tariff_to_dto,
    tariffs_to_dtos,
)
from billing.core.types import DayType, PeakType
from tariffs.models import (
    ApplicabilityRule,
    CustomerCharge,
    DemandCharge,
    EnergyCharge,
    Tariff,
)

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


@pytest.mark.django_db
def test_full_applicability_rule():
    """Test converting ApplicabilityRule model with all fields to DTO."""
    orm_rule = ApplicabilityRule.objects.create(
        name="Summer Peak Hours",
        period_start_time_local=time(8, 0),
        period_end_time_local=time(17, 0),
        applies_start_date=date(2024, 6, 1),
        applies_end_date=date(2024, 8, 31),
        applies_weekdays=True,
        applies_weekends=False,
        applies_holidays=False,
    )

    rule = applicability_rule_to_dto(orm_rule)

    assert rule.period_start_local == time(8, 0)
    assert rule.period_end_local == time(17, 0)
    assert rule.start_date == date(2024, 6, 1)
    assert rule.end_date == date(2024, 8, 31)
    assert rule.day_types == frozenset({DayType.WEEKDAY})


@pytest.mark.django_db
def test_applicability_rule_with_nulls():
    """Test ApplicabilityRule DTO with None dates (year-round)."""
    orm_rule = ApplicabilityRule.objects.create(
        name="Year-Round All Days",
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_start_date=None,
        applies_end_date=None,
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    rule = applicability_rule_to_dto(orm_rule)

    assert rule.start_date is None
    assert rule.end_date is None
    assert rule.day_types == frozenset({DayType.WEEKDAY, DayType.WEEKEND, DayType.HOLIDAY})


# EnergyCharge Conversion Tests


def test_energy_charge_conversion(tariff):
    """Test converting EnergyCharge model to DTO."""
    # Create applicability rule first
    rule = ApplicabilityRule.objects.create(
        name="Peak Hours",
        period_start_time_local=time(12, 0),
        period_end_time_local=time(18, 0),
        applies_weekdays=True,
        applies_weekends=False,
        applies_holidays=False,
    )

    charge = EnergyCharge.objects.create(
        tariff=tariff,
        name="Peak Energy",
        rate_usd_per_kwh=Decimal("0.25"),
    )
    charge.applicability_rules.add(rule)

    dto = energy_charge_to_dto(charge)

    assert dto.name == "Peak Energy"
    assert dto.rate_usd_per_kwh == Decimal("0.25")
    assert len(dto.applicability_rules) == 1
    assert dto.applicability_rules[0].period_start_local == time(12, 0)
    assert dto.applicability_rules[0].period_end_local == time(18, 0)
    assert dto.applicability_rules[0].day_types == frozenset({DayType.WEEKDAY})


def test_energy_charge_with_multiple_rules(tariff):
    """Test converting EnergyCharge with multiple applicability rules."""
    rule1 = ApplicabilityRule.objects.create(
        name="Morning Peak",
        period_start_time_local=time(8, 0),
        period_end_time_local=time(12, 0),
        applies_weekdays=True,
        applies_weekends=False,
        applies_holidays=False,
    )
    rule2 = ApplicabilityRule.objects.create(
        name="Evening Peak",
        period_start_time_local=time(17, 0),
        period_end_time_local=time(21, 0),
        applies_weekdays=True,
        applies_weekends=False,
        applies_holidays=False,
    )

    charge = EnergyCharge.objects.create(
        tariff=tariff,
        name="Peak Energy",
        rate_usd_per_kwh=Decimal("0.30"),
    )
    charge.applicability_rules.add(rule1, rule2)

    dto = energy_charge_to_dto(charge)

    assert dto.name == "Peak Energy"
    assert len(dto.applicability_rules) == 2


def test_energy_charge_with_no_rules(tariff):
    """Test converting EnergyCharge with no applicability rules (applies everywhere)."""
    charge = EnergyCharge.objects.create(
        tariff=tariff,
        name="Base Energy",
        rate_usd_per_kwh=Decimal("0.08"),
    )
    # No rules added

    dto = energy_charge_to_dto(charge)

    assert dto.name == "Base Energy"
    assert len(dto.applicability_rules) == 0


def test_energy_charge_id_stability(tariff):
    """ChargeId should be stable across multiple conversions."""
    rule = ApplicabilityRule.objects.create(
        name="All Hours",
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    charge = EnergyCharge.objects.create(
        tariff=tariff,
        name="Off Peak",
        rate_usd_per_kwh=Decimal("0.10"),
    )
    charge.applicability_rules.add(rule)

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
    rule = ApplicabilityRule.objects.create(
        name="All Hours",
        period_start_time_local=time(0, 0),
        period_end_time_local=time(23, 59),
        applies_weekdays=True,
        applies_weekends=True,
        applies_holidays=True,
    )

    charge = DemandCharge.objects.create(
        tariff=tariff,
        name=f"{peak_type.title()} Demand",
        rate_usd_per_kw=Decimal("15.00"),
        peak_type=peak_type,
    )
    charge.applicability_rules.add(rule)

    dto = demand_charge_to_dto(charge)

    assert dto.name == f"{peak_type.title()} Demand"
    assert dto.rate_usd_per_kw == Decimal("15.00")
    assert dto.type == expected_enum
    assert len(dto.applicability_rules) == 1


def test_demand_charge_invalid_peak_type_raises_error(tariff):
    """Invalid peak_type should raise ValueError."""
    charge = DemandCharge.objects.create(
        tariff=tariff,
        name="Invalid Demand",
        rate_usd_per_kw=Decimal("10.00"),
        peak_type="monthly",  # Valid for creation
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
        tariff=tariff, name="Monthly Service Fee", amount_usd=Decimal("25.00")
    )

    dto = customer_charge_to_dto(charge)

    assert dto.name == "Monthly Service Fee"
    assert dto.amount_usd == Decimal("25.00")
    assert dto.type.value == "monthly"  # Default charge type
    assert dto.charge_id is not None


def test_customer_charge_daily_conversion(tariff):
    """Test converting daily CustomerCharge model to DTO."""
    charge = CustomerCharge.objects.create(
        tariff=tariff,
        name="Daily Service Fee",
        amount_usd=Decimal("1.50"),
        charge_type="daily",
    )

    dto = customer_charge_to_dto(charge)

    assert dto.name == "Daily Service Fee"
    assert dto.amount_usd == Decimal("1.50")
    assert dto.type.value == "daily"
    assert dto.charge_id is not None


# Full Tariff Conversion Tests


def test_tariff_to_dto_counts(utility):
    """Test converting full tariff produces correct charge counts."""
    tariff = Tariff.objects.create(utility=utility, name="Complete Tariff")

    # Create multiple charges of each type
    EnergyCharge.objects.create(
        tariff=tariff,
        name="Off Peak",
        rate_usd_per_kwh=Decimal("0.10"),
    )
    EnergyCharge.objects.create(
        tariff=tariff,
        name="On Peak",
        rate_usd_per_kwh=Decimal("0.20"),
    )

    DemandCharge.objects.create(
        tariff=tariff,
        name="Demand",
        rate_usd_per_kw=Decimal("10.00"),
        peak_type="monthly",
    )

    CustomerCharge.objects.create(tariff=tariff, name="Service Fee", amount_usd=Decimal("20.00"))

    tariff = Tariff.objects.prefetch_related(
        "energy_charges__applicability_rules",
        "demand_charges__applicability_rules",
        "customer_charges",
    ).get(pk=tariff.pk)

    tariff_dto = tariff_to_dto(tariff)

    assert len(tariff_dto.energy_charges) == 2
    assert len(tariff_dto.demand_charges) == 1
    assert len(tariff_dto.customer_charges) == 1


def test_tariff_to_dto_immutability(utility):
    """Test that Tariff uses tuples (immutable)."""
    tariff = Tariff.objects.create(utility=utility, name="Test Tariff")

    EnergyCharge.objects.create(
        tariff=tariff,
        name="Test Charge",
        rate_usd_per_kwh=Decimal("0.15"),
    )

    tariff = Tariff.objects.prefetch_related(
        "energy_charges__applicability_rules",
        "demand_charges__applicability_rules",
        "customer_charges",
    ).get(pk=tariff.pk)

    tariff_dto = tariff_to_dto(tariff)

    assert isinstance(tariff_dto.energy_charges, tuple)
    assert isinstance(tariff_dto.demand_charges, tuple)
    assert isinstance(tariff_dto.customer_charges, tuple)


def test_empty_tariff_conversion(utility):
    """Test converting tariff with no charges."""
    empty_tariff = Tariff.objects.create(utility=utility, name="Empty Tariff")

    tariff_dto = tariff_to_dto(empty_tariff)

    assert len(tariff_dto.energy_charges) == 0
    assert len(tariff_dto.demand_charges) == 0
    assert len(tariff_dto.customer_charges) == 0


# Batch Tariff Conversion Tests


def test_batch_conversion(utility):
    """Test batch converting multiple tariffs."""
    tariff1 = Tariff.objects.create(utility=utility, name="Tariff 1")
    EnergyCharge.objects.create(
        tariff=tariff1,
        name="Energy 1",
        rate_usd_per_kwh=Decimal("0.15"),
    )

    tariff2 = Tariff.objects.create(utility=utility, name="Tariff 2")
    DemandCharge.objects.create(
        tariff=tariff2,
        name="Demand 2",
        rate_usd_per_kw=Decimal("12.00"),
        peak_type="monthly",
    )

    queryset = Tariff.objects.all()
    tariff_dtos = tariffs_to_dtos(queryset)

    assert len(tariff_dtos) == 2
    assert tariff1.pk in tariff_dtos
    assert tariff2.pk in tariff_dtos

    # Verify contents
    assert len(tariff_dtos[tariff1.pk].energy_charges) == 1
    assert len(tariff_dtos[tariff2.pk].demand_charges) == 1


def test_batch_conversion_returns_dict(utility):
    """Test batch conversion returns dictionary keyed by tariff PK."""
    Tariff.objects.create(utility=utility, name="Tariff 1")
    Tariff.objects.create(utility=utility, name="Tariff 2")

    queryset = Tariff.objects.all()
    tariff_dtos = tariffs_to_dtos(queryset)

    assert isinstance(tariff_dtos, dict)
    for key in tariff_dtos.keys():
        assert isinstance(key, int)  # PKs are integers
