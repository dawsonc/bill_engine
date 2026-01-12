"""
Tests for usage CSV import service.
"""

import datetime
from decimal import Decimal

from django.test import TestCase

from customers.models import Customer
from tariffs.models import CustomerCharge, Tariff
from usage.csv_service import UsageCSVImporter
from usage.models import CustomerUsage
from utilities.models import Utility


class UsageCSVImporterTests(TestCase):
    """Tests for UsageCSVImporter class."""

    def setUp(self):
        """Create test utility, tariff, and customer."""
        self.utility = Utility.objects.create(name="Test Utility")
        self.tariff = Tariff.objects.create(name="Test Tariff", utility=self.utility)
        CustomerCharge.objects.create(
            tariff=self.tariff, name="Base Charge", usd_per_month=Decimal("10.00")
        )
        self.customer = Customer.objects.create(
            name="Test Customer",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff,
            billing_interval_minutes=5,
        )

    def test_import_valid_usage(self):
        """Test importing valid usage data."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,kWh,63.0,kW,22.5,C
2024-01-15 14:35:00,2024-01-15 14:40:00,5.12,kWh,61.5,kW,22.3,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        # Check results
        self.assertEqual(len(results["created"]), 2)
        self.assertEqual(len(results["updated"]), 0)
        self.assertEqual(len(results["errors"]), 0)
        self.assertEqual(len(results["warnings"]), 0)

        # Verify data persisted correctly
        usage_count = CustomerUsage.objects.filter(customer=self.customer).count()
        self.assertEqual(usage_count, 2)

        # Check first record
        usage1 = CustomerUsage.objects.get(customer=self.customer, energy_kwh=Decimal("5.25"))
        self.assertEqual(usage1.peak_demand_kw, Decimal("63.0"))
        self.assertEqual(usage1.temperature_c, Decimal("22.5"))

    def test_import_with_utc_timestamps(self):
        """Test importing usage data with UTC timestamps."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15T22:30:00+00:00,2024-01-15T22:35:00+00:00,5.25,kWh,63.0,kW,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 1)
        self.assertEqual(len(results["errors"]), 0)

        # Verify timestamp is correct
        usage = CustomerUsage.objects.get(customer=self.customer)
        self.assertEqual(
            usage.interval_start_utc,
            datetime.datetime(2024, 1, 15, 22, 30, 0, tzinfo=datetime.timezone.utc),
        )

    def test_import_with_naive_timestamps(self):
        """Test importing usage data with naive timestamps (local time)."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,kWh,63.0,kW,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 1)
        self.assertEqual(len(results["errors"]), 0)

        # Verify timestamp converted from LA time to UTC (8 hour offset in winter)
        usage = CustomerUsage.objects.get(customer=self.customer)
        # 2024-01-15 14:30:00 in LA = 2024-01-15 22:30:00 UTC
        self.assertEqual(
            usage.interval_start_utc,
            datetime.datetime(2024, 1, 15, 22, 30, 0, tzinfo=datetime.timezone.utc),
        )

    def test_import_upsert_behavior(self):
        """Test that existing records are updated, not duplicated."""
        # Create existing usage record
        CustomerUsage.objects.create(
            customer=self.customer,
            interval_start_utc=datetime.datetime(2024, 1, 15, 22, 30, 0, tzinfo=datetime.timezone.utc),
            interval_end_utc=datetime.datetime(2024, 1, 15, 22, 35, 0, tzinfo=datetime.timezone.utc),
            energy_kwh=Decimal("10.00"),
            peak_demand_kw=Decimal("50.0"),
        )

        # Import CSV with overlapping interval (should update) and new interval (should create)
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,kWh,63.0,kW,22.5,C
2024-01-15 14:35:00,2024-01-15 14:40:00,5.12,kWh,61.5,kW,22.3,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        # Check results
        self.assertEqual(len(results["created"]), 1)  # One new interval
        self.assertEqual(len(results["updated"]), 1)  # One updated interval
        self.assertEqual(len(results["errors"]), 0)

        # Verify no duplicates
        usage_count = CustomerUsage.objects.filter(customer=self.customer).count()
        self.assertEqual(usage_count, 2)

        # Verify updated record has new values
        usage = CustomerUsage.objects.get(
            customer=self.customer,
            interval_start_utc=datetime.datetime(2024, 1, 15, 22, 30, 0, tzinfo=datetime.timezone.utc),
        )
        self.assertEqual(usage.energy_kwh, Decimal("5.25"))
        self.assertEqual(usage.peak_demand_kw, Decimal("63.0"))

    def test_unit_validation(self):
        """Test that invalid units trigger errors."""
        # Test invalid usage unit
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,MWh,63.0,kW,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("usage_unit", str(results["errors"][0][1]))

        # Test invalid demand unit
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,kWh,63000,W,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("peak_demand_unit", str(results["errors"][0][1]))

        # Test case insensitivity (should succeed)
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,KWH,63.0,KW,22.5,c"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 1)
        self.assertEqual(len(results["errors"]), 0)

    def test_low_kw_warning(self):
        """Test that low kW values trigger warnings but succeed."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,0.05,kWh,0.05,kW,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        # Should create record with warning
        self.assertEqual(len(results["created"]), 1)
        self.assertEqual(len(results["warnings"]), 1)
        self.assertEqual(len(results["errors"]), 0)

        # Check warning message
        self.assertIn("very low", results["warnings"][0][1])
        self.assertIn("0.05 kW", results["warnings"][0][1])

        # Verify record was created
        usage_count = CustomerUsage.objects.filter(customer=self.customer).count()
        self.assertEqual(usage_count, 1)

    def test_interval_duration_validation(self):
        """Test that wrong interval duration triggers validation error."""
        # Customer has 5-minute billing interval, but CSV has 10-minute interval
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:40:00,5.25,kWh,63.0,kW,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        # Error should mention interval duration mismatch
        error_str = str(results["errors"][0][1])
        self.assertTrue("interval" in error_str.lower() or "duration" in error_str.lower())

    def test_temperature_optional(self):
        """Test that empty temperature field is handled correctly."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,kWh,63.0,kW,,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 1)
        self.assertEqual(len(results["errors"]), 0)

        # Verify temperature is None
        usage = CustomerUsage.objects.get(customer=self.customer)
        self.assertIsNone(usage.temperature_c)

    def test_invalid_csv_syntax(self):
        """Test that malformed CSV returns error."""
        csv_content = """interval_start,interval_end,usage,usage_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,kWh,63.0"""  # Missing columns in header

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("CSV", results["errors"][0][0])

    def test_wrong_header(self):
        """Test that wrong header columns trigger schema error."""
        csv_content = """interval_start,interval_end,usage,usage_unit,demand,demand_unit,temp,temp_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,kWh,63.0,kW,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["errors"]), 1)
        error_str = str(results["errors"][0][1])
        self.assertIn("header", error_str.lower() or "column" in error_str.lower())

    def test_missing_required_fields(self):
        """Test that empty required fields trigger errors."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
,2024-01-15 14:35:00,5.25,kWh,63.0,kW,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("interval_start", str(results["errors"][0][1]))

    def test_invalid_timestamp_format(self):
        """Test that invalid timestamp format triggers error."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-13-45 14:30:00,2024-01-15 14:35:00,5.25,kWh,63.0,kW,22.5,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("timestamp", str(results["errors"][0][1]).lower())

    def test_partial_success(self):
        """Test that some rows succeed while others fail."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit
2024-01-15 14:30:00,2024-01-15 14:35:00,5.25,kWh,63.0,kW,22.5,C
2024-01-15 14:35:00,2024-01-15 14:40:00,5.12,MWh,61.5,kW,22.3,C
2024-01-15 14:40:00,2024-01-15 14:45:00,5.30,kWh,62.0,kW,22.1,C"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        # First and third rows should succeed, second should fail
        self.assertEqual(len(results["created"]), 2)
        self.assertEqual(len(results["errors"]), 1)

        # Verify successful rows were created
        usage_count = CustomerUsage.objects.filter(customer=self.customer).count()
        self.assertEqual(usage_count, 2)

    def test_empty_csv(self):
        """Test that empty CSV file returns appropriate error."""
        csv_content = ""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("empty", str(results["errors"][0][1]).lower())

    def test_csv_with_only_header(self):
        """Test CSV with only header row."""
        csv_content = """interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit"""

        importer = UsageCSVImporter(csv_content, customer=self.customer)
        results = importer.import_usage()

        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("No data", str(results["errors"][0][1]))
