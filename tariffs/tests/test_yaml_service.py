"""
Unit tests for YAML import/export service.

Tests validation, error handling, and roundtrip functionality.
"""

import datetime
from decimal import Decimal
from pathlib import Path

from django.test import TestCase

from tariffs.models import ApplicabilityRule, CustomerCharge, DemandCharge, EnergyCharge, Tariff
from tariffs.yaml_service import TariffYAMLExporter, TariffYAMLImporter
from utilities.models import Utility


class TariffYAMLExporterTests(TestCase):
    """Test YAML export functionality."""

    def setUp(self):
        """Create test data for export."""
        self.utility = Utility.objects.create(name="PG&E")
        self.tariff = Tariff.objects.create(name="B-19", utility=self.utility)

        # Create applicability rule
        self.summer_peak_rule = ApplicabilityRule.objects.create(
            name="Summer Peak Hours",
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
            applies_start_date=datetime.date(2024, 6, 1),
            applies_end_date=datetime.date(2024, 9, 30),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        # Create energy charge and link rule
        energy_charge = EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Energy",
            rate_usd_per_kwh=Decimal("0.15432"),
        )
        energy_charge.applicability_rules.add(self.summer_peak_rule)

        # Create demand charge and link rule
        demand_charge = DemandCharge.objects.create(
            tariff=self.tariff,
            name="Summer Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            peak_type="monthly",
        )
        demand_charge.applicability_rules.add(self.summer_peak_rule)

        CustomerCharge.objects.create(
            tariff=self.tariff,
            name="Basic Service",
            amount_usd=Decimal("15.00"),
        )

    def test_export_tariff_structure(self):
        """Test that export produces correct YAML structure."""
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        self.assertIn("applicability_rules:", yaml_str)
        self.assertIn("tariffs:", yaml_str)
        self.assertIn("name: B-19", yaml_str)
        self.assertIn("utility: PG&E", yaml_str)
        self.assertIn("energy_charges:", yaml_str)
        self.assertIn("demand_charges:", yaml_str)
        self.assertIn("customer_charges:", yaml_str)

    def test_export_applicability_rules_section(self):
        """Test that applicability rules are exported in separate section."""
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        # Rule should be in top-level applicability_rules section
        self.assertIn("name: Summer Peak Hours", yaml_str)
        # Charges should reference rules by name
        self.assertIn("applicability_rules:", yaml_str)
        self.assertIn("- Summer Peak Hours", yaml_str)

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
        self.assertIn("amount_usd: 15.00", yaml_str)

    def test_export_null_dates(self):
        """Test that null dates are exported as null in rules."""
        # Create rule with null dates
        year_round_rule = ApplicabilityRule.objects.create(
            name="Year Round Rule",
            period_start_time_local=datetime.time(0, 0),
            period_end_time_local=datetime.time(23, 59),
            applies_start_date=None,
            applies_end_date=None,
        )

        # Create tariff with charge using this rule
        tariff2 = Tariff.objects.create(name="E-19", utility=self.utility)
        energy_charge = EnergyCharge.objects.create(
            tariff=tariff2,
            name="Year Round",
            rate_usd_per_kwh=Decimal("0.12345"),
        )
        energy_charge.applicability_rules.add(year_round_rule)

        exporter = TariffYAMLExporter(Tariff.objects.filter(name="E-19"))
        yaml_str = exporter.export_to_yaml()

        self.assertIn("applies_start_date: null", yaml_str)
        self.assertIn("applies_end_date: null", yaml_str)

    def test_export_shared_rules(self):
        """Test that shared rules are exported only once."""
        # Create another charge using the same rule
        energy_charge2 = EnergyCharge.objects.create(
            tariff=self.tariff,
            name="Another Peak Energy",
            rate_usd_per_kwh=Decimal("0.20000"),
        )
        energy_charge2.applicability_rules.add(self.summer_peak_rule)

        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        # Rule should appear only once in the rules section
        count = yaml_str.count("name: Summer Peak Hours")
        self.assertEqual(count, 1, "Shared rule should only appear once in export")


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

        # Check charge has linked applicability rule
        energy_charge = tariff1.energy_charges.filter(name="Summer Peak Energy").first()
        self.assertIsNotNone(energy_charge)
        self.assertEqual(energy_charge.rate_usd_per_kwh, Decimal("0.15432"))
        self.assertEqual(energy_charge.applicability_rules.count(), 1)

        # Check rule properties
        rule = energy_charge.applicability_rules.first()
        self.assertEqual(rule.name, "Summer Peak Hours")
        self.assertEqual(rule.period_start_time_local, datetime.time(12, 0))
        self.assertEqual(rule.applies_weekdays, True)
        self.assertEqual(rule.applies_weekends, False)

    def test_import_creates_applicability_rules(self):
        """Test that applicability rules are created from YAML."""
        yaml_content = (self.fixtures_dir / "valid_tariffs.yaml").read_text()
        importer = TariffYAMLImporter(yaml_content)
        importer.import_tariffs()

        # Check rules were created
        self.assertEqual(ApplicabilityRule.objects.count(), 3)
        self.assertTrue(ApplicabilityRule.objects.filter(name="Summer Peak Hours").exists())
        self.assertTrue(ApplicabilityRule.objects.filter(name="Summer Off-Peak Hours").exists())
        self.assertTrue(ApplicabilityRule.objects.filter(name="Year-Round All Hours").exists())

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

        # Error should occur when creating applicability rule
        self.assertEqual(len(results["errors"]), 1)
        # Should contain validation error about time ordering
        error_msg = results["errors"][0][1][0].lower()
        self.assertTrue(
            "period_end_time_local" in error_msg or "time" in error_msg,
            f"Expected time validation error, got: {error_msg}",
        )

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
            tariff=tariff, name="Old Charge", amount_usd=Decimal("10.00")
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

    def test_import_with_applicability_rules(self):
        """Test that charges with applicability rules are linked correctly."""
        yaml_content = """
applicability_rules:
  - name: "Peak Hours"
    period_start_time_local: "12:00"
    period_end_time_local: "18:30"
    applies_weekdays: true
    applies_weekends: false
    applies_holidays: false

tariffs:
  - name: "Test Tariff"
    utility: "PG&E"
    energy_charges:
      - name: "Peak"
        rate_usd_per_kwh: 0.15
        applicability_rules: ["Peak Hours"]
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 1)
        tariff = Tariff.objects.get(name="Test Tariff")
        charge = tariff.energy_charges.first()

        # Verify M2M relationship
        self.assertEqual(charge.applicability_rules.count(), 1)
        rule = charge.applicability_rules.first()
        self.assertEqual(rule.name, "Peak Hours")
        self.assertEqual(rule.period_start_time_local, datetime.time(12, 0))
        self.assertEqual(rule.period_end_time_local, datetime.time(18, 30))
        self.assertFalse(rule.applies_weekends)

    def test_import_unknown_rule_reference(self):
        """Test that referencing unknown rule name raises error."""
        yaml_content = """
tariffs:
  - name: "Test Tariff"
    utility: "PG&E"
    energy_charges:
      - name: "Peak"
        rate_usd_per_kwh: 0.15
        applicability_rules: ["NonExistent Rule"]
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 0)
        self.assertEqual(len(results["errors"]), 1)
        self.assertIn("Unknown applicability rule", results["errors"][0][1][0])

    def test_import_empty_applicability_rules(self):
        """Test that charges without applicability rules are allowed."""
        yaml_content = """
tariffs:
  - name: "Test Tariff"
    utility: "PG&E"
    energy_charges:
      - name: "Base Energy"
        rate_usd_per_kwh: 0.12
        applicability_rules: []
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        self.assertEqual(len(results["created"]), 1)
        charge = EnergyCharge.objects.first()
        self.assertEqual(charge.applicability_rules.count(), 0)

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
        """Test that transactions roll back on error for tariff with invalid rule ref."""
        yaml_content = """
applicability_rules:
  - name: "Valid Rule"
    period_start_time_local: "12:00"
    period_end_time_local: "18:00"

tariffs:
  - name: "Test Tariff"
    utility: "PG&E"
    energy_charges:
      - name: "Peak"
        rate_usd_per_kwh: 0.15
        applicability_rules: ["Invalid Rule"]
    demand_charges: []
    customer_charges: []
"""
        importer = TariffYAMLImporter(yaml_content)
        results = importer.import_tariffs()

        # Should have error and no tariffs created (tariff creation is per-tariff atomic)
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
        # Create applicability rule
        summer_peak_rule = ApplicabilityRule.objects.create(
            name="Summer Peak",
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
            applies_start_date=datetime.date(2024, 6, 1),
            applies_end_date=datetime.date(2024, 9, 30),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        # Create tariff with all charge types
        tariff = Tariff.objects.create(name="B-19", utility=self.utility)

        energy_charge = EnergyCharge.objects.create(
            tariff=tariff,
            name="Summer Peak",
            rate_usd_per_kwh=Decimal("0.15432"),
        )
        energy_charge.applicability_rules.add(summer_peak_rule)

        demand_charge = DemandCharge.objects.create(
            tariff=tariff,
            name="Peak Demand",
            rate_usd_per_kw=Decimal("18.50"),
            peak_type="monthly",
        )
        demand_charge.applicability_rules.add(summer_peak_rule)

        CustomerCharge.objects.create(
            tariff=tariff,
            name="Basic Service",
            amount_usd=Decimal("15.00"),
        )

        # Export
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        # Delete original data
        Tariff.objects.all().delete()
        ApplicabilityRule.objects.all().delete()

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

        # Check rule was recreated and linked
        self.assertEqual(energy.applicability_rules.count(), 1)
        rule = energy.applicability_rules.first()
        self.assertEqual(rule.period_start_time_local, datetime.time(12, 0))
        # Dates are normalized to year 2000 (only month/day matter)
        self.assertEqual(rule.applies_start_date, datetime.date(2000, 6, 1))
        self.assertFalse(rule.applies_weekends)

    def test_roundtrip_shared_rules(self):
        """Test that shared rules are properly handled in roundtrip."""
        # Create one rule shared by multiple charges
        shared_rule = ApplicabilityRule.objects.create(
            name="Shared Peak Rule",
            period_start_time_local=datetime.time(12, 0),
            period_end_time_local=datetime.time(18, 0),
            applies_weekdays=True,
            applies_weekends=False,
            applies_holidays=False,
        )

        tariff = Tariff.objects.create(name="Test Tariff", utility=self.utility)

        energy_charge = EnergyCharge.objects.create(
            tariff=tariff,
            name="Peak Energy",
            rate_usd_per_kwh=Decimal("0.15"),
        )
        energy_charge.applicability_rules.add(shared_rule)

        demand_charge = DemandCharge.objects.create(
            tariff=tariff,
            name="Peak Demand",
            rate_usd_per_kw=Decimal("20.00"),
            peak_type="monthly",
        )
        demand_charge.applicability_rules.add(shared_rule)

        # Export
        exporter = TariffYAMLExporter(Tariff.objects.all())
        yaml_str = exporter.export_to_yaml()

        # Delete original data
        Tariff.objects.all().delete()
        ApplicabilityRule.objects.all().delete()

        # Import
        importer = TariffYAMLImporter(yaml_str)
        results = importer.import_tariffs()

        self.assertEqual(len(results["errors"]), 0)

        # Verify only one rule was created
        self.assertEqual(ApplicabilityRule.objects.count(), 1)

        # Both charges should reference the same rule
        tariff = Tariff.objects.first()
        energy = tariff.energy_charges.first()
        demand = tariff.demand_charges.first()

        self.assertEqual(energy.applicability_rules.first().pk, demand.applicability_rules.first().pk)
