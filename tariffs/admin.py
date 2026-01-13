from django import forms
from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path

from .forms import MonthDayField, TariffYAMLUploadForm
from .models import CustomerCharge, DemandCharge, EnergyCharge, Tariff
from .yaml_service import TariffYAMLExporter, TariffYAMLImporter


class EnergyChargeForm(forms.ModelForm):
    """Form for EnergyCharge with month/day widgets for date fields."""

    applies_start_date = MonthDayField(
        required=False,
        label="Applies Start (Month/Day)",
        help_text="First date of the year this charge applies (inclusive). Leave blank for year-round.",
    )
    applies_end_date = MonthDayField(
        required=False,
        label="Applies End (Month/Day)",
        help_text="Last date of the year this charge applies (inclusive). Leave blank for year-round.",
    )

    class Meta:
        model = EnergyCharge
        fields = "__all__"


class DemandChargeForm(forms.ModelForm):
    """Form for DemandCharge with month/day widgets for date fields."""

    applies_start_date = MonthDayField(
        required=False,
        label="Applies Start (Month/Day)",
        help_text="First date this charge applies (inclusive). Leave blank for year-round.",
    )
    applies_end_date = MonthDayField(
        required=False,
        label="Applies End (Month/Day)",
        help_text="Last date this charge applies (inclusive). Leave blank for year-round.",
    )

    class Meta:
        model = DemandCharge
        fields = "__all__"


class EnergyChargeInline(admin.TabularInline):
    model = EnergyCharge
    form = EnergyChargeForm
    extra = 1
    fields = [
        "name",
        "rate_usd_per_kwh",
        "period_start_time_local",
        "period_end_time_local",
        "applies_start_date",
        "applies_end_date",
        "applies_weekends",
        "applies_holidays",
        "applies_weekdays",
    ]


class DemandChargeInline(admin.TabularInline):
    model = DemandCharge
    form = DemandChargeForm
    extra = 1
    fields = [
        "name",
        "rate_usd_per_kw",
        "period_start_time_local",
        "period_end_time_local",
        "applies_start_date",
        "applies_end_date",
        "applies_weekends",
        "applies_holidays",
        "applies_weekdays",
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
    change_list_template = "admin/tariffs/tariff_changelist.html"
    actions = ["export_selected_tariffs_to_yaml"]

    def charge_count(self, obj):
        energy = obj.energy_charges.count()
        demand = obj.demand_charges.count()
        customer = obj.customer_charges.count()
        return f"{energy}/{demand}/{customer}"

    charge_count.short_description = "Charges (E/D/C)"

    def get_urls(self):
        """Add custom URLs for import/export views."""
        urls = super().get_urls()
        custom_urls = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_tariffs_view),
                name="tariffs_tariff_import",
            ),
            path(
                "export/",
                self.admin_site.admin_view(self.export_tariffs_view),
                name="tariffs_tariff_export",
            ),
        ]
        return custom_urls + urls

    def import_tariffs_view(self, request):
        """Handle YAML import via file upload."""
        if request.method == "POST":
            form = TariffYAMLUploadForm(request.POST, request.FILES)
            if form.is_valid():
                yaml_file = form.cleaned_data["yaml_file"]
                replace_existing = form.cleaned_data["replace_existing"]

                # Read file content
                yaml_content = yaml_file.read().decode("utf-8")

                # Import tariffs
                importer = TariffYAMLImporter(yaml_content, replace_existing=replace_existing)
                results = importer.import_tariffs()

                # Render results page
                context = {
                    **self.admin_site.each_context(request),
                    "results": results,
                    "opts": self.model._meta,
                }
                return render(request, "admin/tariffs/tariff_import_result.html", context)
        else:
            form = TariffYAMLUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "opts": self.model._meta,
            "title": "Import Tariffs from YAML",
        }
        return render(request, "admin/tariffs/tariff_import.html", context)

    def export_tariffs_view(self, request):
        """Export all tariffs as YAML download."""
        tariffs = Tariff.objects.all()
        exporter = TariffYAMLExporter(tariffs)
        yaml_str = exporter.export_to_yaml()

        response = HttpResponse(yaml_str, content_type="application/x-yaml")
        response["Content-Disposition"] = 'attachment; filename="tariffs.yaml"'
        return response

    @admin.action(description="Export selected tariffs to YAML")
    def export_selected_tariffs_to_yaml(self, request, queryset):
        """Export selected tariffs as YAML download."""
        exporter = TariffYAMLExporter(queryset)
        yaml_str = exporter.export_to_yaml()

        response = HttpResponse(yaml_str, content_type="application/x-yaml")
        response["Content-Disposition"] = 'attachment; filename="tariffs_selected.yaml"'
        return response


@admin.register(EnergyCharge)
class EnergyChargeAdmin(admin.ModelAdmin):
    form = EnergyChargeForm
    list_display = [
        "name",
        "tariff",
        "rate_usd_per_kwh",
        "period_start_time_local",
        "period_end_time_local",
        "applies_start_date",
        "applies_end_date",
    ]
    list_filter = ["tariff", "applies_weekdays", "applies_weekends", "applies_holidays"]
    search_fields = ["name", "tariff__name"]


@admin.register(DemandCharge)
class DemandChargeAdmin(admin.ModelAdmin):
    form = DemandChargeForm
    list_display = [
        "name",
        "tariff",
        "rate_usd_per_kw",
        "period_start_time_local",
        "period_end_time_local",
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
