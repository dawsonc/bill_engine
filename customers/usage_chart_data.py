"""
Chart data serialization for customer usage visualization.
"""

import zoneinfo
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.db.models import Max, Sum
from django.db.models.functions import TruncHour
from django.utils import timezone

from usage.models import CustomerUsage


def get_usage_timeseries_data(customer, start_date_local, end_date_local):
    """
    Query and serialize usage data for Plotly time series chart.

    Args:
        customer: Customer instance
        start_date_local: datetime.date in customer's timezone (inclusive)
        end_date_local: datetime.date in customer's timezone (inclusive)

    Returns:
        dict with structure:
        {
            'timestamps': [...],      # ISO format strings in customer TZ
            'energy_kwh': [...],      # Float values
            'peak_demand_kw': [...],  # Float values
            'has_data': bool,
            'point_count': int,
            'is_downsampled': bool,   # True if aggregated to hourly
            'resolution': str         # '5-minute' or 'hourly'
        }
    """
    # Convert local dates to UTC for database query
    customer_tz = zoneinfo.ZoneInfo(str(customer.timezone))

    # Start: midnight on start_date_local
    start_local = datetime.combine(start_date_local, datetime.min.time(), tzinfo=customer_tz)
    start_utc = start_local.astimezone(dt_timezone.utc)

    # End: midnight on day after end_date_local (to make end_date inclusive)
    end_local = datetime.combine(
        end_date_local + timedelta(days=1), datetime.min.time(), tzinfo=customer_tz
    )
    end_utc = end_local.astimezone(dt_timezone.utc)

    # Query usage records in date range
    usage_queryset = CustomerUsage.objects.filter(
        customer=customer,
        interval_start_utc__gte=start_utc,
        interval_start_utc__lt=end_utc,
    ).order_by("interval_start_utc")

    # Check count and decide whether to downsample
    count = usage_queryset.count()

    if count == 0:
        # No data in range
        return {
            "has_data": False,
            "timestamps": [],
            "energy_kwh": [],
            "peak_demand_kw": [],
            "point_count": 0,
            "is_downsampled": False,
            "resolution": "none",
        }

    # Downsample if more than 10,000 points
    if count > 10000:
        # Aggregate to hourly intervals
        hourly_data = (
            usage_queryset.annotate(hour=TruncHour("interval_start_utc"))
            .values("hour")
            .annotate(energy=Sum("energy_kwh"), peak=Max("peak_demand_kw"))
            .order_by("hour")
        )

        # Convert to lists, with timezone conversion
        timestamps = []
        energy_kwh = []
        peak_demand_kw = []

        for record in hourly_data:
            hour_utc = record["hour"]
            hour_local = hour_utc.astimezone(customer_tz)
            timestamps.append(hour_local.isoformat())
            energy_kwh.append(float(record["energy"]))
            peak_demand_kw.append(float(record["peak"]))

        return {
            "has_data": True,
            "timestamps": timestamps,
            "energy_kwh": energy_kwh,
            "peak_demand_kw": peak_demand_kw,
            "point_count": len(timestamps),
            "is_downsampled": True,
            "resolution": "hourly",
        }
    else:
        # Use full resolution data
        usage_records = usage_queryset.only("interval_start_utc", "energy_kwh", "peak_demand_kw")

        timestamps = []
        energy_kwh = []
        peak_demand_kw = []

        for record in usage_records:
            timestamp_local = record.interval_start_utc.astimezone(customer_tz)
            timestamps.append(timestamp_local.isoformat())
            energy_kwh.append(float(record.energy_kwh))
            peak_demand_kw.append(float(record.peak_demand_kw))

        return {
            "has_data": True,
            "timestamps": timestamps,
            "energy_kwh": energy_kwh,
            "peak_demand_kw": peak_demand_kw,
            "point_count": len(timestamps),
            "is_downsampled": False,
            "resolution": f"{customer.billing_interval_minutes}-minute",
        }


def get_default_date_range(customer):
    """
    Get default date range (last 30 days) in customer's local timezone.

    Returns:
        tuple: (start_date, end_date) as datetime.date objects
    """
    customer_tz = zoneinfo.ZoneInfo(str(customer.timezone))
    now_local = timezone.now().astimezone(customer_tz)
    end_date = now_local.date()
    start_date = end_date - timedelta(days=30)
    return start_date, end_date
