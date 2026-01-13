"""
Shared fixtures for billing tests.

Consolidates DataFrame creation and Django model fixtures used across test files.
"""

from datetime import date

import pandas as pd
import pytest

from billing.core.util import _derive_calendar_months, _trim_to_date_range
from tariffs.models import Tariff
from utilities.models import Utility


@pytest.fixture
def usage_df_factory():
    """Factory fixture for creating usage DataFrames with flexible configurations.

    This replaces:
    - create_valid_usage_df() from test_data.py
    - create_usage_with_day_types() from test_applicability.py
    - create_multi_day_usage() from test_applicability.py

    Returns a factory function that creates DataFrames with configurable:
    - Time period (start, periods, frequency)
    - Timezone
    - Usage values (kwh, kw)
    - Day type flags (auto-detect from date or explicit override)
    """

    def _create_usage_df(
        start: str = "2024-01-01 00:00:00",
        periods: int = 4,
        freq: str = "15min",
        tz: str = "US/Pacific",
        kwh: float = 10.5,
        kw: float = 42.0,
        is_weekday: bool | list | None = None,
        is_weekend: bool | list | None = None,
        is_holiday: bool | list | None = None,
        billing_periods: list[tuple[date, date]] | None = None,
    ) -> pd.DataFrame:
        """Create usage DataFrame with configurable parameters.

        Args:
            start: ISO format start datetime string
            periods: Number of intervals to create
            freq: Pandas frequency string (e.g., "15min", "1h")
            tz: Timezone name (e.g., "US/Pacific")
            kwh: Energy usage value (scalar or will be repeated)
            kw: Demand value (scalar or will be repeated)
            is_weekday: If None, auto-detect from date. If bool, use for all periods.
                       If list, use provided values.
            is_weekend: If None, auto-detect from date. If bool, use for all periods.
                       If list, use provided values.
            is_holiday: If None, default to False for all. If bool, use for all periods.
                       If list, use provided values.
            billing_periods: Optional list of (start_date, end_date) tuples defining
                billing periods. Both dates are inclusive. If None, uses calendar months
                derived from the usage data.

        Returns:
            DataFrame with columns: interval_start, interval_end, kwh, kw,
                                   is_weekday, is_weekend, is_holiday
        """
        interval_starts = pd.date_range(start=start, periods=periods, freq=freq, tz=tz)

        # Auto-calculate day types from dates if not specified
        if is_weekday is None and is_weekend is None:
            # Monday = 0, Sunday = 6
            day_of_week = interval_starts.dayofweek
            is_weekday = (day_of_week >= 0) & (day_of_week <= 4)  # Mon-Fri
            is_weekend = (day_of_week >= 5) & (day_of_week <= 6)  # Sat-Sun
        else:
            # Use explicit values or default to False
            if is_weekday is None:
                is_weekday = [False] * periods
            elif isinstance(is_weekday, bool):
                is_weekday = [is_weekday] * periods

            if is_weekend is None:
                is_weekend = [False] * periods
            elif isinstance(is_weekend, bool):
                is_weekend = [is_weekend] * periods

        # Handle is_holiday
        if is_holiday is None:
            is_holiday = [False] * periods
        elif isinstance(is_holiday, bool):
            is_holiday = [is_holiday] * periods

        usage = pd.DataFrame(
            {
                "interval_start": interval_starts,
                "interval_end": interval_starts + pd.Timedelta(freq),
                "kwh": kwh,
                "kw": kw,
                "is_weekday": is_weekday,
                "is_weekend": is_weekend,
                "is_holiday": is_holiday,
            }
        )

        # add billing periods

        # If billing_periods not provided, derive from calendar months in the data
        if billing_periods is None:
            billing_periods = _derive_calendar_months(usage)

        # Trim the data down to just the billing periods
        billing_start_date = min(period[0] for period in billing_periods)
        billing_end_date = max(period[1] for period in billing_periods)
        usage = _trim_to_date_range(usage, billing_start_date, billing_end_date)

        # Label with billing months
        usage["billing_period"] = None
        for period_start, period_end in billing_periods:
            period_str = f"{period_start:%Y-%m} -- {period_end:%Y-%m}"
            mask = (usage["interval_start"].dt.date >= period_start) & (
                usage["interval_start"].dt.date <= period_end
            )
            usage.loc[mask, "billing_period"] = period_str

        return usage

    return _create_usage_df


@pytest.fixture
def utility(db):
    """Create a test utility.

    Replaces setUp() methods in test_adapters.py test classes.
    """
    return Utility.objects.create(name="Test Utility")


@pytest.fixture
def tariff(utility):
    """Create a test tariff with utility dependency.

    Replaces setUp() methods in test_adapters.py test classes.
    """
    return Tariff.objects.create(utility=utility, name="Test Tariff")


@pytest.fixture
def hourly_day_usage(usage_df_factory):
    """24 hours of hourly data for a single day (January 1, 2024).

    Commonly used for time-of-day filtering tests.
    """
    return usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=24,
        freq="1h",
        is_weekday=True,
        is_weekend=False,
    )


@pytest.fixture
def full_week_usage(usage_df_factory):
    """Full week of hourly intervals (Mon-Sun starting Monday, January 1, 2024).

    Day types auto-detected from dates.
    Commonly used for day type filtering tests.
    """
    return usage_df_factory(
        start="2024-01-01 00:00:00",  # Monday
        periods=7 * 24,  # 7 days * 24 hours
        freq="1h",
    )


@pytest.fixture
def month_usage(usage_df_factory):
    """Full month of hourly data (January 2024 - 31 days).

    Commonly used for date range filtering tests.
    """
    return usage_df_factory(
        start="2024-01-01 00:00:00",
        periods=31 * 24,  # 31 days * 24 hours
        freq="1h",
        is_weekday=True,
        is_weekend=False,
    )
