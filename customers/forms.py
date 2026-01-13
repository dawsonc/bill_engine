"""
Forms for customer management.
"""

import zoneinfo

from django import forms
from django.utils import timezone


class CustomerCSVUploadForm(forms.Form):
    """Form for uploading CSV customer files."""

    csv_file = forms.FileField(
        label="CSV File",
        help_text="Upload a .csv file with customer definitions (max 10MB)",
        widget=forms.FileInput(attrs={"accept": ".csv"}),
    )

    replace_existing = forms.BooleanField(
        required=False,
        initial=False,
        label="Replace existing customers",
        help_text="If checked, customers with the same name will be updated. "
        "Otherwise, they will be skipped with a warning.",
    )

    def clean_csv_file(self):
        """Validate file extension and size."""
        csv_file = self.cleaned_data["csv_file"]

        # Check file extension
        if not csv_file.name.endswith(".csv"):
            raise forms.ValidationError(f"File must have .csv extension. Received: {csv_file.name}")

        # Check file size (10MB = 10 * 1024 * 1024 bytes)
        max_size = 10 * 1024 * 1024
        if csv_file.size > max_size:
            size_mb = csv_file.size / (1024 * 1024)
            raise forms.ValidationError(
                f"File size ({size_mb:.2f}MB) exceeds maximum allowed size (10MB)"
            )

        return csv_file


class UsageChartDateRangeForm(forms.Form):
    """Form for filtering usage chart by date range."""

    start_date = forms.DateField(
        label="Start Date",
        widget=forms.DateInput(
            attrs={"type": "date", "class": "vDateField"}  # Django admin CSS
        ),
        help_text="Start of date range (inclusive)",
    )

    end_date = forms.DateField(
        label="End Date",
        widget=forms.DateInput(attrs={"type": "date", "class": "vDateField"}),
        help_text="End of date range (inclusive)",
    )

    def __init__(self, *args, customer=None, **kwargs):
        """Initialize form with customer for timezone validation."""
        super().__init__(*args, **kwargs)
        self.customer = customer
        if customer:
            self.customer_tz = zoneinfo.ZoneInfo(str(customer.timezone))

    def clean(self):
        """Validate date range."""
        cleaned_data = super().clean()
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")

        if start and end:
            # Validate start before end
            if start > end:
                raise forms.ValidationError("Start date must be before or equal to end date.")

            # Validate not too far in future
            if self.customer:
                today_utc = timezone.now()
                today_local = today_utc.astimezone(self.customer_tz).date()

                if start > today_local:
                    raise forms.ValidationError("Start date cannot be in the future.")

                # Cap end date at today (don't error, just cap in view)

        return cleaned_data
