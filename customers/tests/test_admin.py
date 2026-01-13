"""
Integration tests for customer admin interface with usage gap warnings.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from customers.usage_analytics import MonthlyGapSummary
from tariffs.models import Tariff
from utilities.models import Utility
from usage.models import CustomerUsage


class CustomerAdminWarningsTests(TestCase):
    """Test usage gap warnings in admin interface."""

    def setUp(self):
        """Create admin user and test data."""
        # Create superuser
        self.admin_user = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="admin123"
        )

        # Create utility and tariff
        self.utility = Utility.objects.create(name="Test Utility")
        self.tariff = Tariff.objects.create(name="Test Tariff", utility=self.utility)

        # Create customer with usage data gaps
        two_years_ago = timezone.now() - timedelta(days=730)
        self.customer_with_gaps = Customer.objects.create(
            name="Customer With Gaps",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff,
            billing_interval_minutes=5,
        )
        self.customer_with_gaps.created_at = two_years_ago
        self.customer_with_gaps.save()

        # Create only a few intervals (missing most data)
        now = timezone.now()
        for i in range(10):
            start_time = now - timedelta(minutes=i * 5)
            CustomerUsage.objects.create(
                customer=self.customer_with_gaps,
                interval_start_utc=start_time,
                interval_end_utc=start_time + timedelta(minutes=5),
                energy_kwh=Decimal("1.0"),
                peak_demand_kw=Decimal("50.0"),
            )

        # Create customer with no data
        self.customer_no_data = Customer.objects.create(
            name="Customer No Data",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff,
            billing_interval_minutes=5,
        )
        self.customer_no_data.created_at = two_years_ago
        self.customer_no_data.save()

    def test_change_form_displays_warnings(self):
        """Test warnings appear in customer detail page."""
        # Login as admin
        self.client.login(username="admin", password="admin123")

        # Navigate to customer change form
        url = reverse("admin:customers_customer_change", args=[self.customer_with_gaps.id])
        response = self.client.get(url)

        # Assert response is successful
        self.assertEqual(response.status_code, 200)

        # Assert warning section is present
        self.assertContains(response, "usage-gap-warnings")
        self.assertContains(response, "Usage Data Warnings")
        self.assertContains(response, "Missing usage data detected")

        # Assert gap data is shown
        self.assertContains(response, "Missing Intervals")
        self.assertContains(response, "Percentage Missing")

    def test_change_form_handles_analytics_error(self):
        """Test graceful degradation when analytics fails."""
        # Login as admin
        self.client.login(username="admin", password="admin123")

        # Mock analyze_usage_gaps to raise exception
        with patch("customers.usage_analytics.analyze_usage_gaps") as mock_analyze:
            mock_analyze.side_effect = Exception("Test error")

            # Navigate to customer change form
            url = reverse("admin:customers_customer_change", args=[self.customer_with_gaps.id])
            response = self.client.get(url)

            # Page should still load successfully
            self.assertEqual(response.status_code, 200)

            # Warning section should not appear (empty list)
            self.assertNotContains(response, "usage-gap-warnings")

    def test_add_form_no_warnings(self):
        """Test warnings only on existing customers, not add form."""
        # Login as admin
        self.client.login(username="admin", password="admin123")

        # Navigate to add customer form
        url = reverse("admin:customers_customer_add")
        response = self.client.get(url)

        # Assert response is successful
        self.assertEqual(response.status_code, 200)

        # Assert no warning section
        self.assertNotContains(response, "usage-gap-warnings")
        self.assertNotContains(response, "Usage Data Warnings")

    def test_change_form_shows_no_data_warning(self):
        """Test warnings for customer with no data at all."""
        # Login as admin
        self.client.login(username="admin", password="admin123")

        # Navigate to customer change form
        url = reverse("admin:customers_customer_change", args=[self.customer_no_data.id])
        response = self.client.get(url)

        # Assert response is successful
        self.assertEqual(response.status_code, 200)

        # Assert warning section is present
        self.assertContains(response, "usage-gap-warnings")
        self.assertContains(response, "Usage Data Warnings")

        # Assert 100% missing
        self.assertContains(response, "100.0%")

    def test_change_form_with_mock_warnings(self):
        """Test change form correctly renders mock warning data."""
        # Login as admin
        self.client.login(username="admin", password="admin123")

        # Create mock warnings
        from datetime import datetime
        import zoneinfo

        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        mock_warnings = [
            MonthlyGapSummary(
                month_start=datetime(2024, 1, 1, tzinfo=tz),
                month_label="January 2024",
                expected_intervals=8928,
                actual_intervals=8778,
                missing_intervals=150,
                missing_percentage=1.68,
                has_data=True,
            ),
            MonthlyGapSummary(
                month_start=datetime(2023, 12, 1, tzinfo=tz),
                month_label="December 2023",
                expected_intervals=8928,
                actual_intervals=0,
                missing_intervals=8928,
                missing_percentage=100.0,
                has_data=False,
            ),
        ]

        # Mock analyze_usage_gaps to return our mock warnings
        with patch("customers.usage_analytics.analyze_usage_gaps") as mock_analyze:
            mock_analyze.return_value = mock_warnings

            # Navigate to customer change form
            url = reverse("admin:customers_customer_change", args=[self.customer_with_gaps.id])
            response = self.client.get(url)

            # Assert response is successful
            self.assertEqual(response.status_code, 200)

            # Assert January 2024 data
            self.assertContains(response, "January 2024")
            self.assertContains(response, "150")
            self.assertContains(response, "1.7%")  # floatformat:1 rounds 1.68 to 1.7

            # Assert December 2023 data (no data month)
            self.assertContains(response, "December 2023")
            self.assertContains(response, "8,928")  # intcomma formatting
            self.assertContains(response, "100.0%")
            # Check for no-data class (red background)
            self.assertContains(response, 'class="no-data"')

    def test_unauthorized_user_cannot_access(self):
        """Test that non-admin users cannot access customer admin pages."""
        # Create regular user (not admin)
        regular_user = User.objects.create_user(
            username="regular", email="regular@test.com", password="regular123"
        )

        # Login as regular user
        self.client.login(username="regular", password="regular123")

        # Try to navigate to customer change form
        url = reverse("admin:customers_customer_change", args=[self.customer_with_gaps.id])
        response = self.client.get(url)

        # Should redirect to login (not authorized)
        self.assertEqual(response.status_code, 302)


class CustomerAdminChartTests(TestCase):
    """Test chart integration in admin."""

    def setUp(self):
        """Create admin user and test data."""
        # Create superuser
        self.admin_user = User.objects.create_superuser(
            username="admin", email="admin@test.com", password="admin123"
        )

        # Create utility, tariff, and customer
        utility = Utility.objects.create(name="Test Utility")
        tariff = Tariff.objects.create(name="Test Tariff", utility=utility)
        self.customer = Customer.objects.create(
            name="Test Customer",
            timezone="America/Los_Angeles",
            current_tariff=tariff,
            billing_interval_minutes=5,
        )

        # Create some usage data
        now = timezone.now()
        for i in range(10):
            start_time = now - timedelta(minutes=i * 5)
            CustomerUsage.objects.create(
                customer=self.customer,
                interval_start_utc=start_time,
                interval_end_utc=start_time + timedelta(minutes=5),
                energy_kwh=Decimal("1.5"),
                peak_demand_kw=Decimal("50.0"),
            )

    def test_chart_displays_on_change_form(self):
        """Test chart section appears on customer detail."""
        # Login as admin
        self.client.login(username="admin", password="admin123")

        # GET customer change form
        url = reverse("admin:customers_customer_change", args=[self.customer.id])
        response = self.client.get(url)

        # Assert response successful
        self.assertEqual(response.status_code, 200)

        # Assert chart elements present
        self.assertContains(response, "usage-chart-container")
        self.assertContains(response, "Usage Time Series")
        self.assertContains(response, "usage-timeseries-chart")
        self.assertContains(response, "plot.ly/plotly-2.27.0.min.js")

    def test_chart_not_on_add_form(self):
        """Test chart only on existing customers."""
        # Login as admin
        self.client.login(username="admin", password="admin123")

        # GET add customer form
        url = reverse("admin:customers_customer_add")
        response = self.client.get(url)

        # Assert no chart section
        self.assertNotContains(response, "usage-chart-container")
        self.assertNotContains(response, "Usage Time Series")

    def test_date_filter_updates_chart(self):
        """Test GET params update chart data."""
        # Login as admin
        self.client.login(username="admin", password="admin123")

        # GET with date parameters
        url = reverse("admin:customers_customer_change", args=[self.customer.id])
        response = self.client.get(url, {"start_date": "2024-01-01", "end_date": "2024-01-31"})

        # Assert form populated with dates
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2024-01-01")
        self.assertContains(response, "2024-01-31")
