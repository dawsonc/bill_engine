"""
Helper functions for deciding when a charge is applicable.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .types import ApplicabilityRule, DayType


def construct_applicability_mask(usage: pd.DataFrame, rule: ApplicabilityRule) -> pd.Series[bool]:
    """
    Docstring for construct_applicability_mask

    Args:
        usage: dataframe with columns interval_start, is_weekday, is_weekend, is_holiday
            (other columns are ignored).
        rule: the rule to apply

    Returns:
        A bool series with the same index as the provided dataframe where each row is
        True if the rule applies to that interval.
    """
    # Apply day-of-week rules first, then subtract out-of-bounds times/dates
    rule_mask = pd.Series(False, index=usage.index)
    if DayType.WEEKDAY in rule.day_types:
        rule_mask[usage["is_weekday"]] = True
    if DayType.WEEKEND in rule.day_types:
        rule_mask[usage["is_weekend"]] = True
    if DayType.HOLIDAY in rule.day_types:
        rule_mask[usage["is_holiday"]] = True

    # Make sure we have intervals as datetimes to work with
    interval_starts = pd.to_datetime(usage["interval_start"].copy(), utc=False)
    interval_start_times = interval_starts.dt.time

    # Permissive approach: if either the start or end time is None, treat it as the
    # beginning or end of the day, respectively
    if rule.period_start_local:
        rule_mask[~(rule.period_start_local <= interval_start_times)] = False
    if rule.period_end_local:
        rule_mask[~(interval_start_times < rule.period_end_local)] = False

    # Normalize dates to year 2000 for month/day-only comparison
    # This allows rules to match dates regardless of the actual year
    if rule.start_date or rule.end_date:
        interval_dates_normalized = interval_starts.apply(lambda dt: date(2000, dt.month, dt.day))
        if rule.start_date:
            # Normalize rule start_date to year 2000 as well
            rule_start_normalized = date(2000, rule.start_date.month, rule.start_date.day)
            rule_mask[~(rule_start_normalized <= interval_dates_normalized)] = False
        if rule.end_date:
            # Normalize rule end_date to year 2000 as well
            rule_end_normalized = date(2000, rule.end_date.month, rule.end_date.day)
            rule_mask[~(interval_dates_normalized <= rule_end_normalized)] = False

    return rule_mask
