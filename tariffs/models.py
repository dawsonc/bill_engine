from datetime import date

from django.core.exceptions import ValidationError
from django.db import models


class Tariff(models.Model):
    """
    Represents a utility tariff (e.g., PG&E B-19 Secondary).

    A tariff defines the pricing structure for energy, demand, and customer charges.
    """

    name = models.CharField(max_length=200, help_text="Name of the tariff (e.g., PG&E B-19)")
    utility = models.ForeignKey(
        "utilities.Utility",
        on_delete=models.CASCADE,
        related_name="tariffs",
        help_text="Utility company offering this tariff",
    )

    class Meta:
        ordering = ["utility__name", "name"]
        unique_together = [["utility", "name"]]

    def __str__(self):
        return f"{self.name} ({self.utility.name})"


class ApplicabilityRule(models.Model):
    """
    Reusable applicability window for energy and demand charges.

    Multiple charges can share rules, and one charge can have multiple rules.
    When a charge has multiple rules, they combine with OR logic (charge applies
    if ANY rule matches).
    """

    name = models.CharField(
        max_length=200,
        help_text="Descriptive name (e.g., 'Summer Peak Hours')",
    )
    period_start_time_local = models.TimeField(
        null=True,
        blank=True,
        help_text="Start time (inclusive). Null = start of day.",
    )
    period_end_time_local = models.TimeField(
        null=True,
        blank=True,
        help_text="End time (exclusive). Null = end of day.",
    )
    applies_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Seasonal start (month/day only). Null = year-round.",
    )
    applies_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Seasonal end (month/day only). Null = year-round.",
    )
    applies_weekdays = models.BooleanField(
        default=True,
        help_text="Whether this rule applies on weekdays",
    )
    applies_weekends = models.BooleanField(
        default=True,
        help_text="Whether this rule applies on weekends",
    )
    applies_holidays = models.BooleanField(
        default=True,
        help_text="Whether this rule applies on utility holidays",
    )

    def clean(self):
        """Validate rule constraints."""
        # Validate time period (only if both are provided)
        if self.period_start_time_local and self.period_end_time_local:
            if self.period_end_time_local <= self.period_start_time_local:
                raise ValidationError(
                    {"period_end_time_local": "Period end time must be after period start time."}
                )

        # Validate date range (only if both dates are provided)
        # Compare only month/day by normalizing to year 2000
        if self.applies_start_date and self.applies_end_date:
            start_normalized = date(
                2000, self.applies_start_date.month, self.applies_start_date.day
            )
            end_normalized = date(
                2000, self.applies_end_date.month, self.applies_end_date.day
            )
            if end_normalized < start_normalized:
                raise ValidationError(
                    {"applies_end_date": "Applicable end date must be on or after the start date."}
                )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        parts = [self.name]
        if self.period_start_time_local and self.period_end_time_local:
            parts.append(
                f"{self.period_start_time_local:%H:%M}-{self.period_end_time_local:%H:%M}"
            )
        return " ".join(parts)


class EnergyCharge(models.Model):
    """
    Represents a time-of-use energy charge ($/kWh) for a tariff.

    Applicability is determined by linked ApplicabilityRule objects.
    Multiple rules are combined with OR logic (charge applies if ANY rule matches).
    """

    tariff = models.ForeignKey(
        Tariff,
        on_delete=models.CASCADE,
        related_name="energy_charges",
        help_text="Tariff this charge belongs to",
    )
    name = models.CharField(
        max_length=200, help_text="Name of the charge (e.g., Summer Peak Energy)"
    )
    rate_usd_per_kwh = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        help_text="Rate in $/kWh",
    )
    applicability_rules = models.ManyToManyField(
        ApplicabilityRule,
        blank=True,
        related_name="energy_charges",
        help_text="Applicability rules (combined with OR logic)",
    )

    class Meta:
        ordering = ["tariff", "name"]

    def __str__(self):
        return f"{self.tariff.name} - {self.name} (${self.rate_usd_per_kwh}/kWh)"


class DemandCharge(models.Model):
    """
    Represents a demand charge ($/kW) for a tariff.

    Charges based on the maximum power demand during applicable periods.
    Applicability is determined by linked ApplicabilityRule objects.
    Multiple rules are combined with OR logic (charge applies if ANY rule matches).
    """

    PEAK_TYPE_CHOICES = [
        ("daily", "Daily"),
        ("monthly", "Monthly"),
    ]

    tariff = models.ForeignKey(
        Tariff,
        on_delete=models.CASCADE,
        related_name="demand_charges",
        help_text="Tariff this charge belongs to",
    )
    name = models.CharField(
        max_length=200, help_text="Name of the charge (e.g., Summer Peak Demand)"
    )
    rate_usd_per_kw = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        help_text="Rate in $/kW",
    )
    applicability_rules = models.ManyToManyField(
        ApplicabilityRule,
        blank=True,
        related_name="demand_charges",
        help_text="Applicability rules (combined with OR logic)",
    )
    peak_type = models.CharField(
        max_length=10,
        choices=PEAK_TYPE_CHOICES,
        default="monthly",
        help_text="Whether peak is calculated daily or monthly",
    )

    class Meta:
        ordering = ["tariff", "name"]

    def __str__(self):
        return f"{self.tariff.name} - {self.name} (${self.rate_usd_per_kw}/kW, {self.peak_type})"


class CustomerCharge(models.Model):
    """
    Represents a fixed recurring customer charge for a tariff.

    Can be either a daily or monthly charge.
    """

    CHARGE_TYPE_CHOICES = [
        ("daily", "Daily"),
        ("monthly", "Monthly"),
    ]

    tariff = models.ForeignKey(
        Tariff,
        on_delete=models.CASCADE,
        related_name="customer_charges",
        help_text="Tariff this charge belongs to",
    )
    name = models.CharField(max_length=200, help_text="Name of the charge (e.g., Customer Charge)")
    amount_usd = models.DecimalField(
        max_digits=10,
        decimal_places=5,
        help_text="Fixed charge amount in USD (per day or per month depending on charge_type)",
    )
    charge_type = models.CharField(
        max_length=10,
        choices=CHARGE_TYPE_CHOICES,
        default="monthly",
        help_text="Whether this is a daily or monthly charge",
    )

    class Meta:
        ordering = ["tariff", "name"]

    def __str__(self):
        period = "day" if self.charge_type == "daily" else "month"
        return f"{self.tariff.name} - {self.name} (${self.amount_usd}/{period})"
