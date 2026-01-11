import time

from django.db.models import ProtectedError
from django.test import TestCase

from tariffs.models import Tariff
from utilities.models import Utility

from customers.models import Customer


class CustomerModelTests(TestCase):
    def setUp(self):
        """Create required utility and tariff for customer tests."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

    def test_create_and_str(self):
        """Test creating a customer and its string representation."""
        customer = Customer.objects.create(name="Acme Corp", timezone="America/Los_Angeles", current_tariff=self.tariff)
        self.assertIsNotNone(customer.pk)
        self.assertEqual(str(customer), "Acme Corp")

    def test_protect_tariff_with_customers(self):
        """Test that tariffs with customers cannot be deleted (PROTECT)."""
        Customer.objects.create(name="Acme Corp", timezone="America/Los_Angeles", current_tariff=self.tariff)

        with self.assertRaises(ProtectedError):
            self.tariff.delete()

    def test_auto_timestamps(self):
        """Test that created_at and updated_at are set automatically."""
        customer = Customer.objects.create(name="Acme Corp", timezone="America/Los_Angeles", current_tariff=self.tariff)

        # Verify created_at is set
        self.assertIsNotNone(customer.created_at)
        self.assertIsNotNone(customer.updated_at)

        # Save original timestamps
        created_at = customer.created_at
        updated_at = customer.updated_at

        # Wait a moment and update
        time.sleep(0.01)
        customer.name = "Acme Corporation"
        customer.save()

        # Refresh from database
        customer.refresh_from_db()

        # created_at should not change
        self.assertEqual(customer.created_at, created_at)
        # updated_at should change
        self.assertGreater(customer.updated_at, updated_at)
