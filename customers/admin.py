from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import path

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
