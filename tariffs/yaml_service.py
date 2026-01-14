"""
YAML import/export service for tariffs.

Provides bulk import and export functionality for tariffs with all charge types.
Validation matches web interface validation.

YAML Format:
    applicability_rules:
      - name: "Summer Peak Hours"
        period_start_time_local: "12:00"
        period_end_time_local: "18:00"
        applies_start_date: "2000-06-01"
        applies_end_date: "2000-09-30"
        applies_weekdays: true
        applies_weekends: false
        applies_holidays: false

    tariffs:
      - name: "B-19 Secondary"
        utility: "PG&E"
        energy_charges:
          - name: "Summer Peak Energy"
            rate_usd_per_kwh: 0.15432
            applicability_rules: ["Summer Peak Hours"]
        demand_charges:
          - name: "Peak Demand"
            rate_usd_per_kw: 25.00
            peak_type: "monthly"
            applicability_rules: ["Summer Peak Hours"]
        customer_charges:
          - name: "Customer Charge"
            amount_usd: 25.00
            charge_type: "monthly"
"""

import datetime
from decimal import Decimal
from typing import Any

import yaml
from django.core.exceptions import ValidationError
from django.db import transaction

from tariffs.models import ApplicabilityRule, CustomerCharge, DemandCharge, EnergyCharge, Tariff
from utilities.models import Utility


class TariffYAMLExporter:
    """Export tariffs to YAML format."""

    def __init__(self, tariffs_queryset):
        """
        Initialize exporter with tariffs queryset.

        Args:
            tariffs_queryset: Django queryset of Tariff objects to export
        """
        self.tariffs = tariffs_queryset.prefetch_related(
            "energy_charges__applicability_rules",
            "demand_charges__applicability_rules",
            "customer_charges",
            "utility",
        )

    def export_to_yaml(self) -> str:
        """
        Export tariffs to YAML string.

        Returns:
            YAML string representation of tariffs
        """

        # Add custom representer for Decimal to preserve precision
        def decimal_representer(dumper, value):
            return dumper.represent_scalar("tag:yaml.org,2002:float", str(value))

        yaml.add_representer(Decimal, decimal_representer)

        # Collect all unique rules used by any charge
        all_rules: set[ApplicabilityRule] = set()
        for tariff in self.tariffs:
            for charge in tariff.energy_charges.all():
                all_rules.update(charge.applicability_rules.all())
            for charge in tariff.demand_charges.all():
                all_rules.update(charge.applicability_rules.all())

        data = {
            "applicability_rules": [
                self._serialize_applicability_rule(rule)
                for rule in sorted(all_rules, key=lambda r: r.name)
            ],
            "tariffs": [self._serialize_tariff(t) for t in self.tariffs],
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def _serialize_applicability_rule(self, rule: ApplicabilityRule) -> dict:
        """Convert applicability rule instance to dictionary."""
        result = {"name": rule.name}

        if rule.period_start_time_local:
            result["period_start_time_local"] = rule.period_start_time_local.strftime("%H:%M")
        if rule.period_end_time_local:
            result["period_end_time_local"] = rule.period_end_time_local.strftime("%H:%M")

        # Always include date fields (null means year-round)
        result["applies_start_date"] = self._normalize_date_to_year_2000(rule.applies_start_date)
        result["applies_end_date"] = self._normalize_date_to_year_2000(rule.applies_end_date)

        result["applies_weekdays"] = rule.applies_weekdays
        result["applies_weekends"] = rule.applies_weekends
        result["applies_holidays"] = rule.applies_holidays

        return result

    def _serialize_tariff(self, tariff: Tariff) -> dict:
        """Convert tariff instance to dictionary."""
        return {
            "name": tariff.name,
            "utility": tariff.utility.name,
            "energy_charges": [
                self._serialize_energy_charge(c) for c in tariff.energy_charges.all()
            ],
            "demand_charges": [
                self._serialize_demand_charge(c) for c in tariff.demand_charges.all()
            ],
            "customer_charges": [
                self._serialize_customer_charge(c) for c in tariff.customer_charges.all()
            ],
        }

    def _serialize_energy_charge(self, charge: EnergyCharge) -> dict:
        """Convert energy charge instance to dictionary."""
        return {
            "name": charge.name,
            "rate_usd_per_kwh": charge.rate_usd_per_kwh,
            "applicability_rules": [rule.name for rule in charge.applicability_rules.all()],
        }

    def _serialize_demand_charge(self, charge: DemandCharge) -> dict:
        """Convert demand charge instance to dictionary."""
        return {
            "name": charge.name,
            "rate_usd_per_kw": charge.rate_usd_per_kw,
            "peak_type": charge.peak_type,
            "applicability_rules": [rule.name for rule in charge.applicability_rules.all()],
        }

    def _serialize_customer_charge(self, charge: CustomerCharge) -> dict:
        """Convert customer charge instance to dictionary."""
        return {
            "name": charge.name,
            "amount_usd": charge.amount_usd,
            "charge_type": charge.charge_type,
        }

    def _normalize_date_to_year_2000(self, d: datetime.date | None) -> str | None:
        """Normalize date to year 2000 for export (only month/day matter)."""
        if d is None:
            return None
        return datetime.date(2000, d.month, d.day).isoformat()


class TariffYAMLImporter:
    """Import tariffs from YAML format with validation."""

    def __init__(self, yaml_content: str, replace_existing: bool = False):
        """
        Initialize importer with YAML content.

        Args:
            yaml_content: YAML string to parse and import
            replace_existing: If True, replace existing tariffs with same utility+name.
                            If False, skip existing tariffs.
        """
        self.yaml_content = yaml_content
        self.replace_existing = replace_existing
        self.results = {
            "created": [],  # [(tariff, charge_counts), ...]
            "updated": [],  # [(tariff, charge_counts), ...]
            "skipped": [],  # [(tariff_name, reason), ...]
            "errors": [],  # [(tariff_name, error_messages), ...]
        }
        self._rules_by_name: dict[str, ApplicabilityRule] = {}

    def import_tariffs(self) -> dict:
        """
        Parse and import tariffs from YAML.

        Returns:
            Dictionary with results:
            {
                'created': [(tariff, charge_counts), ...],
                'updated': [(tariff, charge_counts), ...],
                'skipped': [(tariff_name, reason), ...],
                'errors': [(tariff_name, error_messages), ...]
            }
        """
        try:
            data = self._parse_yaml()
            self._validate_schema(data)
        except Exception as e:
            # Parse or schema errors affect entire file
            self.results["errors"].append(("YAML File", [str(e)]))
            return self.results

        # First pass: create all applicability rules
        try:
            self._import_applicability_rules(data.get("applicability_rules", []))
        except Exception as e:
            self.results["errors"].append(("Applicability Rules", [str(e)]))
            return self.results

        # Import each tariff in its own transaction
        for tariff_data in data["tariffs"]:
            try:
                self._import_single_tariff(tariff_data)
            except Exception as e:
                # Unexpected errors during import
                tariff_name = tariff_data.get("name", "Unknown")
                self.results["errors"].append((tariff_name, [f"Unexpected error: {str(e)}"]))

        return self.results

    def _parse_yaml(self) -> dict:
        """Parse YAML content with error handling."""
        try:
            data = yaml.safe_load(self.yaml_content)
            if data is None:
                raise ValueError("Empty YAML file")
            return data
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML syntax: {str(e)}")

    def _validate_schema(self, data: dict):
        """Validate top-level YAML structure."""
        if not isinstance(data, dict):
            raise ValueError("YAML must contain a dictionary at top level")

        if "tariffs" not in data:
            raise ValueError("Missing required top-level key: tariffs")

        if not isinstance(data["tariffs"], list):
            raise ValueError("tariffs must be a list")

        if len(data["tariffs"]) == 0:
            raise ValueError("tariffs list cannot be empty")

        # Validate applicability_rules if present
        if "applicability_rules" in data and not isinstance(data["applicability_rules"], list):
            raise ValueError("applicability_rules must be a list")

    def _import_applicability_rules(self, rules_data: list[dict]):
        """Import all applicability rules and store by name for reference."""
        for rule_data in rules_data:
            rule = self._create_applicability_rule(rule_data)
            self._rules_by_name[rule.name] = rule

    def _create_applicability_rule(self, rule_data: dict) -> ApplicabilityRule:
        """Create and validate an applicability rule."""
        if "name" not in rule_data:
            raise ValueError("Applicability rule missing required field: name")

        rule = ApplicabilityRule(
            name=rule_data["name"],
            period_start_time_local=self._parse_time(
                rule_data.get("period_start_time_local")
            ) if rule_data.get("period_start_time_local") else None,
            period_end_time_local=self._parse_time(
                rule_data.get("period_end_time_local")
            ) if rule_data.get("period_end_time_local") else None,
            applies_start_date=self._parse_date(rule_data.get("applies_start_date")),
            applies_end_date=self._parse_date(rule_data.get("applies_end_date")),
            applies_weekdays=rule_data.get("applies_weekdays", True),
            applies_weekends=rule_data.get("applies_weekends", True),
            applies_holidays=rule_data.get("applies_holidays", True),
        )
        rule.full_clean()
        rule.save()
        return rule

    def _import_single_tariff(self, tariff_data: dict):
        """Import a single tariff atomically."""
        tariff_name = tariff_data.get("name", "Unknown")

        # Validate required fields
        errors = []
        if "name" not in tariff_data:
            errors.append("Missing required field: name")
        if "utility" not in tariff_data:
            errors.append("Missing required field: utility")

        if errors:
            self.results["errors"].append((tariff_name, errors))
            return

        # Look up utility
        try:
            utility = Utility.objects.get(name=tariff_data["utility"])
        except Utility.DoesNotExist:
            self.results["errors"].append(
                (tariff_name, [f"Utility '{tariff_data['utility']}' not found"])
            )
            return

        # Check for existing tariff
        existing_tariff = Tariff.objects.filter(utility=utility, name=tariff_name).first()

        if existing_tariff and not self.replace_existing:
            # Skip duplicate
            self.results["skipped"].append(
                (tariff_name, f"Tariff already exists for {utility.name}")
            )
            return

        # Import in transaction (per-tariff atomicity)
        try:
            with transaction.atomic():
                if existing_tariff:
                    # Delete existing charges (CASCADE will handle this)
                    existing_tariff.energy_charges.all().delete()
                    existing_tariff.demand_charges.all().delete()
                    existing_tariff.customer_charges.all().delete()
                    tariff = existing_tariff
                    action = "updated"
                else:
                    # Create new tariff
                    tariff = Tariff.objects.create(name=tariff_name, utility=utility)
                    action = "created"

                # Import charges
                charge_counts = self._import_charges(tariff, tariff_data)

                # Add to results
                if action == "created":
                    self.results["created"].append((tariff, charge_counts))
                else:
                    self.results["updated"].append((tariff, charge_counts))

        except ValidationError as e:
            # Validation errors from model.clean()
            error_messages = []
            if hasattr(e, "error_dict"):
                for field, errors in e.error_dict.items():
                    for error in errors:
                        error_messages.append(f"{field}: {error.message}")
            else:
                error_messages = [str(e)]
            self.results["errors"].append((tariff_name, error_messages))

    def _import_charges(self, tariff: Tariff, tariff_data: dict) -> dict:
        """
        Import all charges for a tariff.

        Returns:
            Dictionary with charge counts: {'energy': N, 'demand': N, 'customer': N}
        """
        counts = {"energy": 0, "demand": 0, "customer": 0}

        # Energy charges
        for charge_data in tariff_data.get("energy_charges", []):
            self._create_energy_charge(tariff, charge_data)
            counts["energy"] += 1

        # Demand charges
        for charge_data in tariff_data.get("demand_charges", []):
            self._create_demand_charge(tariff, charge_data)
            counts["demand"] += 1

        # Customer charges
        for charge_data in tariff_data.get("customer_charges", []):
            self._create_customer_charge(tariff, charge_data)
            counts["customer"] += 1

        return counts

    def _create_energy_charge(self, tariff: Tariff, charge_data: dict):
        """Create and validate an energy charge."""
        # Get applicability rule names (if any)
        rule_names = charge_data.get("applicability_rules", [])

        # Validate rule references
        for rule_name in rule_names:
            if rule_name not in self._rules_by_name:
                raise ValidationError(f"Unknown applicability rule: '{rule_name}'")

        charge = EnergyCharge(
            tariff=tariff,
            name=charge_data["name"],
            rate_usd_per_kwh=Decimal(str(charge_data["rate_usd_per_kwh"])),
        )
        charge.full_clean()
        charge.save()

        # Link applicability rules via M2M
        for rule_name in rule_names:
            charge.applicability_rules.add(self._rules_by_name[rule_name])

    def _create_demand_charge(self, tariff: Tariff, charge_data: dict):
        """Create and validate a demand charge."""
        # Get applicability rule names (if any)
        rule_names = charge_data.get("applicability_rules", [])

        # Validate rule references
        for rule_name in rule_names:
            if rule_name not in self._rules_by_name:
                raise ValidationError(f"Unknown applicability rule: '{rule_name}'")

        charge = DemandCharge(
            tariff=tariff,
            name=charge_data["name"],
            rate_usd_per_kw=Decimal(str(charge_data["rate_usd_per_kw"])),
            peak_type=charge_data.get("peak_type", "monthly"),
        )
        charge.full_clean()
        charge.save()

        # Link applicability rules via M2M
        for rule_name in rule_names:
            charge.applicability_rules.add(self._rules_by_name[rule_name])

    def _create_customer_charge(self, tariff: Tariff, charge_data: dict):
        """Create and validate a customer charge."""
        charge = CustomerCharge(
            tariff=tariff,
            name=charge_data["name"],
            amount_usd=Decimal(str(charge_data["amount_usd"])),
            charge_type=charge_data.get("charge_type", "monthly"),
        )
        # Validate using model's clean() method
        charge.full_clean()
        charge.save()

    def _parse_time(self, time_str: str) -> datetime.time:
        """Parse time string in HH:MM or HH:MM:SS format."""
        if not time_str:
            raise ValueError("Time field cannot be empty")

        # Try HH:MM format first
        try:
            return datetime.datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            pass

        # Try HH:MM:SS format
        try:
            return datetime.datetime.strptime(time_str, "%H:%M:%S").time()
        except ValueError:
            raise ValueError(f"Invalid time format: '{time_str}'. Expected HH:MM or HH:MM:SS")

    def _parse_date(self, date_str: Any) -> datetime.date | None:
        """Parse date string in YYYY-MM-DD format and normalize to year 2000."""
        if date_str is None or date_str == "":
            return None

        try:
            parsed = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            # Normalize to year 2000 (only month/day matter)
            return datetime.date(2000, parsed.month, parsed.day)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD or null")
