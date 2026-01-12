"""
CSV import service for customer usage data.

Provides UsageCSVImporter class for handling bulk usage uploads via CSV format.
"""

import csv
import io
import zoneinfo
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction

from customers.models import Customer
from usage.models import CustomerUsage


class UsageCSVImporter:
    """Import customer usage data from CSV format with validation."""

    def __init__(self, csv_content: str, customer: Customer):
        """
        Initialize importer with CSV content and customer.

        Args:
            csv_content: CSV string to parse and import
            customer: Customer object for this usage data
        """
        self.csv_content = csv_content
        self.customer = customer
        self.customer_timezone = zoneinfo.ZoneInfo(str(customer.timezone))
        self.results = {
            "created": [],  # [usage_obj, ...]
            "updated": [],  # [usage_obj, ...]
            "warnings": [],  # [(row_identifier, warning_message), ...]
            "errors": [],  # [(row_identifier, [error_messages]), ...]
        }

    def import_usage(self) -> dict:
        """
        Parse and import usage data from CSV.

        Returns:
            Dictionary with results structure containing created, updated, warnings, and errors
        """
        try:
            rows = self._parse_csv()
        except Exception as e:
            self.results["errors"].append(("CSV File", [str(e)]))
            return self.results

        if not rows:
            self.results["errors"].append(("CSV File", ["No data rows found in CSV file"]))
            return self.results

        # Import each usage record in its own transaction
        for row_num, row_data in enumerate(rows, start=2):  # Start at 2 (header is row 1)
            self._import_single_usage(row_data, row_num)

        return self.results

    def _parse_csv(self) -> list[dict]:
        """
        Parse CSV content with error handling.

        Returns:
            List of dictionaries representing CSV rows

        Raises:
            ValueError: If CSV syntax is invalid or schema is wrong
        """
        try:
            reader = csv.DictReader(io.StringIO(self.csv_content))

            # Validate header
            self._validate_schema(reader)

            # Convert to list to catch any parsing errors
            rows = list(reader)
            return rows

        except csv.Error as e:
            raise ValueError(f"Invalid CSV syntax: {str(e)}")

    def _validate_schema(self, reader: csv.DictReader):
        """
        Validate CSV header structure.

        Args:
            reader: CSV DictReader instance

        Raises:
            ValueError: If header is missing or incorrect
        """
        expected_columns = {
            "interval_start",
            "interval_end",
            "usage",
            "usage_unit",
            "peak_demand",
            "peak_demand_unit",
            "temperature",
            "temperature_unit",
        }

        if reader.fieldnames is None:
            raise ValueError("CSV file is empty or has no header row")

        actual_columns = set(reader.fieldnames)

        if actual_columns != expected_columns:
            missing = expected_columns - actual_columns
            extra = actual_columns - expected_columns

            error_parts = []
            if missing:
                error_parts.append(f"Missing columns: {', '.join(sorted(missing))}")
            if extra:
                error_parts.append(f"Unexpected columns: {', '.join(sorted(extra))}")

            raise ValueError(
                f"Invalid CSV header. Expected columns: interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit,temperature,temperature_unit. "
                f"{'; '.join(error_parts)}"
            )

    def _import_single_usage(self, row_data: dict, row_num: int):
        """
        Import a single usage record atomically.

        Args:
            row_data: Dictionary of CSV row data
            row_num: Row number for error reporting (1-indexed)
        """
        interval_start = row_data.get("interval_start", "").strip()
        row_identifier = f"Row {row_num}" + (f": {interval_start}" if interval_start else "")

        try:
            # Validate required fields
            errors = []
            required_fields = [
                "interval_start",
                "interval_end",
                "usage",
                "usage_unit",
                "peak_demand",
                "peak_demand_unit",
            ]
            for field in required_fields:
                if not row_data.get(field, "").strip():
                    errors.append(f"Missing required field '{field}'")

            if errors:
                self.results["errors"].append((row_identifier, errors))
                return

            # Parse timestamps
            try:
                interval_start_utc = self._parse_timestamp(
                    row_data["interval_start"].strip(), self.customer_timezone
                )
                interval_end_utc = self._parse_timestamp(
                    row_data["interval_end"].strip(), self.customer_timezone
                )
            except ValueError as e:
                self.results["errors"].append((row_identifier, [f"Invalid timestamp: {str(e)}"]))
                return

            # Validate units
            unit_errors = self._validate_units(row_data)
            if unit_errors:
                self.results["errors"].append((row_identifier, unit_errors))
                return

            # Parse numeric values
            try:
                energy_kwh = Decimal(row_data["usage"].strip())
                peak_demand_kw = Decimal(row_data["peak_demand"].strip())
            except (InvalidOperation, ValueError) as e:
                self.results["errors"].append(
                    (row_identifier, [f"Invalid numeric value: {str(e)}"])
                )
                return

            # Parse temperature (optional)
            temperature_c = None
            temp_value = row_data.get("temperature", "").strip()
            if temp_value:
                try:
                    temperature_c = Decimal(temp_value)
                except (InvalidOperation, ValueError):
                    self.results["errors"].append(
                        (row_identifier, [f"Invalid temperature value: {temp_value}"])
                    )
                    return

            # Check for warnings
            warning = self._check_demand_warning(peak_demand_kw)
            if warning:
                self.results["warnings"].append((row_identifier, warning))

            # Import usage record in atomic transaction
            with transaction.atomic():
                usage, created = CustomerUsage.objects.update_or_create(
                    customer=self.customer,
                    interval_start_utc=interval_start_utc,
                    defaults={
                        "interval_end_utc": interval_end_utc,
                        "energy_kwh": energy_kwh,
                        "peak_demand_kw": peak_demand_kw,
                        "temperature_c": temperature_c,
                    },
                )
                # Validate model constraints (interval duration)
                usage.full_clean()

                if created:
                    self.results["created"].append(usage)
                else:
                    self.results["updated"].append(usage)

        except ValidationError as e:
            # Extract validation error messages
            error_messages = []
            if hasattr(e, "message_dict"):
                for field, messages in e.message_dict.items():
                    for message in messages:
                        error_messages.append(f"{field}: {message}")
            elif hasattr(e, "messages"):
                error_messages.extend(e.messages)
            else:
                error_messages.append(str(e))

            self.results["errors"].append((row_identifier, error_messages))

        except Exception as e:
            # Catch any unexpected errors
            self.results["errors"].append((row_identifier, [str(e)]))

    def _parse_timestamp(self, timestamp_str: str, customer_timezone: zoneinfo.ZoneInfo) -> datetime:
        """
        Parse timestamp, auto-detect if naive or aware, convert to UTC.

        Args:
            timestamp_str: Timestamp string to parse
            customer_timezone: Customer's timezone for localizing naive timestamps

        Returns:
            Timezone-aware datetime in UTC

        Raises:
            ValueError: If timestamp cannot be parsed
        """
        try:
            # Try parsing with fromisoformat (handles most formats)
            dt = datetime.fromisoformat(timestamp_str)
        except ValueError:
            # Try parsing with common formats
            for fmt in [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ]:
                try:
                    dt = datetime.strptime(timestamp_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(
                    f"Unable to parse timestamp '{timestamp_str}'. "
                    f"Expected formats: YYYY-MM-DD HH:MM:SS or ISO 8601"
                )

        # Check if naive or aware
        if dt.tzinfo is None:
            # Naive: localize to customer timezone, then convert to UTC
            local_dt = dt.replace(tzinfo=customer_timezone)
            utc_dt = local_dt.astimezone(timezone.utc)
        else:
            # Aware: convert directly to UTC
            utc_dt = dt.astimezone(timezone.utc)

        return utc_dt

    def _validate_units(self, row_data: dict) -> list[str]:
        """
        Validate unit values.

        Args:
            row_data: Dictionary of CSV row data

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Define allowed units (normalized)
        allowed_units = {
            "usage_unit": ["kwh"],
            "peak_demand_unit": ["kw"],
            "temperature_unit": ["c", "celsius", "°c"],
        }

        for unit_field, allowed in allowed_units.items():
            # Skip validation for temperature if empty (it's optional)
            if unit_field == "temperature_unit":
                temp_value = row_data.get("temperature", "").strip()
                if not temp_value:
                    continue

            unit_value = row_data.get(unit_field, "").strip().lower()
            if not unit_value:
                errors.append(f"Missing required field '{unit_field}'")
            elif unit_value not in allowed:
                if unit_field == "usage_unit":
                    errors.append(
                        f"Invalid {unit_field}: '{row_data.get(unit_field, '')}'. Must be 'kWh' (case-insensitive)"
                    )
                elif unit_field == "peak_demand_unit":
                    errors.append(
                        f"Invalid {unit_field}: '{row_data.get(unit_field, '')}'. Must be 'kW' (case-insensitive)"
                    )
                elif unit_field == "temperature_unit":
                    errors.append(
                        f"Invalid {unit_field}: '{row_data.get(unit_field, '')}'. Must be 'C' or 'Celsius' (case-insensitive)"
                    )

        return errors

    def _check_demand_warning(self, peak_demand_kw: Decimal) -> Optional[str]:
        """
        Check if peak demand is suspiciously low.

        Args:
            peak_demand_kw: Peak demand value in kW

        Returns:
            Warning message if value is suspicious, None otherwise
        """
        if peak_demand_kw < Decimal("0.1"):
            return (
                f"Peak demand ({peak_demand_kw} kW) is very low. "
                f"Verify units are correct (not W instead of kW)."
            )
        return None
