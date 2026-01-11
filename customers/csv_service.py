"""
CSV import/export service for bulk customer operations.

Provides CustomerCSVExporter and CustomerCSVImporter classes for handling
bulk customer uploads and downloads via CSV format.
"""

import csv
import io
import zoneinfo
from django.core.exceptions import ValidationError
from django.db import transaction

from customers.models import Customer
from tariffs.models import Tariff


class CustomerCSVExporter:
    """Export customers to CSV format."""

    def __init__(self, customers_queryset):
        """
        Initialize exporter with customers queryset.

        Args:
            customers_queryset: Django queryset of Customer objects to export
        """
        self.customers = customers_queryset.select_related('current_tariff__utility')

    def export_to_csv(self) -> str:
        """
        Export customers to CSV string.

        Returns:
            CSV string representation of customers with header row
        """
        output = io.StringIO()
        fieldnames = ['name', 'timezone', 'utility_name', 'tariff_name']
        writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)

        writer.writeheader()

        for customer in self.customers:
            writer.writerow({
                'name': customer.name,
                'timezone': str(customer.timezone),
                'utility_name': customer.current_tariff.utility.name,
                'tariff_name': customer.current_tariff.name,
            })

        return output.getvalue()


class CustomerCSVImporter:
    """Import customers from CSV format with validation."""

    def __init__(self, csv_content: str, replace_existing: bool = False):
        """
        Initialize importer with CSV content.

        Args:
            csv_content: CSV string to parse and import
            replace_existing: If True, update existing customers with same name.
                            If False, skip existing customers.
        """
        self.csv_content = csv_content
        self.replace_existing = replace_existing
        self.results = {
            'created': [],  # [customer, ...]
            'updated': [],  # [customer, ...]
            'skipped': [],  # [(customer_name, reason), ...]
            'errors': [],   # [(row_identifier, [error_messages]), ...]
        }

    def import_customers(self) -> dict:
        """
        Parse and import customers from CSV.

        Returns:
            Dictionary with results structure containing created, updated, skipped, and errors
        """
        try:
            rows = self._parse_csv()
        except Exception as e:
            self.results['errors'].append(('CSV File', [str(e)]))
            return self.results

        if not rows:
            self.results['errors'].append(('CSV File', ['No data rows found in CSV file']))
            return self.results

        # Import each customer in its own transaction
        for row_num, row_data in enumerate(rows, start=2):  # Start at 2 (header is row 1)
            self._import_single_customer(row_data, row_num)

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
        expected_columns = {'name', 'timezone', 'utility_name', 'tariff_name'}

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
                f"Invalid CSV header. Expected columns: name,timezone,utility_name,tariff_name. "
                f"{'; '.join(error_parts)}"
            )

    def _import_single_customer(self, row_data: dict, row_num: int):
        """
        Import a single customer atomically.

        Args:
            row_data: Dictionary of CSV row data
            row_num: Row number for error reporting (1-indexed)
        """
        customer_name = row_data.get('name', '').strip()
        row_identifier = f"Row {row_num}" + (f": {customer_name}" if customer_name else "")

        try:
            # Validate required fields
            errors = []
            for field in ['name', 'timezone', 'utility_name', 'tariff_name']:
                if not row_data.get(field, '').strip():
                    errors.append(f"Missing required field '{field}'")

            if errors:
                self.results['errors'].append((row_identifier, errors))
                return

            # Clean data
            name = row_data['name'].strip()
            timezone_str = row_data['timezone'].strip()
            utility_name = row_data['utility_name'].strip()
            tariff_name = row_data['tariff_name'].strip()

            # Validate timezone
            try:
                zoneinfo.ZoneInfo(timezone_str)
            except zoneinfo.ZoneInfoNotFoundError:
                self.results['errors'].append((
                    row_identifier,
                    [f"Invalid timezone '{timezone_str}'. Must be a valid IANA timezone."]
                ))
                return

            # Lookup tariff
            tariff = Tariff.objects.filter(
                utility__name=utility_name,
                name=tariff_name
            ).select_related('utility').first()

            if not tariff:
                self.results['errors'].append((
                    row_identifier,
                    [f"Tariff '{tariff_name}' not found for utility '{utility_name}'"]
                ))
                return

            # Import customer in atomic transaction
            with transaction.atomic():
                # Check for existing customer
                existing_customer = Customer.objects.filter(name=name).first()

                if existing_customer:
                    if not self.replace_existing:
                        self.results['skipped'].append((
                            name,
                            f"Customer already exists (replace_existing not checked)"
                        ))
                        return
                    else:
                        # Update existing customer
                        existing_customer.timezone = timezone_str
                        existing_customer.current_tariff = tariff
                        existing_customer.full_clean()
                        existing_customer.save()
                        self.results['updated'].append(existing_customer)
                else:
                    # Create new customer
                    customer = Customer(
                        name=name,
                        timezone=timezone_str,
                        current_tariff=tariff
                    )
                    customer.full_clean()
                    customer.save()
                    self.results['created'].append(customer)

        except ValidationError as e:
            # Extract validation error messages
            error_messages = []
            if hasattr(e, 'message_dict'):
                for field, messages in e.message_dict.items():
                    for message in messages:
                        error_messages.append(f"{field}: {message}")
            elif hasattr(e, 'messages'):
                error_messages.extend(e.messages)
            else:
                error_messages.append(str(e))

            self.results['errors'].append((row_identifier, error_messages))

        except Exception as e:
            # Catch any unexpected errors
            self.results['errors'].append((row_identifier, [str(e)]))
