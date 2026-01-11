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


@dataclass(frozen=True, slots=True)
class ApplicabilityRule:
    """
    Applicability window shared by energy and demand charges.

    A rule can constrain:
        - time-of-day (period_start/period_end),
        - date range (start_date/end_date),
        - day categories (day_types).

    Notes:
        - If a field is None/empty, it is treated as 'no constraint' for that dimension.
        - period_start/period_end are interpreted as local clock times.

    Validation:
        - period_start < period_end
        - start_date <= end_date

    Defaults:
        - Applies to all day_types by default
    """

    period_start: Optional[time] = None
    period_end: Optional[time] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    day_types: frozenset[DayType] = field(default_factory=lambda: frozenset(DayType))

    def __post_init__(self) -> None:
        """Validate internal consistency of the applicability rule."""
        if self.period_start is not None and self.period_end is not None:
            if self.period_start >= self.period_end:
                raise ValueError("period_start must be strictly earlier than period_end")

        if self.start_date is not None and self.end_date is not None:
            if self.start_date > self.end_date:
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
    rate_per_kwh: Decimal
    charge_id: ChargeId = field(default_factory=ChargeId)
    applicability: ApplicabilityRule = field(default_factory=ApplicabilityRule)


@dataclass(frozen=True, slots=True)
class DemandCharge:
    """
    Demand charge rate (e.g., $/kW) with optional applicability windows.
    """

    name: str
    rate_per_kw: Decimal
    type: PeakType = PeakType.MONTHLY
    charge_id: ChargeId = field(default_factory=ChargeId)
    applicability: ApplicabilityRule = field(default_factory=ApplicabilityRule)


@dataclass(frozen=True, slots=True)
class CustomerCharge:
    """
    Flat recurring charge (e.g., monthly customer charge).

    This is typically a fixed amount per billing period, not time-windowed.
    """

    name: str
    amount: Decimal
    charge_id: ChargeId = field(default_factory=ChargeId)


@dataclass(frozen=True, slots=True)
class ChargeList:
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

    charge_id: ChargeId = field(default_factory=ChargeId)
    description: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class MonthlyBillResult:
    """
    Billing result for a calendar month.
    """

    month_start: date
    month_end: date
    energy_line_items: tuple[BillLineItem, ...]
    demand_line_items: tuple[BillLineItem, ...]
    customer_line_items: tuple[BillLineItem, ...]
    total: Decimal
