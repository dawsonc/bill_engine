"""
Forms for tariff import/export.
"""

from datetime import date

from django import forms

MONTH_CHOICES = [
    ("", "---"),
    (1, "Jan"),
    (2, "Feb"),
    (3, "Mar"),
    (4, "Apr"),
    (5, "May"),
    (6, "Jun"),
    (7, "Jul"),
    (8, "Aug"),
    (9, "Sep"),
    (10, "Oct"),
    (11, "Nov"),
    (12, "Dec"),
]

DAY_CHOICES = [("", "---")] + [(i, str(i)) for i in range(1, 32)]


class MonthDayWidget(forms.MultiWidget):
    """Widget for selecting month and day as two dropdowns."""

    def __init__(self, attrs=None):
        widgets = [
            forms.Select(attrs=attrs, choices=MONTH_CHOICES),
            forms.Select(attrs=attrs, choices=DAY_CHOICES),
        ]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        """Convert a date value to [month, day] for the widget."""
        if value:
            return [value.month, value.day]
        return [None, None]


class MonthDayField(forms.MultiValueField):
    """Form field for month/day input, stores as date with year 2000."""

    widget = MonthDayWidget

    def __init__(self, **kwargs):
        fields = [
            forms.IntegerField(required=False, min_value=1, max_value=12),
            forms.IntegerField(required=False, min_value=1, max_value=31),
        ]
        super().__init__(fields, **kwargs)

    def compress(self, data_list):
        """Convert [month, day] to a date with year 2000."""
        if not data_list or not all(data_list):
            return None
        month, day = data_list
        try:
            return date(2000, month, day)
        except ValueError as e:
            raise forms.ValidationError(f"Invalid date: {e}")


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
