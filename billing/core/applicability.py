"""
Helper functions for deciding when a charge is applicable.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from .types import ApplicabilityRule, DayType


def _construct_single_rule_mask(
    usage: pd.DataFrame, rule: ApplicabilityRule
) -> pd.Series[bool]:
    """
    Construct applicability mask for a single rule.

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
        # Vectorized date normalization: create timestamps with year 2000
        interval_dates_normalized = pd.to_datetime(
            {"year": 2000, "month": interval_starts.dt.month, "day": interval_starts.dt.day}
        )
        if rule.start_date:
            # Normalize rule start_date to year 2000 as well
            rule_start_normalized = pd.Timestamp(
                year=2000, month=rule.start_date.month, day=rule.start_date.day
            )
            rule_mask &= interval_dates_normalized >= rule_start_normalized
        if rule.end_date:
            # Normalize rule end_date to year 2000 as well
            rule_end_normalized = pd.Timestamp(
                year=2000, month=rule.end_date.month, day=rule.end_date.day
            )
            rule_mask &= interval_dates_normalized <= rule_end_normalized

    return rule_mask


def construct_applicability_mask(
    usage: pd.DataFrame,
    rules: tuple[ApplicabilityRule, ...],
) -> pd.Series[bool]:
    """
    Construct applicability mask for multiple rules combined with OR logic.

    When multiple rules are provided, the charge applies if ANY rule matches
    the interval. If no rules are provided, the charge applies everywhere.

    Args:
        usage: dataframe with columns interval_start, is_weekday, is_weekend, is_holiday
            (other columns are ignored).
        rules: tuple of ApplicabilityRule DTOs. Empty tuple means no constraints
            (charge applies to all intervals).

    Returns:
        A bool series with the same index as the provided dataframe where each row is
        True if any rule applies to that interval (or all True if no rules).
    """
    if not rules:
        # No rules means charge applies everywhere
        return pd.Series(True, index=usage.index)

    # Combine all rule masks with OR logic
    combined_mask = pd.Series(False, index=usage.index)
    for rule in rules:
        rule_mask = _construct_single_rule_mask(usage, rule)
        combined_mask = combined_mask | rule_mask

    return combined_mask
