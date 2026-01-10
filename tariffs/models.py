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


class EnergyCharge(models.Model):
    """
    Represents a time-of-use energy charge ($/kWh) for a tariff.
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
    period_start_time_utc = models.TimeField(
        help_text="Start time of the period in UTC (inclusive)"
    )
    period_end_time_utc = models.TimeField(
        help_text="End time of the period in UTC (exclusive of the next minute)"
    )
    applies_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="First date of the year that this charge applies (inclusive). Null if year-round.",
    )
    applies_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Last date of the year that this charge applies (inclusive). Null if year-round.",
    )
    applies_weekends = models.BooleanField(
        default=True, help_text="Whether this charge applies on weekends"
    )
    applies_holidays = models.BooleanField(
        default=True, help_text="Whether this charge applies on utility holidays"
    )
    applies_weekdays = models.BooleanField(
        default=True, help_text="Whether this charge applies on weekdays"
    )

    class Meta:
        ordering = ["tariff", "name"]

    def __str__(self):
        return f"{self.tariff.name} - {self.name} (${self.rate_usd_per_kwh}/kWh)"


class DemandCharge(models.Model):
    """
    Represents a demand charge ($/kW) for a tariff.
    Charges based on the maximum power demand during applicable periods.
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
        decimal_places=2,
        help_text="Rate in $/kW",
    )
    period_start_time_utc = models.TimeField(
        help_text="Start time of the period in UTC (inclusive)"
    )
    period_end_time_utc = models.TimeField(
        help_text="End time of the period in UTC (exclusive of the next minute)"
    )
    applies_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="First date this charge applies (inclusive). Null if year-round.",
    )
    applies_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Last date this charge applies (inclusive). Null if year-round.",
    )
    applies_weekends = models.BooleanField(
        default=True, help_text="Whether this charge applies on weekends"
    )
    applies_holidays = models.BooleanField(
        default=True, help_text="Whether this charge applies on utility holidays"
    )
    applies_weekdays = models.BooleanField(
        default=True, help_text="Whether this charge applies on weekdays"
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
    Represents a fixed monthly customer charge for a tariff.
    """

    tariff = models.ForeignKey(
        Tariff,
        on_delete=models.CASCADE,
        related_name="customer_charges",
        help_text="Tariff this charge belongs to",
    )
    name = models.CharField(max_length=200, help_text="Name of the charge (e.g., Customer Charge)")
    usd_per_month = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Fixed charge in $/month",
    )

    class Meta:
        ordering = ["tariff", "name"]

    def __str__(self):
        return f"{self.tariff.name} - {self.name} (${self.usd_per_month}/month)"
