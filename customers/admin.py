from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "get_utility",
        "current_tariff",
        "timezone",
        "created_at",
        "updated_at",
    ]
    list_filter = ["current_tariff__utility", "current_tariff"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]

    def get_utility(self, obj):
        return obj.current_tariff.utility

    get_utility.short_description = "Utility"
