from django.contrib import admin

from .models import CustomerCharge, DemandCharge, EnergyCharge, Tariff


class EnergyChargeInline(admin.TabularInline):
    model = EnergyCharge
    extra = 1
    fields = [
        "name",
        "rate_usd_per_kwh",
        "period_start_time_utc",
        "period_end_time_utc",
        "applies_start_date",
        "applies_end_date",
        "applies_weekends",
        "applies_holidays",
        "applied_weekdays",
    ]


class DemandChargeInline(admin.TabularInline):
    model = DemandCharge
    extra = 1
    fields = [
        "name",
        "rate_usd_per_kw",
        "period_start_time_utc",
        "period_end_time_utc",
        "applies_start_date",
        "applies_end_date",
        "applies_weekends",
        "applies_holidays",
        "applied_weekdays",
        "peak_type",
    ]


class CustomerChargeInline(admin.TabularInline):
    model = CustomerCharge
    extra = 1
    fields = ["name", "usd_per_month"]


@admin.register(Tariff)
class TariffAdmin(admin.ModelAdmin):
    list_display = ["name", "utility", "charge_count"]
    list_filter = ["utility"]
    search_fields = ["name", "utility__name"]
    inlines = [EnergyChargeInline, DemandChargeInline, CustomerChargeInline]

    def charge_count(self, obj):
        energy = obj.energy_charges.count()
        demand = obj.demand_charges.count()
        customer = obj.customer_charges.count()
        return f"E:{energy} D:{demand} C:{customer}"

    charge_count.short_description = "Charges (E/D/C)"


@admin.register(EnergyCharge)
class EnergyChargeAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "tariff",
        "rate_usd_per_kwh",
        "period_start_time_utc",
        "period_end_time_utc",
        "applies_start_date",
        "applies_end_date",
    ]
    list_filter = ["tariff", "applies_weekdays", "applies_weekends", "applies_holidays"]
    search_fields = ["name", "tariff__name"]


@admin.register(DemandCharge)
class DemandChargeAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "tariff",
        "rate_usd_per_kw",
        "period_start_time_utc",
        "period_end_time_utc",
        "peak_type",
    ]
    list_filter = [
        "tariff",
        "peak_type",
        "applies_weekdays",
        "applies_weekends",
        "applies_holidays",
    ]
    search_fields = ["name", "tariff__name"]


@admin.register(CustomerCharge)
class CustomerChargeAdmin(admin.ModelAdmin):
    list_display = ["name", "tariff", "usd_per_month"]
    list_filter = ["tariff"]
    search_fields = ["name", "tariff__name"]
