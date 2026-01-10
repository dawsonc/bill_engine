import datetime
from decimal import Decimal

from django.test import TestCase

from utilities.models import Utility
from tariffs.models import Tariff, DemandCharge


class DemandChargeModelTests(TestCase):
    def setUp(self):
        """Create utility and tariff for demand charge tests."""
        self.utility = Utility.objects.create(
            name="PG&E", timezone="America/Los_Angeles"
        )
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

    def test_create_and_str(self):
        """Test creating a demand charge and its string representation."""
        charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_utc=datetime.time(12, 0, 0),
            period_end_time_utc=datetime.time(18, 0, 0),
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
            period_start_time_utc=datetime.time(12, 0, 0),
            period_end_time_utc=datetime.time(18, 0, 0),
            peak_type="daily",
        )
        daily_charge.refresh_from_db()
        self.assertEqual(daily_charge.peak_type, "daily")

        monthly_charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Monthly Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_utc=datetime.time(12, 0, 0),
            period_end_time_utc=datetime.time(18, 0, 0),
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
            period_start_time_utc=datetime.time(12, 0, 0),
            period_end_time_utc=datetime.time(18, 0, 0),
            peak_type="monthly",
        )

        self.assertEqual(DemandCharge.objects.count(), 1)

        self.tariff.delete()

        self.assertEqual(DemandCharge.objects.count(), 0)
