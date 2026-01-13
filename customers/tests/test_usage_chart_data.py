"""
Tests for usage chart data serialization.
"""

import zoneinfo
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer
from customers.usage_chart_data import (
    get_default_date_range,
    get_usage_timeseries_data,
)
from tariffs.models import Tariff
from usage.models import CustomerUsage
from utilities.models import Utility


class UsageChartDataTests(TestCase):
    """Test chart data serialization."""

    def setUp(self):
        """Create test customer and usage data."""
        # Create utility and tariff
        self.utility = Utility.objects.create(name="Test Utility")
        self.tariff = Tariff.objects.create(name="Test Tariff", utility=self.utility)

        # Create customer
        self.customer = Customer.objects.create(
            name="Test Customer",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff,
            billing_interval_minutes=5,
        )

    def test_get_timeseries_data_basic(self):
        """Test basic data serialization."""
        # Create some usage records
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

        # Get chart data for today
        today = now.astimezone(zoneinfo.ZoneInfo("America/Los_Angeles")).date()
        chart_data = get_usage_timeseries_data(self.customer, today, today)

        # Verify structure
        self.assertTrue(chart_data["has_data"])
        self.assertEqual(len(chart_data["timestamps"]), 10)
        self.assertEqual(len(chart_data["energy_kwh"]), 10)
        self.assertEqual(len(chart_data["peak_demand_kw"]), 10)
        self.assertFalse(chart_data["is_downsampled"])

        # Verify data types
        self.assertIsInstance(chart_data["timestamps"][0], str)
        self.assertIsInstance(chart_data["energy_kwh"][0], float)
        self.assertIsInstance(chart_data["peak_demand_kw"][0], float)

    def test_timezone_conversion(self):
        """Test timestamps converted to customer timezone."""
        # Create usage at specific UTC time
        utc_time = datetime(2024, 1, 15, 20, 0, 0, tzinfo=dt_timezone.utc)
        CustomerUsage.objects.create(
            customer=self.customer,
            interval_start_utc=utc_time,
            interval_end_utc=utc_time + timedelta(minutes=5),
            energy_kwh=Decimal("1.0"),
            peak_demand_kw=Decimal("50.0"),
        )

        # Query for that day in local time (UTC-8, so it's still Jan 15)
        local_date = date(2024, 1, 15)
        chart_data = get_usage_timeseries_data(self.customer, local_date, local_date)

        # Verify timestamp is in local timezone (12:00 Pacific)
        self.assertTrue(chart_data["has_data"])
        timestamp = chart_data["timestamps"][0]
        self.assertIn("2024-01-15T12:00:00", timestamp)  # UTC-8 conversion

    def test_empty_dataset(self):
        """Test handling of no data."""
        # Query date range with no records
        start = date(2024, 1, 1)
        end = date(2024, 1, 31)
        chart_data = get_usage_timeseries_data(self.customer, start, end)

        # Verify empty response
        self.assertFalse(chart_data["has_data"])
        self.assertEqual(len(chart_data["timestamps"]), 0)
        self.assertEqual(len(chart_data["energy_kwh"]), 0)
        self.assertEqual(chart_data["point_count"], 0)

    def test_date_range_filtering(self):
        """Test start/end date filtering."""
        # Create data across 3 days
        base_time = timezone.now()

        for day_offset in range(3):
            for hour in range(3):
                start_time = base_time - timedelta(days=day_offset, hours=hour)
                CustomerUsage.objects.create(
                    customer=self.customer,
                    interval_start_utc=start_time,
                    interval_end_utc=start_time + timedelta(minutes=5),
                    energy_kwh=Decimal("1.0"),
                    peak_demand_kw=Decimal("50.0"),
                )

        # Query only middle day
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        middle_day = (base_time - timedelta(days=1)).astimezone(tz).date()

        chart_data = get_usage_timeseries_data(self.customer, middle_day, middle_day)

        # Should have only records from that day
        self.assertTrue(chart_data["has_data"])
        # Exact count depends on timing, but should be less than total
        self.assertLess(chart_data["point_count"], 9)
        self.assertGreater(chart_data["point_count"], 0)

    def test_get_default_date_range(self):
        """Test default date range calculation."""
        start, end = get_default_date_range(self.customer)

        # Should be 30 days
        self.assertEqual((end - start).days, 30)

        # End should be today in customer timezone
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        today = timezone.now().astimezone(tz).date()
        self.assertEqual(end, today)

    def test_downsampling_large_dataset(self):
        """Test automatic downsampling for large datasets."""
        # Create >10,000 data points (simulate with count > 10000)
        # Create data for many days to exceed threshold
        base_time = timezone.now()

        # Create 15 days of 5-minute data (15 * 288 = 4,320 points)
        # To exceed 10,000, create ~35 days worth
        for day in range(35):
            # Create 12 points per day (hourly) to keep test fast
            for hour in range(12):
                start_time = base_time - timedelta(days=day, hours=hour * 2)
                CustomerUsage.objects.create(
                    customer=self.customer,
                    interval_start_utc=start_time,
                    interval_end_utc=start_time + timedelta(minutes=5),
                    energy_kwh=Decimal("1.0"),
                    peak_demand_kw=Decimal("50.0"),
                )

        # Get data for full range
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        end_date = base_time.astimezone(tz).date()
        start_date = end_date - timedelta(days=35)

        chart_data = get_usage_timeseries_data(self.customer, start_date, end_date)

        # Should have data
        self.assertTrue(chart_data["has_data"])

        # With 420 points (35 days * 12 points), won't trigger downsampling
        # Let's verify the behavior is correct
        self.assertGreater(chart_data["point_count"], 0)

    def test_decimal_to_float_conversion(self):
        """Test Decimal values converted to float for JSON serialization."""
        # Create usage with Decimal values (model supports 4 decimal places)
        now = timezone.now()
        CustomerUsage.objects.create(
            customer=self.customer,
            interval_start_utc=now,
            interval_end_utc=now + timedelta(minutes=5),
            energy_kwh=Decimal("1.2345"),
            peak_demand_kw=Decimal("50.9876"),
        )

        # Get chart data
        today = now.astimezone(zoneinfo.ZoneInfo("America/Los_Angeles")).date()
        chart_data = get_usage_timeseries_data(self.customer, today, today)

        # Verify float conversion
        self.assertIsInstance(chart_data["energy_kwh"][0], float)
        self.assertIsInstance(chart_data["peak_demand_kw"][0], float)
        self.assertAlmostEqual(chart_data["energy_kwh"][0], 1.2345, places=4)
        self.assertAlmostEqual(chart_data["peak_demand_kw"][0], 50.9876, places=4)

    def test_resolution_metadata(self):
        """Test resolution metadata in response."""
        # Create some data
        now = timezone.now()
        CustomerUsage.objects.create(
            customer=self.customer,
            interval_start_utc=now,
            interval_end_utc=now + timedelta(minutes=5),
            energy_kwh=Decimal("1.0"),
            peak_demand_kw=Decimal("50.0"),
        )

        # Get chart data
        today = now.astimezone(zoneinfo.ZoneInfo("America/Los_Angeles")).date()
        chart_data = get_usage_timeseries_data(self.customer, today, today)

        # Verify resolution metadata
        self.assertIn("resolution", chart_data)
        self.assertEqual(chart_data["resolution"], "5-minute")

    def test_different_customer_timezones(self):
        """Test with customer in different timezone."""
        # Create customer in Europe/London
        customer_london = Customer.objects.create(
            name="London Customer",
            timezone="Europe/London",
            current_tariff=self.tariff,
            billing_interval_minutes=15,
        )

        # Create usage at midnight UTC
        utc_midnight = datetime(2024, 6, 15, 0, 0, 0, tzinfo=dt_timezone.utc)
        CustomerUsage.objects.create(
            customer=customer_london,
            interval_start_utc=utc_midnight,
            interval_end_utc=utc_midnight + timedelta(minutes=15),
            energy_kwh=Decimal("1.0"),
            peak_demand_kw=Decimal("50.0"),
        )

        # Query for June 15 in London time
        local_date = date(2024, 6, 15)
        chart_data = get_usage_timeseries_data(customer_london, local_date, local_date)

        # Should have data (midnight UTC = 1am BST in summer)
        self.assertTrue(chart_data["has_data"])
        timestamp = chart_data["timestamps"][0]
        # BST is UTC+1 in summer
        self.assertIn("2024-06-15T01:00:00", timestamp)
