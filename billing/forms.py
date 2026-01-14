"""Forms for billing module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms

from billing.services import get_available_billing_months

if TYPE_CHECKING:
    from customers.models import Customer


class BillingMonthRangeForm(forms.Form):
    """Form for selecting a range of billing months for bill calculation."""

    start_billing_month = forms.ChoiceField(
        label="Start Billing Month",
        help_text="First billing month to calculate",
    )
    end_billing_month = forms.ChoiceField(
        label="End Billing Month",
        help_text="Last billing month to calculate",
    )

    def __init__(self, *args, customer: Customer | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer

        if customer:
            choices = get_available_billing_months(customer)
            if choices:
                self.fields["start_billing_month"].choices = choices
                self.fields["end_billing_month"].choices = choices
                # Default to last month for end, first for start if more than one
                if len(choices) >= 1:
                    self.fields["end_billing_month"].initial = choices[-1][0]
                    self.fields["start_billing_month"].initial = choices[-1][0]
            else:
                # No billing months available
                self.fields["start_billing_month"].choices = [
                    ("", "No billing months available")
                ]
                self.fields["end_billing_month"].choices = [
                    ("", "No billing months available")
                ]
                self.fields["start_billing_month"].disabled = True
                self.fields["end_billing_month"].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_billing_month")
        end = cleaned_data.get("end_billing_month")

        if start and end and start > end:
            raise forms.ValidationError(
                "Start billing month must be before or equal to end billing month."
            )

        return cleaned_data
