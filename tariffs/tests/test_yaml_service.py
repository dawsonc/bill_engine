"""
Unit tests for YAML import/export service.

Tests validation, error handling, and roundtrip functionality.
"""

import datetime
from decimal import Decimal
from pathlib import Path

from django.test import TestCase

from tariffs.models import CustomerCharge, DemandCharge, EnergyCharge, Tariff
from tariffs.yaml_service import TariffYAMLExporter, TariffYAMLImporter
from utilities.models import Utility


class TariffYAMLExporterTests(TestCase):
    """Test YAML export functionality."""

    def setUp(self):
        """Create test data for export."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

        # Create charges
        EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Energy",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
            applies_start_date=datetime.date(2024, 6, 1),
            applies_end_date=datetime.date(2024, 9, 30),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        DemandCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
            peak_type="monthly",
            applies_start_date=datetime.date(2024, 6, 1),
            applies_end_date=datetime.date(2024, 9, 30),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        CustomerCharge.objects.create(
            tariff=self.tariff,
            name="Basic Service",
            usd_per_month=Decimal("15.00"),
        )

    def test_export_tariff_structure(self):
        """Test that export produces correct YAML structure."""
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        self.assertIn("tariffs:", yaml_str)
        self.assertIn("name: B-19", yaml_str)
        self.assertIn("utility: PG&E", yaml_str)
        self.assertIn("energy_charges:", yaml_str)
        self.assertIn("demand_charges:", yaml_str)
        self.assertIn("customer_charges:", yaml_str)

    def test_export_time_format(self):
        """Test that times are exported in HH:MM format."""
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        self.assertIn("period_start_time_local: '12:00'", yaml_str)
        self.assertIn("period_end_time_local: '18:00'", yaml_str)

    def test_export_date_format(self):
        """Test that dates are exported in YYYY-MM-DD format with year 2000."""
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        # Dates are normalized to year 2000 (only month/day matter)
        self.assertIn("applies_start_date: '2000-06-01'", yaml_str)
        self.assertIn("applies_end_date: '2000-09-30'", yaml_str)

    def test_export_preserves_decimal_precision(self):
        """Test that decimal values preserve correct precision."""
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        # Energy rates should have 5 decimal places
        self.assertIn("rate_usd_per_kwh: 0.15432", yaml_str)
        # Demand/customer rates should have 2 decimal places (as originally specified)
        self.assertIn("rate_usd_per_kw: 18.50", yaml_str)
        self.assertIn("usd_per_month: 15.00", yaml_str)

    def test_export_null_dates(self):
        """Test that null dates are exported as null."""
        # Create tariff with null dates
        tariff2 = Tariff.objects.create(name="E-19", utility=self.utility)
        EnergyCharge.objects.create(
            tariff=tariff2,
            name="Year Round",
            rate_usd_per_kwh=Decimal("0.12345"),
            period_start_time_local=datetime.time(0, 0),
            period_end_time_local=datetime.time(23, 59),
            applies_start_date=None,
            applies_end_date=None,
        )

        exporter = TariffYAMLExporter(Tariff.objects.filter(name="E-19"))
        yaml_str = exporter.export_to_yaml()

        self.assertIn("applies_start_date: null", yaml_str)
        self.assertIn("applies_end_date: null", yaml_str)


class TariffYAMLImporterTests(TestCase):
    """Test YAML import functionality."""

    def setUp(self):
        """Create utility for import tests."""
        self.utility = Utility.objects.create(name="PG&E")
        self.fixtures_dir = Path(__file__).parent / "fixtures"

    def test_import_valid_tariffs(self):
        """Test importing valid YAML file."""
        yaml_content = (self.fixtures_dir / "valid_tariffs.yaml").read_text()
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 2)
        self.assertEqual(len(results["errors"]), 0)
        self.assertEqual(len(results["skipped"]), 0)

        # Check first tariff
        tariff1 = Tariff.objects.get(name="B-19 Secondary")
        self.assertEqual(tariff1.utility, self.utility)
        self.assertEqual(tariff1.energy_charges.count(), 2)
        self.assertEqual(tariff1.demand_charges.count(), 1)
        self.assertEqual(tariff1.customer_charges.count(), 2)

        # Check charge details
        energy_charge = tariff1.energy_charges.filter(name="Summer Peak Energy").first()
        self.assertIsNotNone(energy_charge)
        self.assertEqual(energy_charge.rate_usd_per_kwh, Decimal("0.15432"))
        self.assertEqual(energy_charge.period_start_time_local, datetime.time(12, 0))
        self.assertEqual(energy_charge.applies_weekdays, True)
        self.assertEqual(energy_charge.applies_weekends, False)

    def test_import_invalid_yaml_syntax(self):
        """Test that invalid YAML syntax is caught."""
        yaml_content = (self.fixtures_dir / "invalid_yaml.yaml").read_text()
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("YAML File", results["errors"][0][0])
        self.assertIn("Invalid YAML syntax", results["errors"][0][1][0])

    def test_import_missing_required_field(self):
        """Test that missing required fields are caught."""
        yaml_content = (self.fixtures_dir / "invalid_schema.yaml").read_text()
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("Missing required field: name", results["errors"][0][1][0])

    def test_import_validation_error(self):
        """Test that model validation errors are caught."""
        yaml_content = (self.fixtures_dir / "invalid_validation.yaml").read_text()
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        # Should contain validation error about time ordering
        error_msg = results["errors"][0][1][0]
        self.assertIn("period_end_time_local", error_msg.lower())

    def test_import_utility_not_found(self):
        """Test that missing utility is caught."""
        yaml_content = """
tariffs:
  - name: "Test Tariff"
    utility: "NonExistent Utility"
    energy_charges: []
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("Utility 'NonExistent Utility' not found", results["errors"][0][1][0])

    def test_import_duplicate_skip_mode(self):
        """Test skipping duplicate tariffs when replace_existing=False."""
        # Create existing tariff
        Tariff.objects.create(name="B-19", utility=self.utility)

        yaml_content = (self.fixtures_dir / "duplicate_tariffs.yaml").read_text()
        importer = TariffYAMLImporter(yaml_content, replace_existing=False)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["skipped"]), 1)
        self.assertIn("B-19", results["skipped"][0][0])

    def test_import_duplicate_replace_mode(self):
        """Test replacing duplicate tariffs when replace_existing=True."""
        # Create existing tariff with different charges
        tariff = Tariff.objects.create(name="B-19", utility=self.utility)
        CustomerCharge.objects.create(
            tariff=tariff, name="Old Charge", usd_per_month=Decimal("10.00")
        )

        yaml_content = (self.fixtures_dir / "duplicate_tariffs.yaml").read_text()
        importer = TariffYAMLImporter(yaml_content, replace_existing=True)
        results = importer.import_tariffs()

        self.assertEqual(len(results["updated"]), 1)
        self.assertEqual(len(results["skipped"]), 0)

        # Check that old charges were replaced
        tariff.refresh_from_db()
        self.assertEqual(tariff.customer_charges.count(), 1)
        self.assertEqual(tariff.customer_charges.first().name, "Customer Charge")

    def test_import_time_format_hh_mm(self):
        """Test that HH:MM time format is parsed correctly."""
        yaml_content = """
tariffs:
  - name: "Test Tariff"
    utility: "PG&E"
    energy_charges:
      - name: "Peak"
        rate_usd_per_kwh: 0.15
        period_start_time_local: "12:00"
        period_end_time_local: "18:30"
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 1)
        tariff = Tariff.objects.get(name="Test Tariff")
        charge = tariff.energy_charges.first()
        self.assertEqual(charge.period_start_time_local, datetime.time(12, 0))
        self.assertEqual(charge.period_end_time_local, datetime.time(18, 30))

    def test_import_boolean_defaults(self):
        """Test that boolean fields default to True when omitted."""
        yaml_content = """
tariffs:
  - name: "Test Tariff"
    utility: "PG&E"
    energy_charges:
      - name: "Peak"
        rate_usd_per_kwh: 0.15
        period_start_time_local: "12:00"
        period_end_time_local: "18:00"
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 1)
        charge = EnergyCharge.objects.first()
        self.assertTrue(charge.applies_weekdays)
        self.assertTrue(charge.applies_weekends)
        self.assertTrue(charge.applies_holidays)

    def test_import_empty_charge_arrays(self):
        """Test that empty charge arrays are allowed."""
        yaml_content = """
tariffs:
  - name: "Test Tariff"
    utility: "PG&E"
    energy_charges: []
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 1)
        tariff = Tariff.objects.get(name="Test Tariff")
        self.assertEqual(tariff.energy_charges.count(), 0)
        self.assertEqual(tariff.demand_charges.count(), 0)
        self.assertEqual(tariff.customer_charges.count(), 0)

    def test_import_transaction_rollback(self):
        """Test that transactions roll back on error."""
        yaml_content = """
tariffs:
  - name: "Test Tariff"
    utility: "PG&E"
    energy_charges:
      - name: "Peak"
        rate_usd_per_kwh: 0.15
        period_start_time_local: "18:00"
        period_end_time_local: "12:00"
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        # Should have error and no tariffs created
        self.assertEqual(len(results["errors"]), 1)
        self.assertEqual(Tariff.objects.count(), 0)
        self.assertEqual(EnergyCharge.objects.count(), 0)


class TariffYAMLRoundtripTests(TestCase):
    """Test export then import roundtrip."""

    def setUp(self):
        """Create test data."""
        self.utility = Utility.objects.create(name="PG&E")

    def test_roundtrip_preserves_data(self):
        """Test that exporting then importing preserves all data."""
        # Create tariff with all charge types
        tariff = Tariff.objects.create(name="B-19", utility=self.utility)

        EnergyCharge.objects.create(
            tariff=tariff,
            name="Summer Peak",
            rate_usd_per_kwh=Decimal("0.15432"),
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
            applies_start_date=datetime.date(2024, 6, 1),
            applies_end_date=datetime.date(2024, 9, 30),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        DemandCharge.objects.create(
            tariff=tariff,
            name="Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
            peak_type="monthly",
            applies_start_date=datetime.date(2024, 6, 1),
            applies_end_date=datetime.date(2024, 9, 30),
        )

        CustomerCharge.objects.create(
            tariff=tariff,
            name="Basic Service",
            usd_per_month=Decimal("15.00"),
        )

        # Export
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        # Delete original data
        Tariff.objects.all().delete()

        # Import
        importer = TariffYAMLImporter(yaml_str)
        results = importer.import_tariffs()

        # Verify
        self.assertEqual(len(results["created"]), 1)
        self.assertEqual(len(results["errors"]), 0)

        # Check recreated tariff
        tariff = Tariff.objects.get(name="B-19")
        self.assertEqual(tariff.energy_charges.count(), 1)
        self.assertEqual(tariff.demand_charges.count(), 1)
        self.assertEqual(tariff.customer_charges.count(), 1)

        # Check energy charge details
        energy = tariff.energy_charges.first()
        self.assertEqual(energy.name, "Summer Peak")
        self.assertEqual(energy.rate_usd_per_kwh, Decimal("0.15432"))
        self.assertEqual(energy.period_start_time_local, datetime.time(12, 0))
        # Dates are normalized to year 2000 (only month/day matter)
        self.assertEqual(energy.applies_start_date, datetime.date(2000, 6, 1))
        self.assertFalse(energy.applies_weekends)
