"""
Chart data generation for billing visualizations.

Converts billing results into structured data for Plotly charts.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from billing.services import BillingCalculationResult


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
                'peak_demand_days': ['2024-01-15', ...],  # days with peak kW
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

    # Find days with peak demand that caused demand charges
    peak_demand_days: set[str] = set()
    for month_result in billing_result.billing_months:
        # Check if this month has non-zero demand charges
        has_demand_charges = any(
            item.amount_usd > 0 for item in month_result.demand_line_items
        )
        if has_demand_charges:
            # Filter to this billing period
            period_mask = (daily["date"] >= month_result.period_start) & (
                daily["date"] <= month_result.period_end
            )
            period_daily = daily[period_mask]
            if not period_daily.empty:
                # Find the day with max kW in this period
                max_kw_idx = period_daily["kw"].idxmax()
                peak_date = period_daily.loc[max_kw_idx, "date"]
                peak_demand_days.add(peak_date.isoformat())

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
            "peak_demand_days": list(peak_demand_days),
        },
    }
