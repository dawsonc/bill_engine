"""
Chart data generation for billing visualizations.

Converts billing results into structured data for Plotly charts.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, time
from decimal import Decimal
from typing import TYPE_CHECKING

import pandas as pd

from billing.adapters import tariff_to_dto
from billing.core.types import DayType, Tariff

if TYPE_CHECKING:
    from billing.services import BillingCalculationResult

# Color palette for charge period overlays
CHARGE_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]


def _get_day_types_for_date(df: pd.DataFrame, target_date: date) -> set[DayType]:
    """
    Determine which day types apply to a specific date based on billing_df flags.

    Args:
        df: DataFrame with is_weekday, is_weekend, is_holiday columns
        target_date: The date to check

    Returns:
        Set of applicable DayType values
    """
    day_df = df[df["interval_start"].dt.date == target_date]
    if day_df.empty:
        return set()

    # Take the first row's flags (they should be consistent for the day)
    row = day_df.iloc[0]
    day_types = set()
    if row.get("is_weekday", False):
        day_types.add(DayType.WEEKDAY)
    if row.get("is_weekend", False):
        day_types.add(DayType.WEEKEND)
    if row.get("is_holiday", False):
        day_types.add(DayType.HOLIDAY)
    return day_types


def _time_to_str(t: time | None, default: str) -> str:
    """Convert time to HH:MM string, or return default if None."""
    if t is None:
        return default
    return t.strftime("%H:%M")


def _rule_applies_to_date(rule, target_date: date, day_types: set[DayType]) -> bool:
    """Check if a single applicability rule applies to the given date."""
    # Check day type
    if rule.day_types and not (rule.day_types & day_types):
        return False

    # Check date range if specified (normalized to month/day)
    if rule.start_date or rule.end_date:
        target_normalized = date(2000, target_date.month, target_date.day)
        if rule.start_date:
            start_normalized = date(2000, rule.start_date.month, rule.start_date.day)
            if target_normalized < start_normalized:
                return False
        if rule.end_date:
            end_normalized = date(2000, rule.end_date.month, rule.end_date.day)
            if target_normalized > end_normalized:
                return False

    return True


def _get_charge_periods(
    tariff: Tariff, target_date: date, day_types: set[DayType]
) -> tuple[list[dict], list[dict]]:
    """
    Extract applicable charge periods for a specific date.

    Args:
        tariff: The tariff DTO with energy and demand charges
        target_date: The date to get periods for
        day_types: Set of DayType values that apply to this date

    Returns:
        Tuple of (energy_periods, demand_periods) where each period is:
        {
            'name': str,
            'start': 'HH:MM',
            'end': 'HH:MM',
            'color': str,
        }
    """
    energy_periods = []
    demand_periods = []

    # Process energy charges
    for i, charge in enumerate(tariff.energy_charges):
        # No rules means charge applies everywhere
        if not charge.applicability_rules:
            energy_periods.append({
                "name": charge.name,
                "start": "00:00",
                "end": "24:00",
                "color": CHARGE_COLORS[i % len(CHARGE_COLORS)],
            })
            continue

        # Check each rule (OR logic - add period for each applicable rule)
        for rule in charge.applicability_rules:
            if _rule_applies_to_date(rule, target_date, day_types):
                energy_periods.append({
                    "name": charge.name,
                    "start": _time_to_str(rule.period_start_local, "00:00"),
                    "end": _time_to_str(rule.period_end_local, "24:00"),
                    "color": CHARGE_COLORS[i % len(CHARGE_COLORS)],
                })

    # Process demand charges
    for i, charge in enumerate(tariff.demand_charges):
        # No rules means charge applies everywhere
        if not charge.applicability_rules:
            demand_periods.append({
                "name": charge.name,
                "start": "00:00",
                "end": "24:00",
                "color": CHARGE_COLORS[(i + 3) % len(CHARGE_COLORS)],
            })
            continue

        # Check each rule (OR logic - add period for each applicable rule)
        for rule in charge.applicability_rules:
            if _rule_applies_to_date(rule, target_date, day_types):
                demand_periods.append({
                    "name": charge.name,
                    "start": _time_to_str(rule.period_start_local, "00:00"),
                    "end": _time_to_str(rule.period_end_local, "24:00"),
                    "color": CHARGE_COLORS[(i + 3) % len(CHARGE_COLORS)],
                })

    return energy_periods, demand_periods


def _find_peak_demand_day(
    df: pd.DataFrame, demand_charge_ids: list[str]
) -> str | None:
    """
    Find the day with highest total demand charges.

    Args:
        df: DataFrame with date column and demand charge columns
        demand_charge_ids: List of demand charge column IDs (UUIDs)

    Returns:
        ISO date string of the peak demand day, or None if no demand charges
    """
    if not demand_charge_ids:
        return None

    # Sum all demand charge columns per day
    daily_demand = df.groupby("date")[demand_charge_ids].sum().sum(axis=1)

    if daily_demand.empty or daily_demand.max() == 0:
        return None

    peak_day = daily_demand.idxmax()
    return peak_day.isoformat()


def get_billing_chart_data(billing_result: BillingCalculationResult) -> dict:
    """
    Generate chart data from billing results.

    Args:
        billing_result: Result from calculate_customer_bill()

    Returns:
        Dictionary with structure:
        {
            'months': ['Jan 2024', 'Feb 2024', ...],
            'stacked_bar': {
                'energy_charges': {'Weekday Energy': [...], ...},
                'demand_charges': {'Peak Demand': [...], ...},
                'customer_charges': {'Service Charge': [...], ...},
            },
            'energy_line': {
                'total': [...],
                'components': {'Weekday Energy': [...], ...}
            },
            'demand_line': {
                'total': [...],
                'components': {'Peak Demand': [...], ...}
            },
            'customer_line': {
                'total': [...],
                'components': {'Service Charge': [...], ...}
            },
            'daily_usage': {
                'dates': ['2024-01-01', '2024-01-02', ...],
                'total_kwh': [...],
                'max_kw': [...],
                'demand_charge_details': {'2024-01-15': [{'name': 'Peak Demand', 'amount': 50.0}], ...},
                'billing_period_ends': ['2024-01-15', '2024-02-15', ...],
            },
        }
    """
    months: list[str] = []

    # Stacked bar data - charges by type
    energy_by_name: dict[str, list[float]] = defaultdict(list)
    demand_by_name: dict[str, list[float]] = defaultdict(list)
    customer_by_name: dict[str, list[float]] = defaultdict(list)

    # Line chart data - totals
    energy_totals: list[float] = []
    demand_totals: list[float] = []
    customer_totals: list[float] = []

    for month_result in billing_result.billing_months:
        # Month label from period end date (the "billing month")
        month_label = month_result.period_end.strftime("%b %Y")
        months.append(month_label)

        # Energy charges
        energy_total = Decimal("0")
        for item in month_result.energy_line_items:
            energy_by_name[item.description].append(float(item.amount_usd))
            energy_total += item.amount_usd
        energy_totals.append(float(energy_total))

        # Demand charges
        demand_total = Decimal("0")
        for item in month_result.demand_line_items:
            demand_by_name[item.description].append(float(item.amount_usd))
            demand_total += item.amount_usd
        demand_totals.append(float(demand_total))

        # Customer charges
        customer_total = Decimal("0")
        for item in month_result.customer_line_items:
            customer_by_name[item.description].append(float(item.amount_usd))
            customer_total += item.amount_usd
        customer_totals.append(float(customer_total))

    # Ensure all charge series have the same length (fill with 0 for missing months)
    num_months = len(months)
    for charges_dict in [energy_by_name, demand_by_name, customer_by_name]:
        for name, values in charges_dict.items():
            while len(values) < num_months:
                values.append(0.0)

    # Daily usage aggregation from billing_df
    df = billing_result.billing_df.copy()
    df["date"] = df["interval_start"].dt.date
    daily = df.groupby("date").agg({"kwh": "sum", "kw": "max"}).reset_index()

    # Convert to lists for JSON serialization
    daily_dates = [d.isoformat() for d in daily["date"]]
    daily_kwh = daily["kwh"].tolist()
    daily_max_kw = daily["kw"].tolist()

    # Find days with non-zero demand charges and their details
    # Maps date -> list of {name, amount} for each charge
    demand_charge_details: dict[str, list[dict]] = defaultdict(list)

    # Get demand charge info from tariff
    tariff_dto = tariff_to_dto(billing_result.tariff)
    # Map charge_id -> charge name
    charge_id_to_name = {
        str(c.charge_id.value): c.name for c in tariff_dto.demand_charges
    }
    demand_charge_ids = list(charge_id_to_name.keys())

    if demand_charge_ids:
        # For each demand charge, sum per day and record non-zero amounts
        for charge_id, charge_name in charge_id_to_name.items():
            daily_charge = df.groupby("date")[charge_id].sum()
            for day, amount in daily_charge.items():
                if amount > 0:
                    demand_charge_details[day.isoformat()].append({
                        "name": charge_name,
                        "amount": round(float(amount), 2),
                    })

    # Collect billing period boundaries for vertical lines
    billing_period_ends: list[str] = []
    for month_result in billing_result.billing_months[:-1]:  # Skip last one (no line after it)
        billing_period_ends.append(month_result.period_end.isoformat())

    # Generate daily detail data for each date
    # tariff_dto already computed above
    available_dates = daily_dates  # Already computed above

    # Find peak demand day
    peak_demand_day = _find_peak_demand_day(df, demand_charge_ids)

    # Build by_date dictionary with interval-level data for each day
    by_date: dict[str, dict] = {}
    for target_date_str in available_dates:
        target_date = date.fromisoformat(target_date_str)

        # Get intervals for this day
        day_df = df[df["date"] == target_date].sort_values("interval_start")

        if day_df.empty:
            by_date[target_date_str] = {
                "timestamps": [],
                "kwh": [],
                "kw": [],
                "energy_periods": [],
                "demand_periods": [],
                "demand_charge_intervals": [],
            }
            continue

        # Get day types for this date
        day_types = _get_day_types_for_date(df, target_date)

        # Get charge periods
        energy_periods, demand_periods = _get_charge_periods(
            tariff_dto, target_date, day_types
        )

        # Convert to JSON-serializable format
        timestamps = day_df["interval_start"].dt.strftime("%Y-%m-%dT%H:%M:%S%z").tolist()

        # Find intervals with non-zero demand charges
        demand_charge_intervals = []
        if demand_charge_ids:
            # Filter to rows with any demand charge > 0 (avoids iterating all rows)
            has_demand_charge = (day_df[demand_charge_ids] > 0).any(axis=1)
            if has_demand_charge.any():
                # Convert filtered rows to dicts for fast iteration (much faster than iterrows)
                intervals_with_charges = day_df.loc[has_demand_charge]
                for record in intervals_with_charges.to_dict("records"):
                    charges_for_interval = [
                        {"name": charge_id_to_name[charge_id], "amount": round(float(record[charge_id]), 2)}
                        for charge_id in demand_charge_ids
                        if record[charge_id] > 0
                    ]
                    demand_charge_intervals.append({
                        "timestamp": record["interval_start"].isoformat(),
                        "kw": float(record["kw"]),
                        "charges": charges_for_interval,
                    })

        by_date[target_date_str] = {
            "timestamps": timestamps,
            "kwh": day_df["kwh"].tolist(),
            "kw": day_df["kw"].tolist(),
            "energy_periods": energy_periods,
            "demand_periods": demand_periods,
            "demand_charge_intervals": demand_charge_intervals,
        }

    return {
        "months": months,
        "stacked_bar": {
            "energy_charges": dict(energy_by_name),
            "demand_charges": dict(demand_by_name),
            "customer_charges": dict(customer_by_name),
        },
        "energy_line": {
            "total": energy_totals,
            "components": dict(energy_by_name),
        },
        "demand_line": {
            "total": demand_totals,
            "components": dict(demand_by_name),
        },
        "customer_line": {
            "total": customer_totals,
            "components": dict(customer_by_name),
        },
        "daily_usage": {
            "dates": daily_dates,
            "total_kwh": daily_kwh,
            "max_kw": daily_max_kw,
            "demand_charge_details": dict(demand_charge_details),
            "billing_period_ends": billing_period_ends,
        },
        "daily_detail": {
            "available_dates": available_dates,
            "peak_demand_day": peak_demand_day,
            "by_date": by_date,
        },
    }
