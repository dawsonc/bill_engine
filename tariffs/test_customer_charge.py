from decimal import Decimal

from django.test import TestCase

from utilities.models import Utility
from tariffs.models import Tariff, CustomerCharge


class CustomerChargeModelTests(TestCase):
    def setUp(self):
        """Create utility and tariff for customer charge tests."""
        self.utility = Utility.objects.create(
            name="PG&E", timezone="America/Los_Angeles"
        )
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

    def test_create_and_str(self):
        """Test creating a customer charge and its string representation."""
        charge = CustomerCharge.objects.create(
            tariff=self.tariff,
            name="Basic Service",
            usd_per_month=Decimal("15.00"),
        )
        self.assertIsNotNone(charge.pk)
        self.assertEqual(str(charge), "B-19 - Basic Service ($15.00/month)")

    def test_cascade_delete(self):
        """Test that customer charges are deleted when tariff is deleted."""
        CustomerCharge.objects.create(
            tariff=self.tariff,
            name="Basic Service",
            usd_per_month=Decimal("15.00"),
        )
        CustomerCharge.objects.create(
            tariff=self.tariff,
            name="Meter Charge",
            usd_per_month=Decimal("5.00"),
        )

        self.assertEqual(CustomerCharge.objects.count(), 2)

        self.tariff.delete()

        self.assertEqual(CustomerCharge.objects.count(), 0)
