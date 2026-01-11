from django.contrib import admin

from .models import Holiday, Utility


class HolidayInline(admin.TabularInline):
    model = Holiday
    extra = 1
    fields = ["name", "date"]


@admin.register(Utility)
class UtilityAdmin(admin.ModelAdmin):
    list_display = ["name", "holiday_count"]
    search_fields = ["name"]
    inlines = [HolidayInline]

    def holiday_count(self, obj):
        return obj.holidays.count()

    holiday_count.short_description = "Holidays"


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ["name", "date", "utility"]
    list_filter = ["utility", "date"]
    search_fields = ["name", "utility__name"]
    date_hierarchy = "date"
