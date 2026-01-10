from django.contrib import admin

from .models import Customer, CustomerTariffHistory


class CustomerTariffHistoryInline(admin.TabularInline):
    model = CustomerTariffHistory
    extra = 1
    fields = ["tariff", "effective_from", "effective_to"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "timezone", "current_tariff", "created_at", "updated_at"]
    list_filter = ["timezone", "current_tariff"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [CustomerTariffHistoryInline]


@admin.register(CustomerTariffHistory)
class CustomerTariffHistoryAdmin(admin.ModelAdmin):
    list_display = ["customer", "tariff", "effective_from", "effective_to"]
    list_filter = ["customer", "tariff", "effective_from"]
    search_fields = ["customer__name", "tariff__name"]
    date_hierarchy = "effective_from"
