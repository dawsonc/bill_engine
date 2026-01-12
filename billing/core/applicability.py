"""
Helper functions for deciding when a charge is applicable.
"""

from __future__ import annotations

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
    interval_start_dates = interval_starts.dt.date

    # Permissive approach: if either the start or end time is None, treat it as the
    # beginning or end of the day, respectively
    if rule.period_start:
        rule_mask[~(rule.period_start <= interval_start_times)] = False
    if rule.period_end:
        rule_mask[~(interval_start_times < rule.period_end)] = False

    # Same permissive approach to start and end dates
    if rule.start_date:
        rule_mask[~(rule.start_date <= interval_start_dates)] = False
    if rule.end_date:
        rule_mask[~(interval_start_dates <= rule.end_date)] = False

    return rule_mask
