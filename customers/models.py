from django.db import models
from timezone_field import TimeZoneField


class Customer(models.Model):
    """
    Represents a customer with energy usage data.
    """

    name = models.CharField(max_length=200, help_text="Name of the customer")
    timezone = TimeZoneField(
        default="America/Los_Angeles",
        help_text="IANA timezone for this customer's location",
    )
    current_tariff = models.ForeignKey(
        "tariffs.Tariff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_customers",
        help_text="Current tariff for this customer",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CustomerTariffHistory(models.Model):
    """
    Tracks historical tariff assignments for a customer.
    Allows customers to change tariffs over time.
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="tariff_history",
        help_text="Customer",
    )
    tariff = models.ForeignKey(
        "tariffs.Tariff",
        on_delete=models.CASCADE,
        related_name="customer_history",
        help_text="Tariff",
    )
    effective_from = models.DateField(help_text="Date this tariff became effective for the customer")
    effective_to = models.DateField(
        null=True,
        blank=True,
        help_text="Date this tariff stopped being effective (null if current)",
    )

    class Meta:
        verbose_name_plural = "Customer tariff histories"
        ordering = ["customer", "-effective_from"]
        unique_together = [["customer", "effective_from"]]

    def __str__(self):
        return f"{self.customer.name} - {self.tariff.name} (from {self.effective_from})"
