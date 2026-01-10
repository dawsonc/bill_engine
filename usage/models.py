from django.db import models


class CustomerUsage(models.Model):
    """
    Represents customer energy usage in a 5-minute interval.
    All intervals are stored in UTC with 5-minute granularity as the canonical representation.
    """

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="usage_records",
        help_text="Customer",
    )
    interval_start_utc = models.DateTimeField(
        db_index=True, help_text="Start of the 5-minute interval in UTC (inclusive)"
    )
    interval_end_utc = models.DateTimeField(
        help_text="End of the 5-minute interval in UTC (exclusive)"
    )
    energy_kwh = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Energy consumption in kWh for this interval",
    )
    peak_demand_kw = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Peak power demand in kW during this interval",
    )
    temperature_c = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Temperature in Celsius (optional)",
    )
    created_at_utc = models.DateTimeField(
        auto_now_add=True, help_text="When this record was created"
    )

    class Meta:
        verbose_name_plural = "Customer usage records"
        ordering = ["customer", "interval_start_utc"]
        unique_together = [["customer", "interval_start_utc"]]
        indexes = [
            models.Index(fields=["customer", "interval_start_utc"]),
        ]

    def __str__(self):
        return f"{self.customer.name} - {self.interval_start_utc} ({self.energy_kwh} kWh)"
