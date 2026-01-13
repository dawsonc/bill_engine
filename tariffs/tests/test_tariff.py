import datetime
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from tariffs.models import CustomerCharge, DemandCharge, EnergyCharge, Tariff
from utilities.models import Utility


class TariffModelTests(TestCase):
    def setUp(self):
        """Create a utility for use in tariff tests."""
        self.utility = Utility.objects.create(name="PG&E")

    def test_create_and_str(self):
        """Test creating a tariff and its string representation."""
        tariff = Tariff.objects.create(name="B-19", utility=self.utility)
        self.assertIsNotNone(tariff.pk)
        self.assertEqual(str(tariff), "B-19 (PG&E)")

    def test_unique_together_constraint(self):
        """Test that utility+name combination must be unique."""
        Tariff.objects.create(name="B-19", utility=self.utility)
        with self.assertRaises(IntegrityError):
            Tariff.objects.create(name="B-19", utility=self.utility)

    def test_cascade_delete_charges(self):
        """Test that all charge types are deleted when tariff is deleted."""
        tariff = Tariff.objects.create(name="B-19", utility=self.utility)

        # Create one of each charge type
        EnergyCharge.objects.create(
            tariff=tariff,
            name="Summer Peak Energy",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
        )
        DemandCharge.objects.create(
            tariff=tariff,
            name="Summer Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            peak_type="monthly",
        )
        CustomerCharge.objects.create(
            tariff=tariff,
            name="Basic Service",
            amount_usd=Decimal("15.00"),
        )

        # Verify charges exist
        self.assertEqual(EnergyCharge.objects.filter(tariff=tariff).count(), 1)
        self.assertEqual(DemandCharge.objects.filter(tariff=tariff).count(), 1)
        self.assertEqual(CustomerCharge.objects.filter(tariff=tariff).count(), 1)

        # Delete tariff and verify cascade
        tariff.delete()
        self.assertEqual(EnergyCharge.objects.count(), 0)
        self.assertEqual(DemandCharge.objects.count(), 0)
        self.assertEqual(CustomerCharge.objects.count(), 0)
