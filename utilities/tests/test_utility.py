from django.db import IntegrityError
from django.test import TestCase

from utilities.models import Utility


class UtilityModelTests(TestCase):
    def test_create_and_str(self):
        """Test creating a utility and its string representation."""
        utility = Utility.objects.create(name="PG&E")
        self.assertIsNotNone(utility.pk)
        self.assertEqual(str(utility), "PG&E")

    def test_name_uniqueness(self):
        """Test that utility names must be unique."""
        Utility.objects.create(name="PG&E")
        with self.assertRaises(IntegrityError):
            Utility.objects.create(name="PG&E")
