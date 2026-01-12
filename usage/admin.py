from django.contrib import admin
from django.shortcuts import render
from django.urls import path

from .csv_service import UsageCSVImporter
from .forms import UsageCSVUploadForm
from .models import CustomerUsage


@admin.register(CustomerUsage)
class CustomerUsageAdmin(admin.ModelAdmin):
    list_display = [
        "customer",
        "interval_start_utc",
        "energy_kwh",
        "peak_demand_kw",
        "temperature_c",
    ]
    list_filter = ["customer", "interval_start_utc"]
    search_fields = ["customer__name"]
    date_hierarchy = "interval_start_utc"
    readonly_fields = ["created_at_utc"]
    list_per_page = 50
    change_list_template = "admin/usage/customerusage_changelist.html"

    def get_urls(self):
        """Add custom URLs for import view."""
        urls = super().get_urls()
        custom_urls = [
            path(
                "import/",
                self.admin_site.admin_view(self.import_usage_view),
                name="usage_customerusage_import",
            ),
        ]
        return custom_urls + urls

    def import_usage_view(self, request):
        """Handle CSV import via file upload."""
        if request.method == "POST":
            form = UsageCSVUploadForm(request.POST, request.FILES)
            if form.is_valid():
                csv_file = form.cleaned_data["csv_file"]
                customer = form.cleaned_data["customer"]

                # Read file content
                csv_content = csv_file.read().decode("utf-8")

                # Import usage data
                importer = UsageCSVImporter(csv_content, customer=customer)
                results = importer.import_usage()

                # Render results page
                context = {
                    **self.admin_site.each_context(request),
                    "results": results,
                    "customer": customer,
                    "opts": self.model._meta,
                    "title": "CSV Import Results",
                }
                return render(request, "admin/usage/customerusage_import_result.html", context)
        else:
            form = UsageCSVUploadForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "opts": self.model._meta,
            "title": "Import Usage Data from CSV",
        }
        return render(request, "admin/usage/customerusage_import.html", context)
