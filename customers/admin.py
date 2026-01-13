import json

from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path

from customers.forms import UsageChartDateRangeForm
from customers.usage_analytics import analyze_usage_gaps
from customers.usage_chart_data import (
    get_default_date_range,
    get_usage_timeseries_data,
)

from .csv_service import CustomerCSVExporter, CustomerCSVImporter
from .forms import CustomerCSVUploadForm
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
    change_list_template = "admin/customers/customer_changelist.html"
    change_form_template = "admin/customers/customer_change_form.html"
    actions = ["export_selected_customers_to_csv"]

    def get_utility(self, obj):
        return obj.current_tariff.utility

    get_utility.short_description = "Utility"

    def get_urls(self):
        """Add custom URLs for import/export views."""
        urls = super().get_urls()
        custom_urls = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_customers_view),
                name="customers_customer_import",
            ),
            path(
                "export/",
                self.admin_site.admin_view(self.export_customers_view),
                name="customers_customer_export",
            ),
        ]
        return custom_urls + urls

    def import_customers_view(self, request):
        """Handle CSV import via file upload."""
        if request.method == "POST":
            form = CustomerCSVUploadForm(request.POST, request.FILES)
            if form.is_valid():
                csv_file = form.cleaned_data["csv_file"]
                replace_existing = form.cleaned_data["replace_existing"]

                # Read file content
                csv_content = csv_file.read().decode("utf-8")

                # Import customers
                importer = CustomerCSVImporter(csv_content, replace_existing=replace_existing)
                results = importer.import_customers()

                # Render results page
                context = {
                    **self.admin_site.each_context(request),
                    "results": results,
                    "opts": self.model._meta,
                    "title": "CSV Import Results",
                }
                return render(request, "admin/customers/customer_import_result.html", context)
        else:
            form = CustomerCSVUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "opts": self.model._meta,
            "title": "Import Customers from CSV",
        }
        return render(request, "admin/customers/customer_import.html", context)

    def export_customers_view(self, request):
        """Export all customers as CSV download."""
        customers = Customer.objects.all()
        exporter = CustomerCSVExporter(customers)
        csv_str = exporter.export_to_csv()

        response = HttpResponse(csv_str, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="customers.csv"'
        return response

    @admin.action(description="Export selected customers to CSV")
    def export_selected_customers_to_csv(self, request, queryset):
        """Export selected customers as CSV download."""
        exporter = CustomerCSVExporter(queryset)
        csv_str = exporter.export_to_csv()

        response = HttpResponse(csv_str, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="customers_selected.csv"'
        return response

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        """Override to add usage gap warnings and usage chart to context."""
        extra_context = extra_context or {}

        # Only add data when viewing existing customer (not add form)
        if object_id:
            try:
                customer = self.get_object(request, object_id)
                if customer:
                    # Existing gap warnings code
                    gap_warnings = analyze_usage_gaps(customer)
                    extra_context["usage_gap_warnings"] = gap_warnings

                    # Parse date range from GET parameters or use defaults
                    chart_form = UsageChartDateRangeForm(
                        data=request.GET if request.GET else None, customer=customer
                    )

                    if chart_form.is_valid():
                        start_date = chart_form.cleaned_data["start_date"]
                        end_date = chart_form.cleaned_data["end_date"]
                    else:
                        # Use defaults (last 30 days)
                        start_date, end_date = get_default_date_range(customer)

                        # Reinitialize form with defaults for display
                        chart_form = UsageChartDateRangeForm(
                            initial={"start_date": start_date, "end_date": end_date},
                            customer=customer,
                        )

                    # Get chart data
                    chart_data = get_usage_timeseries_data(customer, start_date, end_date)

                    # Serialize to JSON for JavaScript
                    chart_data_json = json.dumps(chart_data)

                    # Add to context
                    extra_context["chart_date_form"] = chart_form
                    extra_context["chart_data"] = chart_data
                    extra_context["chart_data_json"] = chart_data_json

            except Exception as e:
                # Log error but don't break admin page
                import logging

                logger = logging.getLogger(__name__)
                logger.exception(f"Error preparing data for customer {object_id}: {e}")

                extra_context["usage_gap_warnings"] = []
                extra_context["chart_date_form"] = UsageChartDateRangeForm(
                    customer=customer if "customer" in locals() else None
                )
                extra_context["chart_data"] = {
                    "has_data": False,
                    "timestamps": [],
                    "energy_kwh": [],
                    "peak_demand_kw": [],
                    "point_count": 0,
                }
                extra_context["chart_data_json"] = json.dumps(extra_context["chart_data"])

        return super().changeform_view(request, object_id, form_url, extra_context)
