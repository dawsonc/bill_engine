from django.contrib import admin

from .models import CustomerUsage


@admin.register(CustomerUsage)
class CustomerUsageAdmin(admin.ModelAdmin):
    list_display = [
        "customer",
        "interval_start_utc",
        "interval_end_utc",
        "energy_kwh",
        "peak_demand_kw",
        "temperature_c",
    ]
    list_filter = ["customer", "interval_start_utc"]
    search_fields = ["customer__name"]
    date_hierarchy = "interval_start_utc"
    readonly_fields = ["created_at_utc"]
    list_per_page = 50
