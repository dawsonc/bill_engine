import datetime
from decimal import Decimal

from django.test import TestCase

from tariffs.models import ApplicabilityRule, EnergyCharge, Tariff
from utilities.models import Utility


class EnergyChargeModelTests(TestCase):
    def setUp(self):
        """Create utility and tariff for energy charge tests."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

    def test_create_and_str(self):
        """Test creating an energy charge and its string representation."""
        charge = EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Energy",
            rate_usd_per_kwh=Decimal("0.15432"),
        )
        self.assertIsNotNone(charge.pk)
        self.assertEqual(str(charge), "B-19 - Summer Peak Energy ($0.15432/kWh)")

    def test_cascade_delete(self):
        """Test that energy charges are deleted when tariff is deleted."""
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Energy",
            rate_usd_per_kwh=Decimal("0.15432"),
        )
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Winter Off-Peak Energy",
            rate_usd_per_kwh=Decimal("0.09876"),
        )

        self.assertEqual(EnergyCharge.objects.count(), 2)

        self.tariff.delete()

        self.assertEqual(EnergyCharge.objects.count(), 0)

    def test_link_applicability_rules(self):
        """Test linking applicability rules to energy charge."""
        rule1 = ApplicabilityRule.objects.create(
            name="Peak Hours",
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
        )
        rule2 = ApplicabilityRule.objects.create(
            name="Off-Peak Hours",
            period_start_time_local=datetime.time(0, 0),
            period_end_time_local=datetime.time(12, 0),
        )

        charge = EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Peak Energy",
            rate_usd_per_kwh=Decimal("0.25"),
        )
        charge.applicability_rules.add(rule1, rule2)

        self.assertEqual(charge.applicability_rules.count(), 2)

    def test_charge_without_rules_valid(self):
        """Test that energy charge without applicability rules is valid."""
        charge = EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Base Energy",
            rate_usd_per_kwh=Decimal("0.10"),
        )
        charge.full_clean()  # Should not raise
        self.assertEqual(charge.applicability_rules.count(), 0)
