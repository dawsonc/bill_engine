"""
Forms for usage data management.
"""

from django import forms

from customers.models import Customer


class UsageCSVUploadForm(forms.Form):
    """Form for uploading CSV usage files for a single customer."""

    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all().order_by("name"),
        empty_label="Select customer...",
        help_text="Select the customer for this usage data",
    )

    csv_file = forms.FileField(
        label="CSV File",
        help_text="Upload a .csv file with usage data (max 10MB)",
        widget=forms.FileInput(attrs={"accept": ".csv"}),
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
