import datetime
from decimal import Decimal

from django.test import TestCase

from tariffs.models import ApplicabilityRule, DemandCharge, Tariff
from utilities.models import Utility


class DemandChargeModelTests(TestCase):
    def setUp(self):
        """Create utility and tariff for demand charge tests."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

    def test_create_and_str(self):
        """Test creating a demand charge and its string representation."""
        charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            peak_type="monthly",
        )
        self.assertIsNotNone(charge.pk)
        self.assertEqual(str(charge), "B-19 - Summer Peak Demand ($18.50/kW, monthly)")

    def test_peak_type_choices(self):
        """Test that both peak_type choices work correctly."""
        daily_charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Daily Peak Demand",
            rate_usd_per_kw=Decimal("15.00"),
            peak_type="daily",
        )
        daily_charge.refresh_from_db()
        self.assertEqual(daily_charge.peak_type, "daily")

        monthly_charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Monthly Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            peak_type="monthly",
        )
        monthly_charge.refresh_from_db()
        self.assertEqual(monthly_charge.peak_type, "monthly")

    def test_cascade_delete(self):
        """Test that demand charges are deleted when tariff is deleted."""
        DemandCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            peak_type="monthly",
        )

        self.assertEqual(DemandCharge.objects.count(), 1)

        self.tariff.delete()

        self.assertEqual(DemandCharge.objects.count(), 0)

    def test_link_applicability_rules(self):
        """Test linking applicability rules to demand charge."""
        rule = ApplicabilityRule.objects.create(
            name="Peak Hours",
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Peak Demand",
            rate_usd_per_kw=Decimal("20.00"),
            peak_type="monthly",
        )
        charge.applicability_rules.add(rule)

        self.assertEqual(charge.applicability_rules.count(), 1)
        self.assertEqual(charge.applicability_rules.first().name, "Peak Hours")

    def test_charge_without_rules_valid(self):
        """Test that demand charge without applicability rules is valid."""
        charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Base Demand",
            rate_usd_per_kw=Decimal("10.00"),
            peak_type="monthly",
        )
        charge.full_clean()  # Should not raise
        self.assertEqual(charge.applicability_rules.count(), 0)
