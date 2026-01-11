"""
YAML import/export service for tariffs.

Provides bulk import and export functionality for tariffs with all charge types.
Validation matches web interface validation from issue #5.
"""

import datetime
from decimal import Decimal
from typing import Any

import yaml
from django.core.exceptions import ValidationError
from django.db import transaction

from tariffs.models import CustomerCharge, DemandCharge, EnergyCharge, Tariff
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
            "energy_charges", "demand_charges", "customer_charges", "utility"
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

        data = {"tariffs": [self._serialize_tariff(t) for t in self.tariffs]}
        return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

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
            "period_start_time_local": charge.period_start_time_local.strftime("%H:%M"),
            "period_end_time_local": charge.period_end_time_local.strftime("%H:%M"),
            "applies_start_date": charge.applies_start_date.isoformat()
            if charge.applies_start_date
            else None,
            "applies_end_date": charge.applies_end_date.isoformat()
            if charge.applies_end_date
            else None,
            "applies_weekdays": charge.applies_weekdays,
            "applies_weekends": charge.applies_weekends,
            "applies_holidays": charge.applies_holidays,
        }

    def _serialize_demand_charge(self, charge: DemandCharge) -> dict:
        """Convert demand charge instance to dictionary."""
        return {
            "name": charge.name,
            "rate_usd_per_kw": charge.rate_usd_per_kw,
            "period_start_time_local": charge.period_start_time_local.strftime("%H:%M"),
            "period_end_time_local": charge.period_end_time_local.strftime("%H:%M"),
            "peak_type": charge.peak_type,
            "applies_start_date": charge.applies_start_date.isoformat()
            if charge.applies_start_date
            else None,
            "applies_end_date": charge.applies_end_date.isoformat()
            if charge.applies_end_date
            else None,
            "applies_weekdays": charge.applies_weekdays,
            "applies_weekends": charge.applies_weekends,
            "applies_holidays": charge.applies_holidays,
        }

    def _serialize_customer_charge(self, charge: CustomerCharge) -> dict:
        """Convert customer charge instance to dictionary."""
        return {
            "name": charge.name,
            "usd_per_month": charge.usd_per_month,
        }


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
        charge = EnergyCharge(
            tariff=tariff,
            name=charge_data["name"],
            rate_usd_per_kwh=Decimal(str(charge_data["rate_usd_per_kwh"])),
            period_start_time_local=self._parse_time(charge_data["period_start_time_local"]),
            period_end_time_local=self._parse_time(charge_data["period_end_time_local"]),
            applies_start_date=self._parse_date(charge_data.get("applies_start_date")),
            applies_end_date=self._parse_date(charge_data.get("applies_end_date")),
            applies_weekdays=charge_data.get("applies_weekdays", True),
            applies_weekends=charge_data.get("applies_weekends", True),
            applies_holidays=charge_data.get("applies_holidays", True),
        )
        # Validate using model's clean() method (matches web interface validation)
        charge.full_clean()
        charge.save()

    def _create_demand_charge(self, tariff: Tariff, charge_data: dict):
        """Create and validate a demand charge."""
        charge = DemandCharge(
            tariff=tariff,
            name=charge_data["name"],
            rate_usd_per_kw=Decimal(str(charge_data["rate_usd_per_kw"])),
            period_start_time_local=self._parse_time(charge_data["period_start_time_local"]),
            period_end_time_local=self._parse_time(charge_data["period_end_time_local"]),
            peak_type=charge_data.get("peak_type", "monthly"),
            applies_start_date=self._parse_date(charge_data.get("applies_start_date")),
            applies_end_date=self._parse_date(charge_data.get("applies_end_date")),
            applies_weekdays=charge_data.get("applies_weekdays", True),
            applies_weekends=charge_data.get("applies_weekends", True),
            applies_holidays=charge_data.get("applies_holidays", True),
        )
        # Validate using model's clean() method (matches web interface validation)
        charge.full_clean()
        charge.save()

    def _create_customer_charge(self, tariff: Tariff, charge_data: dict):
        """Create and validate a customer charge."""
        charge = CustomerCharge(
            tariff=tariff,
            name=charge_data["name"],
            usd_per_month=Decimal(str(charge_data["usd_per_month"])),
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
        """Parse date string in YYYY-MM-DD format or return None."""
        if date_str is None or date_str == "":
            return None

        try:
            return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD or null")
