import datetime

from django.db import IntegrityError
from django.test import TestCase

from utilities.models import Holiday, Utility


class HolidayModelTests(TestCase):
    def setUp(self):
        """Create a utility for use in holiday tests."""
        self.utility = Utility.objects.create(name="PG&E", timezone="America/Los_Angeles")

    def test_create_and_str(self):
        """Test creating a holiday and its string representation."""
        holiday = Holiday.objects.create(
            utility=self.utility,
            name="Independence Day",
            date=datetime.date(2024, 7, 4),
        )
        self.assertIsNotNone(holiday.pk)
        self.assertEqual(str(holiday), "PG&E - Independence Day (2024-07-04)")

    def test_unique_together_constraint(self):
        """Test that utility+date combination must be unique."""
        date = datetime.date(2024, 7, 4)
        Holiday.objects.create(utility=self.utility, name="Independence Day", date=date)
        with self.assertRaises(IntegrityError):
            Holiday.objects.create(utility=self.utility, name="July 4th", date=date)

    def test_cascade_delete(self):
        """Test that holidays are deleted when their utility is deleted."""
        Holiday.objects.create(
            utility=self.utility,
            name="Independence Day",
            date=datetime.date(2024, 7, 4),
        )
        Holiday.objects.create(
            utility=self.utility,
            name="Christmas",
            date=datetime.date(2024, 12, 25),
        )
        self.assertEqual(Holiday.objects.count(), 2)

        self.utility.delete()
        self.assertEqual(Holiday.objects.count(), 0)
