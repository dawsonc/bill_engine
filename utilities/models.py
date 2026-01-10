from django.db import models
from timezone_field import TimeZoneField


class Utility(models.Model):
    """
    Represents a utility company (e.g., PG&E, SCE).
    """

    name = models.CharField(max_length=200, unique=True, help_text="Name of the utility company")
    timezone = TimeZoneField(
        default="America/Los_Angeles", help_text="IANA timezone for this utility's service area"
    )

    class Meta:
        verbose_name_plural = "Utilities"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Holiday(models.Model):
    """
    Represents a holiday for a utility company.
    Used to determine when business day rates don't apply.
    """

    utility = models.ForeignKey(
        Utility, on_delete=models.CASCADE, related_name="holidays", help_text="Utility company"
    )
    name = models.CharField(max_length=200, help_text="Name of the holiday (e.g., Independence Day)")
    date = models.DateField(help_text="Date of the holiday")

    class Meta:
        ordering = ["date"]
        unique_together = [["utility", "date"]]

    def __str__(self):
        return f"{self.name} ({self.date}) - {self.utility.name}"
