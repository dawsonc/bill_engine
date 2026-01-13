import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from tariffs.models import DemandCharge, Tariff
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
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
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
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            peak_type="daily",
        )
        daily_charge.refresh_from_db()
        self.assertEqual(daily_charge.peak_type, "daily")

        monthly_charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Monthly Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
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
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            peak_type="monthly",
        )

        self.assertEqual(DemandCharge.objects.count(), 1)

        self.tariff.delete()

        self.assertEqual(DemandCharge.objects.count(), 0)

    def test_period_end_time_must_be_after_start_time(self):
        """Test that period end time must be after start time."""
        # Test equal times (invalid)
        charge = DemandCharge(
            tariff=self.tariff,
            name="Invalid Equal Times",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(12, 0, 0),
            peak_type="monthly",
        )
        with self.assertRaises(ValidationError) as cm:
            charge.full_clean()
        self.assertIn("period_end_time_local", cm.exception.message_dict)

    def test_period_end_time_before_start_time(self):
        """Test that period end time cannot be before start time."""
        charge = DemandCharge(
            tariff=self.tariff,
            name="Invalid Reversed Times",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(18, 0, 0),
            period_end_time_local=datetime.time(12, 0, 0),
            peak_type="monthly",
        )
        with self.assertRaises(ValidationError) as cm:
            charge.full_clean()
        self.assertIn("period_end_time_local", cm.exception.message_dict)

    def test_applies_end_date_must_be_on_or_after_start_date(self):
        """Test that applicable end date must be on or after start date (month/day only)."""
        # Uses year 2000 convention for month/day only comparison
        charge = DemandCharge(
            tariff=self.tariff,
            name="Invalid Date Range",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=datetime.date(2000, 9, 1),
            applies_end_date=datetime.date(2000, 6, 1),
            peak_type="monthly",
        )
        with self.assertRaises(ValidationError) as cm:
            charge.full_clean()
        self.assertIn("applies_end_date", cm.exception.message_dict)

    def test_applies_same_start_and_end_date_allowed(self):
        """Test that same start and end date is allowed (single-day charge)."""
        # Uses year 2000 convention
        charge = DemandCharge(
            tariff=self.tariff,
            name="Single Day Demand",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=datetime.date(2000, 7, 4),
            applies_end_date=datetime.date(2000, 7, 4),
            peak_type="monthly",
        )
        charge.full_clean()  # Should not raise
        charge.save()
        self.assertIsNotNone(charge.pk)

    def test_applies_null_dates_allowed(self):
        """Test that null date fields don't trigger validation."""
        # Both null (year-round)
        charge = DemandCharge(
            tariff=self.tariff,
            name="Year-Round Demand",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=None,
            applies_end_date=None,
            peak_type="monthly",
        )
        charge.full_clean()  # Should not raise
        charge.save()
        self.assertIsNotNone(charge.pk)

    def test_valid_charge_with_proper_times_and_dates(self):
        """Test that valid charges pass validation with year 2000 convention."""
        charge = DemandCharge(
            tariff=self.tariff,
            name="Valid Summer Peak",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0, 0),
            period_end_time_local=datetime.time(18, 0, 0),
            applies_start_date=datetime.date(2000, 6, 1),
            applies_end_date=datetime.date(2000, 9, 30),
            peak_type="monthly",
        )
        charge.full_clean()  # Should not raise
        charge.save()
        self.assertIsNotNone(charge.pk)
