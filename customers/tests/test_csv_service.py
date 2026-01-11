"""
Unit tests for CSV import/export service.

Tests validation, error handling, and roundtrip functionality for customer CSV operations.
"""

from pathlib import Path

from django.test import TestCase

from customers.csv_service import CustomerCSVExporter, CustomerCSVImporter
from customers.models import Customer
from tariffs.models import Tariff
from utilities.models import Utility


class CustomerCSVExporterTests(TestCase):
    """Test CSV export functionality."""

    def setUp(self):
        """Create test data for export."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

    def test_export_comprehensive(self):
        """Test CSV export with structure, multiple customers, special characters."""
        # Create customers with various edge cases
        Customer.objects.create(
            name="Customer A",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff
        )
        Customer.objects.create(
            name="Customer, With Comma",
            timezone="America/New_York",
            current_tariff=self.tariff
        )
        Customer.objects.create(
            name="Café François",
            timezone="America/Chicago",
            current_tariff=self.tariff
        )

        # Export all customers
        customers = Customer.objects.all()
        exporter = CustomerCSVExporter(customers)
        csv_str = exporter.export_to_csv()

        lines = [line.rstrip('\r') for line in csv_str.strip().split('\n')]

        # Check CSV structure
        self.assertEqual(lines[0], 'name,timezone,utility_name,tariff_name')
        self.assertEqual(len(lines), 4)  # Header + 3 customers

        # Check all customer names are present
        self.assertIn('Customer A', csv_str)
        self.assertIn('Customer, With Comma', csv_str)
        self.assertIn('Café François', csv_str)

        # Check timezones are preserved
        self.assertIn('America/Los_Angeles', csv_str)
        self.assertIn('America/New_York', csv_str)
        self.assertIn('America/Chicago', csv_str)

        # Check utility and tariff
        self.assertIn('PG&E', csv_str)
        self.assertIn('B-19', csv_str)

    def test_export_empty_queryset(self):
        """Test exporting empty queryset."""
        customers = Customer.objects.none()
        exporter = CustomerCSVExporter(customers)
        csv_str = exporter.export_to_csv()

        lines = csv_str.strip().split('\n')
        self.assertEqual(len(lines), 1)  # Just header
        self.assertEqual(lines[0], 'name,timezone,utility_name,tariff_name')


class CustomerCSVImporterTests(TestCase):
    """Test CSV import functionality."""

    def setUp(self):
        """Create required utilities and tariffs for customer tests."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)
        self.fixtures_dir = Path(__file__).parent / "fixtures"

    def _read_fixture(self, filename):
        """Helper to read fixture file content."""
        return (self.fixtures_dir / filename).read_text()

    def test_import_valid_customers(self):
        """Test importing valid customers including unicode and commas."""
        csv_content = self._read_fixture("valid_customers.csv")
        importer = CustomerCSVImporter(csv_content, replace_existing=False)
        results = importer.import_customers()

        self.assertEqual(len(results['created']), 3)
        self.assertEqual(len(results['updated']), 0)
        self.assertEqual(len(results['skipped']), 0)
        self.assertEqual(len(results['errors']), 0)

        # Verify all customers were created with special cases
        self.assertTrue(Customer.objects.filter(name="Customer A").exists())
        self.assertTrue(Customer.objects.filter(name="Customer, With Comma").exists())
        self.assertTrue(Customer.objects.filter(name="Café François").exists())

        # Verify comma in name is preserved
        customer_comma = Customer.objects.get(name="Customer, With Comma")
        self.assertEqual(customer_comma.name, "Customer, With Comma")

    def test_import_validation_errors(self):
        """Test all validation error cases."""
        # Test invalid CSV syntax
        with self.subTest("invalid_csv_syntax"):
            csv_content = self._read_fixture("invalid_csv_syntax.csv")
            importer = CustomerCSVImporter(csv_content, replace_existing=False)
            results = importer.import_customers()
            self.assertEqual(len(results['errors']), 1)
            self.assertIn('CSV File', results['errors'][0][0])

        # Test missing required field
        with self.subTest("missing_required_field"):
            csv_content = self._read_fixture("missing_fields.csv")
            importer = CustomerCSVImporter(csv_content, replace_existing=False)
            results = importer.import_customers()
            self.assertEqual(len(results['errors']), 1)
            error_identifier, error_messages = results['errors'][0]
            self.assertIn('Row 2', error_identifier)
            self.assertTrue(any('timezone' in msg for msg in error_messages))

        # Test invalid timezone
        with self.subTest("invalid_timezone"):
            csv_content = self._read_fixture("invalid_timezone.csv")
            importer = CustomerCSVImporter(csv_content, replace_existing=False)
            results = importer.import_customers()
            self.assertEqual(len(results['errors']), 1)
            error_identifier, error_messages = results['errors'][0]
            self.assertIn('Row 2', error_identifier)
            self.assertTrue(any('timezone' in msg.lower() for msg in error_messages))

        # Test tariff not found
        with self.subTest("tariff_not_found"):
            csv_content = "name,timezone,utility_name,tariff_name\nCustomer X,America/Los_Angeles,PG&E,NonExistentTariff"
            importer = CustomerCSVImporter(csv_content, replace_existing=False)
            results = importer.import_customers()
            self.assertEqual(len(results['errors']), 1)
            error_identifier, error_messages = results['errors'][0]
            self.assertIn('Row 2', error_identifier)
            self.assertTrue(any('not found' in msg for msg in error_messages))

        # Test utility not found
        with self.subTest("utility_not_found"):
            csv_content = "name,timezone,utility_name,tariff_name\nCustomer Y,America/Los_Angeles,NonExistentUtility,B-19"
            importer = CustomerCSVImporter(csv_content, replace_existing=False)
            results = importer.import_customers()
            self.assertEqual(len(results['errors']), 1)
            error_identifier, error_messages = results['errors'][0]
            self.assertIn('Row 2', error_identifier)
            self.assertTrue(any('not found' in msg for msg in error_messages))

        # Test empty file
        with self.subTest("empty_file"):
            csv_content = "name,timezone,utility_name,tariff_name\n"
            importer = CustomerCSVImporter(csv_content, replace_existing=False)
            results = importer.import_customers()
            self.assertEqual(len(results['errors']), 1)
            self.assertIn('No data rows', results['errors'][0][1][0])

        # Test wrong header
        with self.subTest("wrong_header"):
            csv_content = "wrong,header,columns,here\ndata,data,data,data"
            importer = CustomerCSVImporter(csv_content, replace_existing=False)
            results = importer.import_customers()
            self.assertEqual(len(results['errors']), 1)
            self.assertIn('CSV File', results['errors'][0][0])
            self.assertTrue(any('header' in msg.lower() for msg in results['errors'][0][1]))

        # Test missing header
        with self.subTest("missing_header"):
            csv_content = ""
            importer = CustomerCSVImporter(csv_content, replace_existing=False)
            results = importer.import_customers()
            self.assertEqual(len(results['errors']), 1)
            self.assertIn('CSV File', results['errors'][0][0])

    def test_import_duplicate_skip_mode(self):
        """Test that duplicates are skipped when replace_existing=False."""
        # Create existing customer
        Customer.objects.create(
            name="Duplicate Customer",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff
        )

        csv_content = self._read_fixture("duplicate_customers.csv")
        importer = CustomerCSVImporter(csv_content, replace_existing=False)
        results = importer.import_customers()

        self.assertEqual(len(results['created']), 0)
        self.assertEqual(len(results['updated']), 0)
        self.assertEqual(len(results['skipped']), 1)
        self.assertEqual(len(results['errors']), 0)

        skipped_name, reason = results['skipped'][0]
        self.assertEqual(skipped_name, "Duplicate Customer")
        self.assertIn('already exists', reason)

    def test_import_duplicate_replace_mode(self):
        """Test that duplicates are updated when replace_existing=True."""
        # Create existing customer with different timezone
        existing = Customer.objects.create(
            name="Duplicate Customer",
            timezone="America/New_York",
            current_tariff=self.tariff
        )

        csv_content = self._read_fixture("duplicate_customers.csv")
        importer = CustomerCSVImporter(csv_content, replace_existing=True)
        results = importer.import_customers()

        self.assertEqual(len(results['created']), 0)
        self.assertEqual(len(results['updated']), 1)
        self.assertEqual(len(results['skipped']), 0)
        self.assertEqual(len(results['errors']), 0)

        # Verify customer was updated
        updated_customer = Customer.objects.get(name="Duplicate Customer")
        self.assertEqual(str(updated_customer.timezone), "America/Los_Angeles")

    def test_import_partial_success(self):
        """Test that some rows can succeed while others fail."""
        csv_content = """name,timezone,utility_name,tariff_name
Customer Success,America/Los_Angeles,PG&E,B-19
Customer Fail,InvalidTimezone,PG&E,B-19
Customer Success 2,America/New_York,PG&E,B-19"""

        importer = CustomerCSVImporter(csv_content, replace_existing=False)
        results = importer.import_customers()

        self.assertEqual(len(results['created']), 2)
        self.assertEqual(len(results['errors']), 1)

        # Verify successful customers were created
        self.assertTrue(Customer.objects.filter(name="Customer Success").exists())
        self.assertTrue(Customer.objects.filter(name="Customer Success 2").exists())
        self.assertFalse(Customer.objects.filter(name="Customer Fail").exists())


class CustomerCSVRoundtripTests(TestCase):
    """Test that export then import preserves data."""

    def setUp(self):
        """Create test data."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

    def test_roundtrip_preserves_data(self):
        """Test that exporting then importing preserves all data."""
        # Create customers
        Customer.objects.create(
            name="Roundtrip A",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff
        )
        Customer.objects.create(
            name="Roundtrip B",
            timezone="America/New_York",
            current_tariff=self.tariff
        )

        # Export
        exporter = CustomerCSVExporter(Customer.objects.all())
        csv_str = exporter.export_to_csv()

        # Delete all customers
        Customer.objects.all().delete()
        self.assertEqual(Customer.objects.count(), 0)

        # Import
        importer = CustomerCSVImporter(csv_str, replace_existing=False)
        results = importer.import_customers()

        # Verify
        self.assertEqual(len(results['created']), 2)
        self.assertEqual(len(results['errors']), 0)

        customer_a = Customer.objects.get(name="Roundtrip A")
        self.assertEqual(str(customer_a.timezone), "America/Los_Angeles")
        self.assertEqual(customer_a.current_tariff, self.tariff)

        customer_b = Customer.objects.get(name="Roundtrip B")
        self.assertEqual(str(customer_b.timezone), "America/New_York")
        self.assertEqual(customer_b.current_tariff, self.tariff)
