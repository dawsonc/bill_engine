"""
CSV import service for customer usage data.

Provides UsageCSVImporter class for handling bulk usage uploads via CSV format.
"""

import io
import zoneinfo
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd
from dateutil import parser as dateutil_parser
from django.core.exceptions import ValidationError

from customers.models import Customer
from usage.models import CustomerUsage


class UsageCSVImporter:
    """Import customer usage data from CSV format with validation."""

    # Batch size for bulk operations (SQLite has ~999 variable limit)
    BATCH_SIZE = 500

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
        Parse and import usage data from CSV using bulk operations.

        Returns:
            Dictionary with results structure containing created, updated, warnings, and errors
        """
        try:
            df = self._parse_csv()
        except Exception as e:
            self.results["errors"].append(("CSV File", [str(e)]))
            return self.results

        if df.empty:
            self.results["errors"].append(("CSV File", ["No data rows found in CSV file"]))
            return self.results

        # Validate and transform each row, collecting valid records
        valid_records = []
        for idx, row in df.iterrows():
            row_num = idx + 2  # 1-indexed, skip header
            result = self._validate_and_transform_row(row, row_num)
            if result is not None:
                valid_records.append(result)

        if not valid_records:
            return self.results

        # Fetch existing records in one query
        interval_starts = [r["interval_start_utc"] for r in valid_records]
        existing = self._get_existing_records(interval_starts)

        # Split into create/update lists
        to_create, to_update = self._split_records(valid_records, existing)

        # Bulk create and update
        self._bulk_create(to_create)
        self._bulk_update(to_update, existing)

        return self.results

    def _parse_csv(self) -> pd.DataFrame:
        """
        Parse CSV content with pandas.

        Returns:
            DataFrame containing CSV data

        Raises:
            ValueError: If CSV syntax is invalid or schema is wrong
        """
        try:
            df = pd.read_csv(io.StringIO(self.csv_content), dtype=str, keep_default_na=False)

            # Validate header
            self._validate_schema(df.columns.tolist())

            return df

        except pd.errors.EmptyDataError:
            raise ValueError("CSV file is empty or has no header row")
        except pd.errors.ParserError as e:
            raise ValueError(f"Invalid CSV syntax: {str(e)}")

    def _validate_schema(self, columns: list[str]):
        """
        Validate CSV header structure.

        Args:
            columns: List of column names from DataFrame

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

        if not columns:
            raise ValueError("CSV file is empty or has no header row")

        actual_columns = set(columns)

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

    def _validate_and_transform_row(self, row_data: pd.Series, row_num: int) -> Optional[dict]:
        """
        Validate and transform a single row of CSV data.

        Args:
            row_data: pandas Series containing row data
            row_num: Row number for error reporting (1-indexed)

        Returns:
            Dictionary with 'interval_start_utc' and 'data' keys if valid, None if errors
        """
        interval_start = str(row_data.get("interval_start", "")).strip()
        row_identifier = f"Row {row_num}" + (f": {interval_start}" if interval_start else "")

        # Convert Series to dict for compatibility with existing validation methods
        row_dict = {k: str(v).strip() for k, v in row_data.items()}

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
            if not row_dict.get(field, ""):
                errors.append(f"Missing required field '{field}'")

        if errors:
            self.results["errors"].append((row_identifier, errors))
            return None

        # Parse timestamps
        try:
            interval_start_utc = self._parse_timestamp(
                row_dict["interval_start"], self.customer_timezone
            )
            interval_end_utc = self._parse_timestamp(
                row_dict["interval_end"], self.customer_timezone
            )
        except ValueError as e:
            self.results["errors"].append((row_identifier, [f"Invalid timestamp: {str(e)}"]))
            return None

        # Validate units
        unit_errors = self._validate_units(row_dict)
        if unit_errors:
            self.results["errors"].append((row_identifier, unit_errors))
            return None

        # Parse numeric values
        try:
            energy_kwh = Decimal(row_dict["usage"])
            peak_demand_kw = Decimal(row_dict["peak_demand"])
        except (InvalidOperation, ValueError) as e:
            self.results["errors"].append((row_identifier, [f"Invalid numeric value: {str(e)}"]))
            return None

        # Parse temperature (optional)
        temperature_c = None
        temp_value = row_dict.get("temperature", "")
        if temp_value:
            try:
                temperature_raw = float(temp_value)
                temp_unit = row_dict.get("temperature_unit", "")
                temperature_c = self._convert_temperature_to_celsius(temperature_raw, temp_unit)
            except (ValueError, TypeError):
                self.results["errors"].append(
                    (row_identifier, [f"Invalid temperature value: {temp_value}"])
                )
                return None

        # Pre-validate model constraints (interval duration) without saving
        try:
            temp_usage = CustomerUsage(
                customer=self.customer,
                interval_start_utc=interval_start_utc,
                interval_end_utc=interval_end_utc,
                energy_kwh=energy_kwh,
                peak_demand_kw=peak_demand_kw,
                temperature_c=temperature_c,
            )
            temp_usage.clean()
        except ValidationError as e:
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
            return None

        # Check for warnings
        warning = self._check_demand_warning(peak_demand_kw)
        if warning:
            self.results["warnings"].append((row_identifier, warning))

        return {
            "interval_start_utc": interval_start_utc,
            "row_identifier": row_identifier,
            "data": {
                "interval_start_utc": interval_start_utc,
                "interval_end_utc": interval_end_utc,
                "energy_kwh": energy_kwh,
                "peak_demand_kw": peak_demand_kw,
                "temperature_c": temperature_c,
            },
        }

    def _parse_timestamp(
        self, timestamp_str: str, customer_timezone: zoneinfo.ZoneInfo
    ) -> datetime:
        """
        Parse timestamp, auto-detect if naive or aware, convert to UTC.

        Supports a wide variety of formats via python-dateutil including:
        - ISO 8601: 2024-01-15T14:30:00, 2024-01-15T14:30:00+00:00
        - Common formats: 2024-01-15 14:30:00, 01/15/2024 14:30:00
        - US format: 1/15/2024 2:30:00 PM
        - And many more via dateutil.parser

        Args:
            timestamp_str: Timestamp string to parse
            customer_timezone: Customer's timezone for localizing naive timestamps

        Returns:
            Timezone-aware datetime in UTC

        Raises:
            ValueError: If timestamp cannot be parsed
        """
        try:
            # Try fromisoformat first (fast path for ISO 8601)
            dt = datetime.fromisoformat(timestamp_str)
        except ValueError:
            try:
                # Use dateutil for flexible parsing
                dt = dateutil_parser.parse(timestamp_str)
            except (ValueError, dateutil_parser.ParserError):
                raise ValueError(
                    f"Unable to parse timestamp '{timestamp_str}'. "
                    f"Please use a standard format like YYYY-MM-DD HH:MM:SS or MM/DD/YYYY HH:MM:SS"
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
            "temperature_unit": ["c", "celsius", "°c", "f", "fahrenheit", "°f"],
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
                        f"Invalid {unit_field}: '{row_data.get(unit_field, '')}'. Must be 'C', 'Celsius', 'F', or 'Fahrenheit' (case-insensitive)"
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

    def _convert_temperature_to_celsius(self, temperature_value: float, unit: str) -> float:
        """
        Convert temperature to Celsius if needed.

        Args:
            temperature_value: Temperature value
            unit: Temperature unit (normalized lowercase)

        Returns:
            Temperature in Celsius
        """
        unit = unit.lower().strip()

        # If Fahrenheit, convert to Celsius
        if unit in ["f", "fahrenheit", "°f"]:
            # Formula: C = (F - 32) * 5/9
            celsius = (temperature_value - 32) * 5 / 9
            return celsius

        # Already Celsius (or celsius variants)
        return temperature_value

    def _get_existing_records(
        self, interval_starts: list[datetime]
    ) -> dict[datetime, CustomerUsage]:
        """
        Fetch existing usage records for the given interval starts.

        Args:
            interval_starts: List of interval_start_utc datetimes to check

        Returns:
            Dictionary mapping interval_start_utc to existing CustomerUsage objects
        """
        result = {}
        for i in range(0, len(interval_starts), self.BATCH_SIZE):
            batch = interval_starts[i : i + self.BATCH_SIZE]
            existing = CustomerUsage.objects.filter(
                customer=self.customer, interval_start_utc__in=batch
            )
            for u in existing:
                result[u.interval_start_utc] = u
        return result

    def _split_records(
        self, valid_records: list[dict], existing: dict[datetime, CustomerUsage]
    ) -> tuple[list[dict], list[dict]]:
        """
        Split valid records into create and update lists.

        Args:
            valid_records: List of validated record dictionaries
            existing: Dictionary of existing records keyed by interval_start_utc

        Returns:
            Tuple of (to_create, to_update) record lists
        """
        to_create = []
        to_update = []

        for record in valid_records:
            if record["interval_start_utc"] in existing:
                to_update.append(record)
            else:
                to_create.append(record)

        return to_create, to_update

    def _bulk_create(self, records: list[dict]):
        """
        Bulk create new usage records.

        Args:
            records: List of validated record dictionaries to create
        """
        if not records:
            return

        objects = [CustomerUsage(customer=self.customer, **record["data"]) for record in records]
        for i in range(0, len(objects), self.BATCH_SIZE):
            batch = objects[i : i + self.BATCH_SIZE]
            created = CustomerUsage.objects.bulk_create(batch)
            self.results["created"].extend(created)

    def _bulk_update(self, records: list[dict], existing: dict[datetime, CustomerUsage]):
        """
        Bulk update existing usage records.

        Args:
            records: List of validated record dictionaries to update
            existing: Dictionary of existing records keyed by interval_start_utc
        """
        if not records:
            return

        updated_objects = []
        for record in records:
            obj = existing[record["interval_start_utc"]]
            obj.interval_end_utc = record["data"]["interval_end_utc"]
            obj.energy_kwh = record["data"]["energy_kwh"]
            obj.peak_demand_kw = record["data"]["peak_demand_kw"]
            obj.temperature_c = record["data"]["temperature_c"]
            updated_objects.append(obj)

        for i in range(0, len(updated_objects), self.BATCH_SIZE):
            batch = updated_objects[i : i + self.BATCH_SIZE]
            CustomerUsage.objects.bulk_update(
                batch,
                fields=["interval_end_utc", "energy_kwh", "peak_demand_kw", "temperature_c"],
            )
        self.results["updated"].extend(updated_objects)
