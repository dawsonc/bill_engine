"""
Analytics for customer usage data quality.

Provides functions to detect and analyze gaps in usage data.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
import zoneinfo

from django.utils import timezone

from usage.models import CustomerUsage


@dataclass
class MonthlyGapSummary:
    """Summary of missing intervals for a specific month."""

    month_start: datetime  # First day of month in customer timezone
    month_label: str  # e.g., "January 2024"
    expected_intervals: int  # Expected number of intervals
    actual_intervals: int  # Actual records in database
    missing_intervals: int  # expected - actual
    missing_percentage: float  # (missing / expected) * 100
    has_data: bool  # False if no data at all


def get_month_boundaries_in_customer_tz(
    customer, months: int = 12
) -> list[tuple[datetime, datetime, datetime]]:
    """
    Get month boundaries in customer's timezone for the last N months.

    Returns list of (month_start_local, month_start_utc, month_end_utc) tuples.
    All times converted to UTC for database queries (handles DST correctly).

    Args:
        customer: Customer instance
        months: Number of months to analyze (default: 12)

    Returns:
        List of (month_start_local, month_start_utc, month_end_utc) tuples,
        ordered from newest to oldest month.
    """
    customer_tz = zoneinfo.ZoneInfo(str(customer.timezone))
    now_utc = timezone.now()
    now_local = now_utc.astimezone(customer_tz)

    boundaries = []

    # Iterate through last N months
    for i in range(months):
        # Calculate month start in local timezone
        # Go back i months from current month
        year = now_local.year
        month = now_local.month - i

        # Handle year boundary
        while month <= 0:
            month += 12
            year -= 1

        # First day of the month at midnight in customer timezone
        month_start_local = datetime(year, month, 1, 0, 0, 0, tzinfo=customer_tz)

        # First day of next month
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1

        month_end_local = datetime(
            next_year, next_month, 1, 0, 0, 0, tzinfo=customer_tz
        )

        # Convert to UTC for database queries
        month_start_utc = month_start_local.astimezone(dt_timezone.utc)
        month_end_utc = month_end_local.astimezone(dt_timezone.utc)

        boundaries.append((month_start_local, month_start_utc, month_end_utc))

    return boundaries


def analyze_usage_gaps(customer, months: int = 12) -> list[MonthlyGapSummary]:
    """
    Analyze usage data gaps for a customer over the last N months.

    Returns list of MonthlyGapSummary objects for months with missing data,
    sorted newest first. Uses UTC for all calculations (DST-safe).

    Args:
        customer: Customer instance
        months: Number of months to analyze (default: 12)

    Returns:
        List of MonthlyGapSummary objects (only months with gaps)
    """
    boundaries = get_month_boundaries_in_customer_tz(customer, months)
    now_utc = timezone.now()

    gap_summaries = []

    for month_start_local, month_start_utc, month_end_utc in boundaries:
        # Determine effective range for this month
        # (handle customer created mid-month and current incomplete month)
        effective_start_utc = max(customer.created_at, month_start_utc)
        effective_end_utc = min(now_utc, month_end_utc)

        # Skip if the customer didn't exist yet or if range is invalid
        if effective_start_utc >= effective_end_utc:
            continue

        # Calculate expected number of intervals
        month_duration = effective_end_utc - effective_start_utc
        total_minutes = int(month_duration.total_seconds() / 60)
        expected_intervals = total_minutes // customer.billing_interval_minutes

        # Skip if no intervals expected (e.g., customer created at end of month)
        if expected_intervals == 0:
            continue

        # Query actual number of intervals in database
        actual_intervals = CustomerUsage.objects.filter(
            customer=customer,
            interval_start_utc__gte=effective_start_utc,
            interval_start_utc__lt=effective_end_utc,
        ).count()

        # Calculate missing intervals
        missing_intervals = expected_intervals - actual_intervals

        # Only include months with missing data
        if missing_intervals > 0:
            missing_percentage = (missing_intervals / expected_intervals) * 100

            # Check if there's any data at all in this month
            has_data = actual_intervals > 0

            summary = MonthlyGapSummary(
                month_start=month_start_local,
                month_label=month_start_local.strftime("%B %Y"),
                expected_intervals=expected_intervals,
                actual_intervals=actual_intervals,
                missing_intervals=missing_intervals,
                missing_percentage=missing_percentage,
                has_data=has_data,
            )

            gap_summaries.append(summary)

    return gap_summaries
