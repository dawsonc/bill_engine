"""
Unit tests for billing adapters.

Tests conversion from Django ORM models to billing DTOs.
"""

from datetime import time
from decimal import Decimal

from django.test import TestCase

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
from utilities.models import Utility


class GenerateChargeIdTests(TestCase):
    """Tests for deterministic ChargeId generation."""

    def test_charge_id_deterministic(self):
        """Same model and PK should produce same ChargeId."""
        charge_id_1 = generate_charge_id("EnergyCharge", 42)
        charge_id_2 = generate_charge_id("EnergyCharge", 42)
        self.assertEqual(charge_id_1, charge_id_2)
        self.assertEqual(charge_id_1.value, charge_id_2.value)

    def test_charge_id_different_models_different_ids(self):
        """Different models with same PK should produce different ChargeIds."""
        energy_id = generate_charge_id("EnergyCharge", 1)
        demand_id = generate_charge_id("DemandCharge", 1)
        self.assertNotEqual(energy_id.value, demand_id.value)

    def test_charge_id_different_pks_different_ids(self):
        """Same model with different PKs should produce different ChargeIds."""
        charge_id_1 = generate_charge_id("EnergyCharge", 1)
        charge_id_2 = generate_charge_id("EnergyCharge", 2)
        self.assertNotEqual(charge_id_1.value, charge_id_2.value)


class BuildDayTypesTests(TestCase):
    """Tests for day types conversion."""

    def test_all_day_types_true(self):
        """All day types enabled should return all three DayTypes."""
        result = build_day_types(
            applies_weekdays=True, applies_weekends=True, applies_holidays=True
        )
        self.assertEqual(
            result, frozenset({DayType.WEEKDAY, DayType.WEEKEND, DayType.HOLIDAY})
        )

    def test_only_weekdays(self):
        """Only weekdays should return only WEEKDAY."""
        result = build_day_types(
            applies_weekdays=True, applies_weekends=False, applies_holidays=False
        )
        self.assertEqual(result, frozenset({DayType.WEEKDAY}))

    def test_weekdays_and_weekends(self):
        """Weekdays and weekends should return both."""
        result = build_day_types(
            applies_weekdays=True, applies_weekends=True, applies_holidays=False
        )
        self.assertEqual(result, frozenset({DayType.WEEKDAY, DayType.WEEKEND}))

    def test_all_false_returns_empty(self):
        """All day types disabled should return empty frozenset."""
        result = build_day_types(
            applies_weekdays=False, applies_weekends=False, applies_holidays=False
        )
        self.assertEqual(result, frozenset())


class BuildApplicabilityRuleTests(TestCase):
    """Tests for ApplicabilityRule construction."""

    def test_full_applicability_rule(self):
        """Test creating ApplicabilityRule with all fields."""
        from datetime import date

        rule = build_applicability_rule(
            period_start_time_local=time(8, 0),
            period_end_time_local=time(17, 0),
            applies_start_date=date(2024, 6, 1),
            applies_end_date=date(2024, 8, 31),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        self.assertEqual(rule.period_start, time(8, 0))
        self.assertEqual(rule.period_end, time(17, 0))
        self.assertEqual(rule.start_date, date(2024, 6, 1))
        self.assertEqual(rule.end_date, date(2024, 8, 31))
        self.assertEqual(rule.day_types, frozenset({DayType.WEEKDAY}))

    def test_applicability_rule_with_nulls(self):
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

        self.assertIsNone(rule.start_date)
        self.assertIsNone(rule.end_date)
        self.assertEqual(
            rule.day_types, frozenset({DayType.WEEKDAY, DayType.WEEKEND, DayType.HOLIDAY})
        )

    def test_invalid_time_period_raises_error(self):
        """ApplicabilityRule should reject invalid time periods."""
        with self.assertRaises(ValueError):
            build_applicability_rule(
                period_start_time_local=time(17, 0),
                period_end_time_local=time(8, 0),  # End before start
                applies_start_date=None,
                applies_end_date=None,
                applies_weekdays=True,
                applies_weekends=True,
                applies_holidays=True,
            )


class EnergyChargeToDtoTests(TestCase):
    """Tests for EnergyCharge conversion."""

    def setUp(self):
        """Create test utility and tariff."""
        self.utility = Utility.objects.create(name="Test Utility")
        self.tariff = Tariff.objects.create(utility=self.utility, name="Test Tariff")

    def test_energy_charge_conversion(self):
        """Test converting EnergyCharge model to DTO."""
        charge = EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Peak Energy",
            rate_usd_per_kwh=Decimal("0.25"),
            period_start_time_local=time(12, 0),
            period_end_time_local=time(18, 0),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        dto = energy_charge_to_dto(charge)

        self.assertEqual(dto.name, "Peak Energy")
        self.assertEqual(dto.rate_per_kwh, Decimal("0.25"))
        self.assertEqual(dto.applicability.period_start, time(12, 0))
        self.assertEqual(dto.applicability.period_end, time(18, 0))
        self.assertEqual(dto.applicability.day_types, frozenset({DayType.WEEKDAY}))

    def test_energy_charge_id_stability(self):
        """ChargeId should be stable across multiple conversions."""
        charge = EnergyCharge.objects.create(
            tariff=self.tariff,
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

        self.assertEqual(dto1.charge_id, dto2.charge_id)


class DemandChargeToDtoTests(TestCase):
    """Tests for DemandCharge conversion."""

    def setUp(self):
        """Create test utility and tariff."""
        self.utility = Utility.objects.create(name="Test Utility")
        self.tariff = Tariff.objects.create(utility=self.utility, name="Test Tariff")

    def test_demand_charge_conversion_monthly(self):
        """Test converting monthly DemandCharge to DTO."""
        charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Monthly Demand",
            rate_usd_per_kw=Decimal("15.00"),
            peak_type="monthly",
            period_start_time_local=time(0, 0),
            period_end_time_local=time(23, 59),
            applies_weekdays=True,
            applies_weekends=True,
            applies_holidays=True,
        )

        dto = demand_charge_to_dto(charge)

        self.assertEqual(dto.name, "Monthly Demand")
        self.assertEqual(dto.rate_per_kw, Decimal("15.00"))
        self.assertEqual(dto.type, PeakType.MONTHLY)

    def test_demand_charge_conversion_daily(self):
        """Test converting daily DemandCharge to DTO."""
        charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Daily Demand",
            rate_usd_per_kw=Decimal("5.00"),
            peak_type="daily",
            period_start_time_local=time(0, 0),
            period_end_time_local=time(23, 59),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        dto = demand_charge_to_dto(charge)

        self.assertEqual(dto.type, PeakType.DAILY)

    def test_demand_charge_invalid_peak_type_raises_error(self):
        """Invalid peak_type should raise ValueError."""
        charge = DemandCharge.objects.create(
            tariff=self.tariff,
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

        with self.assertRaises(ValueError) as context:
            demand_charge_to_dto(charge)

        self.assertIn("Invalid peak_type", str(context.exception))


class CustomerChargeToDtoTests(TestCase):
    """Tests for CustomerCharge conversion."""

    def setUp(self):
        """Create test utility and tariff."""
        self.utility = Utility.objects.create(name="Test Utility")
        self.tariff = Tariff.objects.create(utility=self.utility, name="Test Tariff")

    def test_customer_charge_conversion(self):
        """Test converting CustomerCharge model to DTO."""
        charge = CustomerCharge.objects.create(
            tariff=self.tariff, name="Monthly Service Fee", usd_per_month=Decimal("25.00")
        )

        dto = customer_charge_to_dto(charge)

        self.assertEqual(dto.name, "Monthly Service Fee")
        self.assertEqual(dto.amount, Decimal("25.00"))
        # CustomerCharge has no applicability rule
        self.assertIsNotNone(dto.charge_id)


class TariffToChargeListTests(TestCase):
    """Tests for full tariff conversion."""

    def setUp(self):
        """Create test utility and tariff with multiple charges."""
        self.utility = Utility.objects.create(name="Test Utility")
        self.tariff = Tariff.objects.create(utility=self.utility, name="Complete Tariff")

        # Create multiple charges of each type
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Off Peak",
            rate_usd_per_kwh=Decimal("0.10"),
            period_start_time_local=time(0, 0),
            period_end_time_local=time(12, 0),
            applies_weekdays=True,
            applies_weekends=True,
            applies_holidays=True,
        )
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="On Peak",
            rate_usd_per_kwh=Decimal("0.20"),
            period_start_time_local=time(12, 0),
            period_end_time_local=time(18, 0),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        DemandCharge.objects.create(
            tariff=self.tariff,
            name="Demand",
            rate_usd_per_kw=Decimal("10.00"),
            peak_type="monthly",
            period_start_time_local=time(0, 0),
            period_end_time_local=time(23, 59),
            applies_weekdays=True,
            applies_weekends=True,
            applies_holidays=True,
        )

        CustomerCharge.objects.create(
            tariff=self.tariff, name="Service Fee", usd_per_month=Decimal("20.00")
        )

    def test_tariff_to_charge_list_counts(self):
        """Test converting full tariff produces correct charge counts."""
        tariff = Tariff.objects.prefetch_related(
            "energy_charges", "demand_charges", "customer_charges"
        ).get(pk=self.tariff.pk)

        charge_list = tariff_to_charge_list(tariff)

        self.assertEqual(len(charge_list.energy_charges), 2)
        self.assertEqual(len(charge_list.demand_charges), 1)
        self.assertEqual(len(charge_list.customer_charges), 1)

    def test_tariff_to_charge_list_immutability(self):
        """Test that ChargeList uses tuples (immutable)."""
        tariff = Tariff.objects.prefetch_related(
            "energy_charges", "demand_charges", "customer_charges"
        ).get(pk=self.tariff.pk)

        charge_list = tariff_to_charge_list(tariff)

        self.assertIsInstance(charge_list.energy_charges, tuple)
        self.assertIsInstance(charge_list.demand_charges, tuple)
        self.assertIsInstance(charge_list.customer_charges, tuple)

    def test_empty_tariff_conversion(self):
        """Test converting tariff with no charges."""
        empty_tariff = Tariff.objects.create(utility=self.utility, name="Empty Tariff")

        charge_list = tariff_to_charge_list(empty_tariff)

        self.assertEqual(len(charge_list.energy_charges), 0)
        self.assertEqual(len(charge_list.demand_charges), 0)
        self.assertEqual(len(charge_list.customer_charges), 0)


class TariffsToChargeListsTests(TestCase):
    """Tests for batch tariff conversion."""

    def setUp(self):
        """Create multiple test tariffs."""
        self.utility = Utility.objects.create(name="Test Utility")

        self.tariff1 = Tariff.objects.create(utility=self.utility, name="Tariff 1")
        EnergyCharge.objects.create(
            tariff=self.tariff1,
            name="Energy 1",
            rate_usd_per_kwh=Decimal("0.15"),
            period_start_time_local=time(0, 0),
            period_end_time_local=time(23, 59),
            applies_weekdays=True,
            applies_weekends=True,
            applies_holidays=True,
        )

        self.tariff2 = Tariff.objects.create(utility=self.utility, name="Tariff 2")
        DemandCharge.objects.create(
            tariff=self.tariff2,
            name="Demand 2",
            rate_usd_per_kw=Decimal("12.00"),
            peak_type="monthly",
            period_start_time_local=time(0, 0),
            period_end_time_local=time(23, 59),
            applies_weekdays=True,
            applies_weekends=True,
            applies_holidays=True,
        )

    def test_batch_conversion(self):
        """Test batch converting multiple tariffs."""
        queryset = Tariff.objects.all()
        charge_lists = tariffs_to_charge_lists(queryset)

        self.assertEqual(len(charge_lists), 2)
        self.assertIn(self.tariff1.pk, charge_lists)
        self.assertIn(self.tariff2.pk, charge_lists)

        # Verify contents
        self.assertEqual(len(charge_lists[self.tariff1.pk].energy_charges), 1)
        self.assertEqual(len(charge_lists[self.tariff2.pk].demand_charges), 1)

    def test_batch_conversion_returns_dict(self):
        """Test batch conversion returns dictionary keyed by tariff PK."""
        queryset = Tariff.objects.all()
        charge_lists = tariffs_to_charge_lists(queryset)

        self.assertIsInstance(charge_lists, dict)
        for key in charge_lists.keys():
            self.assertIsInstance(key, int)  # PKs are integers
