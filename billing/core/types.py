"""
Define lightweight dataclasses to use for bill calculations.

Adapters to convert between Django ORM and these classes are in billing.adapters.
"""

from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class DayType(str, Enum):
    """Which day categories a rule applies to."""

    WEEKDAY = "weekday"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"


class PeakType(str, Enum):
    """The period over which the demand charge applies."""

    DAILY = "daily"
    MONTHLY = "monthly"


class CustomerChargeType(str, Enum):
    """The period over which the customer charge applies."""

    DAILY = "daily"
    MONTHLY = "monthly"


@dataclass(frozen=True, slots=True)
class ApplicabilityRule:
    """
    Applicability window shared by energy and demand charges.

    A rule can constrain:
        - time-of-day (period_start/period_end),
        - date range (start_date/end_date),
        - day categories (day_types).

    Time ranges are inclusive of start and exclusive of end.
    Date ranges are inclusive of both start and end.

    Date ranges are applied to every year; only the month and day matter.
    Year-end wrapping is NOT supported: start_date must be earlier than or equal
    to end_date within the same calendar year. For example, a rule for Dec 1 - Jan 31
    must be split into two separate rules: Dec 1 - Dec 31 and Jan 1 - Jan 31.

    Notes:
        - If a field is None/empty, it is treated as 'no constraint' for that dimension.
        - period_start_local/period_end_local are interpreted as local clock times.

    Validation:
        - period_start_local < period_end_local
        - start_date <= end_date (within same calendar year, no wrapping)

    Defaults:
        - Applies to all day_types by default
    """

    period_start_local: Optional[time] = None
    period_end_local: Optional[time] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    day_types: frozenset[DayType] = field(default_factory=lambda: frozenset(DayType))

    def __post_init__(self) -> None:
        """Validate internal consistency of the applicability rule."""
        if self.period_start_local is not None and self.period_end_local is not None:
            if self.period_start_local >= self.period_end_local:
                raise ValueError(
                    "period_start_local must be strictly earlier than period_end_local"
                )

        if self.start_date is not None and self.end_date is not None:
            # Normalize to year 2000 for month/day-only comparison
            start_normalized = date(2000, self.start_date.month, self.start_date.day)
            end_normalized = date(2000, self.end_date.month, self.end_date.day)
            if start_normalized > end_normalized:
                raise ValueError("start_date must be earlier than or equal to end_date")


@dataclass(frozen=True, slots=True)
class ChargeId:
    """Strongly-typed unique charge identifier for labeling and lineage."""

    value: UUID = field(default_factory=uuid4)


@dataclass(frozen=True, slots=True)
class EnergyCharge:
    """
    Energy charge rate (e.g., $/kWh) with optional applicability windows.
    """

    name: str
    rate_usd_per_kwh: Decimal
    charge_id: ChargeId = field(default_factory=ChargeId)
    applicability: ApplicabilityRule = field(default_factory=ApplicabilityRule)


@dataclass(frozen=True, slots=True)
class DemandCharge:
    """
    Demand charge rate (e.g., $/kW) with optional applicability windows.
    """

    name: str
    rate_usd_per_kw: Decimal
    type: PeakType = PeakType.MONTHLY
    charge_id: ChargeId = field(default_factory=ChargeId)
    applicability: ApplicabilityRule = field(default_factory=ApplicabilityRule)


@dataclass(frozen=True, slots=True)
class CustomerCharge:
    """
    Flat recurring charge (e.g., daily or monthly customer charge).

    This is a fixed amount per billing period (day or month), not time-windowed.
    """

    name: str
    amount_usd: Decimal
    type: CustomerChargeType = CustomerChargeType.MONTHLY
    charge_id: ChargeId = field(default_factory=ChargeId)


@dataclass(frozen=True, slots=True)
class Tariff:
    """
    Container for tariff charges, grouped by charge type.
    """

    energy_charges: tuple[EnergyCharge, ...] = ()
    demand_charges: tuple[DemandCharge, ...] = ()
    customer_charges: tuple[CustomerCharge, ...] = ()


@dataclass(frozen=True, slots=True)
class BillLineItem:
    """
    One billed line item, suitable for display and reconciliation.
    """

    description: str
    amount_usd: Decimal
    charge_id: ChargeId = field(default_factory=ChargeId)


@dataclass(frozen=True, slots=True)
class BillingMonthResult:
    """
    Billing result for a custom billing month.

    A billing month may span multiple calendar months.
    """

    period_start: date
    period_end: date
    energy_line_items: tuple[BillLineItem, ...]
    demand_line_items: tuple[BillLineItem, ...]
    customer_line_items: tuple[BillLineItem, ...]
    total_usd: Decimal
