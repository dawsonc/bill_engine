import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from tariffs.models import EnergyCharge, Tariff
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
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
        )
        self.assertIsNotNone(charge.pk)
        self.assertEqual(str(charge), "B-19 - Summer Peak Energy ($0.15432/kWh)")

    def test_cascade_delete(self):
        """Test that energy charges are deleted when tariff is deleted."""
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Energy",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
        )
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Winter Off-Peak Energy",
            rate_usd_per_kwh=Decimal("0.09876"),
            period_start_time_local=datetime.time(0, 0, 0),
            period_end_time_local=datetime.time(6, 0, 0),
        )

        self.assertEqual(EnergyCharge.objects.count(), 2)

        self.tariff.delete()

        self.assertEqual(EnergyCharge.objects.count(), 0)

    def test_period_end_time_must_be_after_start_time(self):
        """Test that period end time must be after start time."""
        # Test equal times (invalid)
        charge = EnergyCharge(
            tariff=self.tariff,
            name="Invalid Equal Times",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(12, 0, 0),
        )
        with self.assertRaises(ValidationError) as cm:
            charge.full_clean()
        self.assertIn('period_end_time_local', cm.exception.message_dict)

    def test_period_end_time_before_start_time(self):
        """Test that period end time cannot be before start time."""
        charge = EnergyCharge(
            tariff=self.tariff,
            name="Invalid Reversed Times",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(18, 0, 0),
            period_end_time_local=datetime.time(12, 0, 0),
        )
        with self.assertRaises(ValidationError) as cm:
            charge.full_clean()
        self.assertIn('period_end_time_local', cm.exception.message_dict)

    def test_applies_end_date_must_be_on_or_after_start_date(self):
        """Test that applicable end date must be on or after start date."""
        # Test end before start (invalid)
        charge = EnergyCharge(
            tariff=self.tariff,
            name="Invalid Date Range",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=datetime.date(2024, 9, 1),
            applies_end_date=datetime.date(2024, 6, 1),
        )
        with self.assertRaises(ValidationError) as cm:
            charge.full_clean()
        self.assertIn('applies_end_date', cm.exception.message_dict)

    def test_applies_same_start_and_end_date_allowed(self):
        """Test that same start and end date is allowed (single-day charge)."""
        charge = EnergyCharge(
            tariff=self.tariff,
            name="Single Day Charge",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=datetime.date(2024, 7, 4),
            applies_end_date=datetime.date(2024, 7, 4),
        )
        charge.full_clean()  # Should not raise
        charge.save()
        self.assertIsNotNone(charge.pk)

    def test_applies_null_dates_allowed(self):
        """Test that null date fields don't trigger validation."""
        # Both null (year-round)
        charge1 = EnergyCharge(
            tariff=self.tariff,
            name="Year-Round Charge",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=None,
            applies_end_date=None,
        )
        charge1.full_clean()  # Should not raise

        # Only start date provided
        charge2 = EnergyCharge(
            tariff=self.tariff,
            name="Open-Ended Start",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=datetime.date(2024, 6, 1),
            applies_end_date=None,
        )
        charge2.full_clean()  # Should not raise

        # Only end date provided
        charge3 = EnergyCharge(
            tariff=self.tariff,
            name="Open-Ended End",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=None,
            applies_end_date=datetime.date(2024, 9, 30),
        )
        charge3.full_clean()  # Should not raise

    def test_valid_charge_with_proper_times_and_dates(self):
        """Test that valid charges pass validation."""
        charge = EnergyCharge(
            tariff=self.tariff,
            name="Valid Summer Peak",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=datetime.date(2024, 6, 1),
            applies_end_date=datetime.date(2024, 9, 30),
        )
        charge.full_clean()  # Should not raise
        charge.save()
        self.assertIsNotNone(charge.pk)
