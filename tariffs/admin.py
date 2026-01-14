from django import forms
from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path

from .forms import MonthDayField, TariffYAMLUploadForm
from .models import ApplicabilityRule, CustomerCharge, DemandCharge, EnergyCharge, Tariff
from .yaml_service import TariffYAMLExporter, TariffYAMLImporter


class ApplicabilityRuleForm(forms.ModelForm):
    """Form for ApplicabilityRule with month/day widgets for date fields."""

    applies_start_date = MonthDayField(
        required=False,
        label="Applies Start (Month/Day)",
        help_text="Seasonal start date (inclusive). Leave blank for year-round.",
    )
    applies_end_date = MonthDayField(
        required=False,
        label="Applies End (Month/Day)",
        help_text="Seasonal end date (inclusive). Leave blank for year-round.",
    )

    class Meta:
        model = ApplicabilityRule
        fields = "__all__"


class EnergyChargeInline(admin.TabularInline):
    model = EnergyCharge
    extra = 1
    fields = ["name", "rate_usd_per_kwh", "applicability_rules"]
    filter_horizontal = ["applicability_rules"]


class DemandChargeInline(admin.TabularInline):
    model = DemandCharge
    extra = 1
    fields = ["name", "rate_usd_per_kw", "peak_type", "applicability_rules"]
    filter_horizontal = ["applicability_rules"]


class CustomerChargeInline(admin.TabularInline):
    model = CustomerCharge
    extra = 1
    fields = ["name", "amount_usd", "charge_type"]


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


@admin.register(ApplicabilityRule)
class ApplicabilityRuleAdmin(admin.ModelAdmin):
    form = ApplicabilityRuleForm
    list_display = [
        "name",
        "time_range",
        "date_range",
        "day_types_display",
        "usage_count",
    ]
    list_filter = ["applies_weekdays", "applies_weekends", "applies_holidays"]
    search_fields = ["name"]

    def time_range(self, obj):
        if obj.period_start_time_local and obj.period_end_time_local:
            return f"{obj.period_start_time_local:%H:%M} - {obj.period_end_time_local:%H:%M}"
        return "All day"

    time_range.short_description = "Time Range"

    def date_range(self, obj):
        if obj.applies_start_date and obj.applies_end_date:
            return f"{obj.applies_start_date:%b %d} - {obj.applies_end_date:%b %d}"
        return "Year-round"

    date_range.short_description = "Date Range"

    def day_types_display(self, obj):
        types = []
        if obj.applies_weekdays:
            types.append("WD")
        if obj.applies_weekends:
            types.append("WE")
        if obj.applies_holidays:
            types.append("HOL")
        return ", ".join(types) if types else "None"

    day_types_display.short_description = "Day Types"

    def usage_count(self, obj):
        energy = obj.energy_charges.count()
        demand = obj.demand_charges.count()
        return f"{energy}E / {demand}D"

    usage_count.short_description = "Used By"


@admin.register(EnergyCharge)
class EnergyChargeAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "tariff",
        "rate_usd_per_kwh",
        "rule_count",
    ]
    list_filter = ["tariff"]
    search_fields = ["name", "tariff__name"]
    filter_horizontal = ["applicability_rules"]

    def rule_count(self, obj):
        return obj.applicability_rules.count()

    rule_count.short_description = "Rules"


@admin.register(DemandCharge)
class DemandChargeAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "tariff",
        "rate_usd_per_kw",
        "peak_type",
        "rule_count",
    ]
    list_filter = ["tariff", "peak_type"]
    search_fields = ["name", "tariff__name"]
    filter_horizontal = ["applicability_rules"]

    def rule_count(self, obj):
        return obj.applicability_rules.count()

    rule_count.short_description = "Rules"


@admin.register(CustomerCharge)
class CustomerChargeAdmin(admin.ModelAdmin):
    list_display = ["name", "tariff", "amount_usd", "charge_type"]
    list_filter = ["tariff", "charge_type"]
    search_fields = ["name", "tariff__name"]
