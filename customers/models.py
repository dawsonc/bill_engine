from django.db import models
from timezone_field import TimeZoneField


class Customer(models.Model):
    """
    Represents a customer with energy usage data.
    """

    name = models.CharField(max_length=200, help_text="Name of the customer")
    timezone = TimeZoneField(
        help_text="IANA timezone for this customer's location",
    )
    current_tariff = models.ForeignKey(
        "tariffs.Tariff",
        on_delete=models.PROTECT,
        null=False,
        blank=False,
        related_name="current_customers",
        help_text="Current tariff for this customer",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
