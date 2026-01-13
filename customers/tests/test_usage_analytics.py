"""
Tests for customer usage data gap analytics.
"""

from datetime import datetime, timedelta
from decimal import Decimal
import zoneinfo

from django.test import TestCase
from django.utils import timezone

from customers.models import Customer
from customers.usage_analytics import (
    MonthlyGapSummary,
    analyze_usage_gaps,
    get_month_boundaries_in_customer_tz,
)
from tariffs.models import Tariff
from utilities.models import Utility
from usage.models import CustomerUsage


class UsageAnalyticsTests(TestCase):
    """Test gap detection logic."""

    def setUp(self):
        """Create test customer and usage data."""
        # Create utility and tariff
        self.utility = Utility.objects.create(name="Test Utility")
        self.tariff = Tariff.objects.create(name="Test Tariff", utility=self.utility)

        # Create customer with 5-minute intervals in US/Pacific timezone
        # Set created_at to 2 years ago so test data falls within customer lifetime
        two_years_ago = timezone.now() - timedelta(days=730)
        self.customer = Customer.objects.create(
            name="Test Customer",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff,
            billing_interval_minutes=5,
        )
        self.customer.created_at = two_years_ago
        self.customer.save()

    def test_analyze_gaps_complete_data(self):
        """Test accurate interval counting with partial complete data."""
        # Create complete usage data for the last 2 hours
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        now = timezone.now()
        start_time = now - timedelta(hours=2)

        # Create intervals every 5 minutes
        current_time = start_time
        intervals_created = 0
        while current_time < now:
            CustomerUsage.objects.create(
                customer=self.customer,
                interval_start_utc=current_time,
                interval_end_utc=current_time + timedelta(minutes=5),
                energy_kwh=Decimal("1.0"),
                peak_demand_kw=Decimal("50.0"),
            )
            current_time += timedelta(minutes=5)
            intervals_created += 1

        # Analyze gaps for the current month
        gaps = analyze_usage_gaps(self.customer, months=1)

        # Should have warnings since we only have 2 hours of data, not a full month
        self.assertGreater(len(gaps), 0)
        current_month_gap = gaps[0]

        # Verify the actual intervals match what we created
        self.assertEqual(current_month_gap.actual_intervals, intervals_created)
        # Expected intervals should be much more than what we created (full month vs 2 hours)
        self.assertGreater(current_month_gap.expected_intervals, intervals_created)
        # Missing intervals should be the difference
        self.assertEqual(
            current_month_gap.missing_intervals,
            current_month_gap.expected_intervals - current_month_gap.actual_intervals,
        )

    def test_analyze_gaps_missing_intervals(self):
        """Test detection of missing intervals."""
        # Create usage data with deliberate gaps
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        now = timezone.now()

        # Create only a few intervals (missing most of the expected data)
        for i in range(10):
            start_time = now - timedelta(minutes=i * 5)
            CustomerUsage.objects.create(
                customer=self.customer,
                interval_start_utc=start_time,
                interval_end_utc=start_time + timedelta(minutes=5),
                energy_kwh=Decimal("1.0"),
                peak_demand_kw=Decimal("50.0"),
            )

        # Analyze gaps for the current month
        gaps = analyze_usage_gaps(self.customer, months=1)

        # Should have warnings for current month
        self.assertGreater(len(gaps), 0)
        current_month_gap = gaps[0]

        # Verify structure
        self.assertIsInstance(current_month_gap, MonthlyGapSummary)
        self.assertGreater(current_month_gap.missing_intervals, 0)
        self.assertEqual(current_month_gap.actual_intervals, 10)
        self.assertTrue(current_month_gap.has_data)
        self.assertGreater(current_month_gap.missing_percentage, 0)

    def test_analyze_gaps_no_data(self):
        """Test month with zero usage records."""
        # Don't create any usage data
        # Analyze gaps for the current month
        gaps = analyze_usage_gaps(self.customer, months=1)

        # Should have warnings for current month with no data
        self.assertGreater(len(gaps), 0)
        current_month_gap = gaps[0]

        # Verify no data flag is set
        self.assertEqual(current_month_gap.actual_intervals, 0)
        self.assertFalse(current_month_gap.has_data)
        self.assertEqual(current_month_gap.missing_percentage, 100.0)

    def test_analyze_gaps_partial_month_customer_created(self):
        """Test customer created mid-month - only count from creation."""
        # Create customer that was created 5 days ago
        five_days_ago = timezone.now() - timedelta(days=5)
        self.customer.created_at = five_days_ago
        self.customer.save()

        # Don't create any usage data
        gaps = analyze_usage_gaps(self.customer, months=1)

        # Should have warnings, but expected intervals should only count from creation date
        self.assertGreater(len(gaps), 0)
        current_month_gap = gaps[0]

        # Expected intervals should be roughly 5 days worth
        # 5 days * 24 hours * 12 intervals/hour = ~1440 intervals
        self.assertLess(
            current_month_gap.expected_intervals, 10000
        )  # Much less than full month
        self.assertGreater(current_month_gap.expected_intervals, 1000)  # But non-zero

    def test_analyze_gaps_partial_month_current(self):
        """Test current incomplete month - only count up to now."""
        # Customer created at beginning of current month
        from datetime import timezone as dt_timezone

        tz = zoneinfo.ZoneInfo(str(self.customer.timezone))
        now_local = timezone.now().astimezone(tz)
        month_start_local = datetime(
            now_local.year, now_local.month, 1, 0, 0, 0, tzinfo=tz
        )
        month_start_utc = month_start_local.astimezone(dt_timezone.utc)

        self.customer.created_at = month_start_utc
        self.customer.save()

        # Don't create any usage data
        gaps = analyze_usage_gaps(self.customer, months=1)

        # Should have warnings for current month
        self.assertGreater(len(gaps), 0)
        current_month_gap = gaps[0]

        # Expected intervals should not include future time
        # Should be less than a full month
        now = timezone.now()
        days_elapsed = (now - month_start_utc).days
        max_expected = days_elapsed * 24 * 12 + 500  # Add buffer
        self.assertLess(current_month_gap.expected_intervals, max_expected)

    def test_analyze_gaps_different_interval_sizes(self):
        """Test with 15-minute and 30-minute intervals."""
        two_years_ago = timezone.now() - timedelta(days=730)

        # Test with 15-minute intervals
        customer_15min = Customer.objects.create(
            name="15min Customer",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff,
            billing_interval_minutes=15,
        )
        customer_15min.created_at = two_years_ago
        customer_15min.save()

        # Create a few intervals
        now = timezone.now()
        for i in range(5):
            start_time = now - timedelta(minutes=i * 15)
            CustomerUsage.objects.create(
                customer=customer_15min,
                interval_start_utc=start_time,
                interval_end_utc=start_time + timedelta(minutes=15),
                energy_kwh=Decimal("1.0"),
                peak_demand_kw=Decimal("50.0"),
            )

        gaps_15 = analyze_usage_gaps(customer_15min, months=1)
        self.assertGreater(len(gaps_15), 0)
        self.assertEqual(gaps_15[0].actual_intervals, 5)

        # Test with 30-minute intervals
        customer_30min = Customer.objects.create(
            name="30min Customer",
            timezone="America/Los_Angeles",
            current_tariff=self.tariff,
            billing_interval_minutes=30,
        )
        customer_30min.created_at = two_years_ago
        customer_30min.save()

        for i in range(5):
            start_time = now - timedelta(minutes=i * 30)
            CustomerUsage.objects.create(
                customer=customer_30min,
                interval_start_utc=start_time,
                interval_end_utc=start_time + timedelta(minutes=30),
                energy_kwh=Decimal("1.0"),
                peak_demand_kw=Decimal("50.0"),
            )

        gaps_30 = analyze_usage_gaps(customer_30min, months=1)
        self.assertGreater(len(gaps_30), 0)
        self.assertEqual(gaps_30[0].actual_intervals, 5)

        # 30-minute intervals should have fewer expected intervals than 15-minute
        # for the same time period
        self.assertLess(
            gaps_30[0].expected_intervals, gaps_15[0].expected_intervals
        )

    def test_get_month_boundaries_count(self):
        """Test correct number of month boundaries returned."""
        boundaries = get_month_boundaries_in_customer_tz(self.customer, months=12)

        # Should return 12 boundaries for 12 months
        self.assertEqual(len(boundaries), 12)

        # Each boundary should be a tuple of 3 items
        for boundary in boundaries:
            self.assertEqual(len(boundary), 3)
            month_start_local, month_start_utc, month_end_utc = boundary
            self.assertIsInstance(month_start_local, datetime)
            self.assertIsInstance(month_start_utc, datetime)
            self.assertIsInstance(month_end_utc, datetime)

    def test_get_month_boundaries_timezone_conversion(self):
        """Test boundaries correctly converted to UTC."""
        boundaries = get_month_boundaries_in_customer_tz(self.customer, months=1)

        self.assertEqual(len(boundaries), 1)
        month_start_local, month_start_utc, month_end_utc = boundaries[0]

        # Local time should be midnight in customer timezone
        self.assertEqual(month_start_local.hour, 0)
        self.assertEqual(month_start_local.minute, 0)

        # UTC time should be offset from local time
        # Pacific time is UTC-8 or UTC-7 depending on DST
        # So UTC time should be 7 or 8 hours ahead
        from datetime import timezone as dt_timezone

        utc_offset_hours = (
            month_start_utc - month_start_local.replace(tzinfo=dt_timezone.utc)
        ).total_seconds() / 3600
        self.assertIn(
            utc_offset_hours, [7.0, 8.0]
        )  # 7 during DST, 8 during standard time

    def test_analyze_gaps_dst_transition(self):
        """Test handling of DST transitions."""
        # Create customer that has been around for over a year
        tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        one_year_ago = timezone.now() - timedelta(days=365)
        self.customer.created_at = one_year_ago
        self.customer.save()

        # Analyze 12 months (will include both DST and standard time)
        gaps = analyze_usage_gaps(self.customer, months=12)

        # Should be able to analyze all months without errors
        # (This mainly tests that DST transitions don't crash the code)
        self.assertGreaterEqual(len(gaps), 0)

        # All gaps should have valid data
        for gap in gaps:
            self.assertIsInstance(gap.expected_intervals, int)
            self.assertGreater(gap.expected_intervals, 0)
            self.assertIsInstance(gap.actual_intervals, int)
            self.assertGreaterEqual(gap.actual_intervals, 0)

    def test_month_boundaries_ordering(self):
        """Test that month boundaries are ordered newest to oldest."""
        boundaries = get_month_boundaries_in_customer_tz(self.customer, months=3)

        self.assertEqual(len(boundaries), 3)

        # First boundary should be current month
        # Second should be previous month, etc.
        for i in range(len(boundaries) - 1):
            current_month_start = boundaries[i][0]
            next_month_start = boundaries[i + 1][0]
            # Current month should be after next month (newest first)
            self.assertGreater(current_month_start, next_month_start)

    def test_analyze_gaps_only_returns_months_with_gaps(self):
        """Test that only months with missing data are returned."""
        # Create complete data for last hour
        now = timezone.now()
        start_time = now - timedelta(hours=1)
        current_time = start_time

        while current_time < now:
            CustomerUsage.objects.create(
                customer=self.customer,
                interval_start_utc=current_time,
                interval_end_utc=current_time + timedelta(minutes=5),
                energy_kwh=Decimal("1.0"),
                peak_demand_kw=Decimal("50.0"),
            )
            current_time += timedelta(minutes=5)

        # Analyze 12 months
        gaps = analyze_usage_gaps(self.customer, months=12)

        # Should have warnings for all months except we only have 1 hour of data
        # So the current month will show as having gaps
        self.assertGreater(len(gaps), 0)

        # All returned gaps should have missing_intervals > 0
        for gap in gaps:
            self.assertGreater(gap.missing_intervals, 0)
