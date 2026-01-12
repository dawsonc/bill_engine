"""
Forms for customer management.
"""

from django import forms


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
