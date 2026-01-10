import datetime
from decimal import Decimal

from django.test import TestCase

from utilities.models import Utility
from tariffs.models import Tariff, EnergyCharge


class EnergyChargeModelTests(TestCase):
    def setUp(self):
        """Create utility and tariff for energy charge tests."""
        self.utility = Utility.objects.create(
            name="PG&E", timezone="America/Los_Angeles"
        )
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

    def test_create_and_str(self):
        """Test creating an energy charge and its string representation."""
        charge = EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Energy",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_utc=datetime.time(12, 0, 0),
            period_end_time_utc=datetime.time(18, 0, 0),
        )
        self.assertIsNotNone(charge.pk)
        self.assertEqual(str(charge), "B-19 - Summer Peak Energy ($0.15432/kWh)")

    def test_cascade_delete(self):
        """Test that energy charges are deleted when tariff is deleted."""
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Energy",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_utc=datetime.time(12, 0, 0),
            period_end_time_utc=datetime.time(18, 0, 0),
        )
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Winter Off-Peak Energy",
            rate_usd_per_kwh=Decimal("0.09876"),
            period_start_time_utc=datetime.time(0, 0, 0),
            period_end_time_utc=datetime.time(6, 0, 0),
        )

        self.assertEqual(EnergyCharge.objects.count(), 2)

        self.tariff.delete()

        self.assertEqual(EnergyCharge.objects.count(), 0)
