import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from customers.models import Customer
from tariffs.models import Tariff
from usage.models import CustomerUsage
from utilities.models import Utility


class CustomerUsageTests(TestCase):
    def setUp(self):
        """Create required utility, tariff, and customer for usage tests."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)
        self.customer = Customer.objects.create(
            name="Acme Corp", timezone="America/Los_Angeles", current_tariff=self.tariff
        )

    def test_create_and_str(self):
        """Test creating a usage record and its string representation."""
        interval_start = datetime.datetime(2024, 7, 4, 12, 0, 0, tzinfo=datetime.timezone.utc)
        interval_end = datetime.datetime(2024, 7, 4, 12, 5, 0, tzinfo=datetime.timezone.utc)

        usage = CustomerUsage.objects.create(
            customer=self.customer,
            interval_start_utc=interval_start,
            interval_end_utc=interval_end,
            energy_kwh=5.25,
            peak_demand_kw=63.0,
        )

        self.assertIsNotNone(usage.pk)
        expected_str = "Acme Corp - 2024-07-04 12:00:00+00:00 (5.25 kWh, 63 kW)"
        self.assertEqual(str(usage), expected_str)

    def test_unique_together_constraint(self):
        """Test that customer+interval_start_utc combination must be unique."""
        interval_start = datetime.datetime(2024, 7, 4, 12, 0, 0, tzinfo=datetime.timezone.utc)
        interval_end = datetime.datetime(2024, 7, 4, 12, 5, 0, tzinfo=datetime.timezone.utc)

        CustomerUsage.objects.create(
            customer=self.customer,
            interval_start_utc=interval_start,
            interval_end_utc=interval_end,
            energy_kwh=5.25,
            peak_demand_kw=63.0,
        )

        with self.assertRaises(ValidationError):
            CustomerUsage.objects.create(
                customer=self.customer,
                interval_start_utc=interval_start,
                interval_end_utc=interval_end,
                energy_kwh=10.0,
                peak_demand_kw=120.0,
            )

    def test_cascade_delete(self):
        """Test that usage records are deleted when customer is deleted."""
        interval_start = datetime.datetime(2024, 7, 4, 12, 0, 0, tzinfo=datetime.timezone.utc)
        interval_end = datetime.datetime(2024, 7, 4, 12, 5, 0, tzinfo=datetime.timezone.utc)

        CustomerUsage.objects.create(
            customer=self.customer,
            interval_start_utc=interval_start,
            interval_end_utc=interval_end,
            energy_kwh=5.25,
            peak_demand_kw=63.0,
        )

        CustomerUsage.objects.create(
            customer=self.customer,
            interval_start_utc=datetime.datetime(
                2024, 7, 4, 12, 5, 0, tzinfo=datetime.timezone.utc
            ),
            interval_end_utc=datetime.datetime(2024, 7, 4, 12, 10, 0, tzinfo=datetime.timezone.utc),
            energy_kwh=6.0,
            peak_demand_kw=70.0,
        )

        self.assertEqual(CustomerUsage.objects.count(), 2)

        self.customer.delete()
        self.assertEqual(CustomerUsage.objects.count(), 0)
