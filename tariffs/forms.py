"""
Forms for tariff import/export.
"""

from django import forms


class TariffYAMLUploadForm(forms.Form):
    """Form for uploading YAML tariff files."""

    yaml_file = forms.FileField(
        label="YAML File",
        help_text="Upload a .yaml or .yml file with tariff definitions (max 10MB)",
        widget=forms.FileInput(attrs={"accept": ".yaml,.yml"}),
    )

    replace_existing = forms.BooleanField(
        required=False,
        initial=False,
        label="Replace existing tariffs",
        help_text="If checked, tariffs with the same utility+name will be replaced. "
        "Otherwise, they will be skipped with a warning.",
    )

    def clean_yaml_file(self):
        """Validate file extension and size."""
        yaml_file = self.cleaned_data["yaml_file"]

        # Check file extension
        if not yaml_file.name.endswith((".yaml", ".yml")):
            raise forms.ValidationError("File must have .yaml or .yml extension")

        # Check file size (max 10MB)
        if yaml_file.size > 10 * 1024 * 1024:
            raise forms.ValidationError("File size exceeds 10MB limit")

        return yaml_file
