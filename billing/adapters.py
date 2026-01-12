"""
Adapters for converting Django ORM models to billing DTOs.

This module provides lightweight mappings from the tariffs app's Django models
to the immutable dataclasses used by the billing engine core.
"""

from datetime import date, time
from typing import Optional
from uuid import UUID, uuid5

from billing.core.types import (
    ApplicabilityRule,
    ChargeId,
    ChargeList,
    CustomerCharge,
    DayType,
    DemandCharge,
    EnergyCharge,
    PeakType,
)
from tariffs.models import (
    CustomerCharge as CustomerChargeModel,
)
from tariffs.models import (
    DemandCharge as DemandChargeModel,
)
from tariffs.models import (
    EnergyCharge as EnergyChargeModel,
)
from tariffs.models import (
    Tariff,
)

# Custom namespace for generating deterministic UUIDs from database IDs
# This ensures the same database record always produces the same ChargeId
BILLING_CHARGE_NAMESPACE = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def generate_charge_id(model_name: str, pk: int) -> ChargeId:
    """
    Generate a deterministic ChargeId from a Django model's primary key.

    Uses UUID5 to create stable, reproducible UUIDs that maintain lineage
    across multiple conversions of the same database record.

    Args:
        model_name: Name of the Django model (e.g., "EnergyCharge")
        pk: Primary key of the model instance

    Returns:
        ChargeId containing a deterministic UUID

    Examples:
        >>> charge_id = generate_charge_id("EnergyCharge", 42)
        >>> # Same input always produces same output
        >>> assert charge_id == generate_charge_id("EnergyCharge", 42)
    """
    # Create a stable string representation combining model name and PK
    # This ensures different model types with the same PK get different UUIDs
    name_string = f"{model_name}:{pk}"
    uuid_value = uuid5(BILLING_CHARGE_NAMESPACE, name_string)
    return ChargeId(value=uuid_value)


def build_day_types(
    applies_weekdays: bool,
    applies_weekends: bool,
    applies_holidays: bool,
) -> frozenset[DayType]:
    """
    Convert Django model's boolean day applicability fields to DayType frozenset.

    Args:
        applies_weekdays: Whether charge applies on weekdays
        applies_weekends: Whether charge applies on weekends
        applies_holidays: Whether charge applies on holidays

    Returns:
        Frozenset of applicable DayType values. If all booleans are False,
        returns an empty frozenset (charge applies to no days).

    Examples:
        >>> build_day_types(True, False, False)
        frozenset({DayType.WEEKDAY})
        >>> build_day_types(True, True, True)
        frozenset({DayType.WEEKDAY, DayType.WEEKEND, DayType.HOLIDAY})
        >>> build_day_types(False, False, False)
        frozenset()
    """
    day_types: set[DayType] = set()

    if applies_weekdays:
        day_types.add(DayType.WEEKDAY)
    if applies_weekends:
        day_types.add(DayType.WEEKEND)
    if applies_holidays:
        day_types.add(DayType.HOLIDAY)

    return frozenset(day_types)


def build_applicability_rule(
    period_start_time_local: time,
    period_end_time_local: time,
    applies_start_date: Optional[date],
    applies_end_date: Optional[date],
    applies_weekdays: bool,
    applies_weekends: bool,
    applies_holidays: bool,
) -> ApplicabilityRule:
    """
    Build an ApplicabilityRule from Django model's flat fields.

    This function aggregates the time-of-day, date range, and day type
    constraints from the Django model's normalized structure into the
    DTO's composite ApplicabilityRule.

    Args:
        period_start_time_local: Start time of daily period (inclusive)
        period_end_time_local: End time of daily period (exclusive)
        applies_start_date: First applicable date (inclusive), None for year-round
        applies_end_date: Last applicable date (inclusive), None for year-round
        applies_weekdays: Whether charge applies on weekdays
        applies_weekends: Whether charge applies on weekends
        applies_holidays: Whether charge applies on holidays

    Returns:
        ApplicabilityRule DTO with all constraints properly configured

    Raises:
        ValueError: If the ApplicabilityRule's post_init validation fails
    """
    day_types = build_day_types(applies_weekdays, applies_weekends, applies_holidays)

    return ApplicabilityRule(
        period_start_local=period_start_time_local,
        period_end_local=period_end_time_local,
        start_date=applies_start_date,
        end_date=applies_end_date,
        day_types=day_types,
    )


def energy_charge_to_dto(charge: EnergyChargeModel) -> EnergyCharge:
    """
    Convert Django EnergyCharge model to EnergyCharge DTO.

    Args:
        charge: Django EnergyCharge model instance

    Returns:
        EnergyCharge DTO with deterministic ChargeId
    """
    charge_id = generate_charge_id("EnergyCharge", charge.pk)
    applicability = build_applicability_rule(
        period_start_time_local=charge.period_start_time_local,
        period_end_time_local=charge.period_end_time_local,
        applies_start_date=charge.applies_start_date,
        applies_end_date=charge.applies_end_date,
        applies_weekdays=charge.applies_weekdays,
        applies_weekends=charge.applies_weekends,
        applies_holidays=charge.applies_holidays,
    )

    return EnergyCharge(
        name=charge.name,
        rate_usd_per_kwh=charge.rate_usd_per_kwh,
        charge_id=charge_id,
        applicability=applicability,
    )


def demand_charge_to_dto(charge: DemandChargeModel) -> DemandCharge:
    """
    Convert Django DemandCharge model to DemandCharge DTO.

    Args:
        charge: Django DemandCharge model instance

    Returns:
        DemandCharge DTO with deterministic ChargeId

    Raises:
        ValueError: If peak_type has an invalid value
    """
    charge_id = generate_charge_id("DemandCharge", charge.pk)
    applicability = build_applicability_rule(
        period_start_time_local=charge.period_start_time_local,
        period_end_time_local=charge.period_end_time_local,
        applies_start_date=charge.applies_start_date,
        applies_end_date=charge.applies_end_date,
        applies_weekdays=charge.applies_weekdays,
        applies_weekends=charge.applies_weekends,
        applies_holidays=charge.applies_holidays,
    )

    # Map Django's string choice field to PeakType enum
    if charge.peak_type == "daily":
        peak_type = PeakType.DAILY
    elif charge.peak_type == "monthly":
        peak_type = PeakType.MONTHLY
    else:
        raise ValueError(f"Invalid peak_type: {charge.peak_type}")

    return DemandCharge(
        name=charge.name,
        rate_usd_per_kw=charge.rate_usd_per_kw,
        type=peak_type,
        charge_id=charge_id,
        applicability=applicability,
    )


def customer_charge_to_dto(charge: CustomerChargeModel) -> CustomerCharge:
    """
    Convert Django CustomerCharge model to CustomerCharge DTO.

    Customer charges are simpler as they have no time-of-day or seasonal constraints.

    Args:
        charge: Django CustomerCharge model instance

    Returns:
        CustomerCharge DTO with deterministic ChargeId
    """
    charge_id = generate_charge_id("CustomerCharge", charge.pk)

    return CustomerCharge(
        name=charge.name,
        amount_usd_per_month=charge.usd_per_month,
        charge_id=charge_id,
    )


def tariff_to_charge_list(tariff: Tariff) -> ChargeList:
    """
    Convert a Django Tariff model with all related charges to a ChargeList DTO.

    This is the main entry point for adapter conversion. It aggregates all
    charge types from the tariff's related managers and converts them to DTOs.

    IMPORTANT: For performance, the tariff should be prefetched with:
        tariff = Tariff.objects.prefetch_related(
            'energy_charges',
            'demand_charges',
            'customer_charges'
        ).get(pk=tariff_id)

    Without prefetching, this function will trigger N+1 queries.

    Args:
        tariff: Django Tariff model instance (preferably with prefetched charges)

    Returns:
        ChargeList DTO containing tuples of all charge DTOs

    Examples:
        >>> from tariffs.models import Tariff
        >>> tariff = Tariff.objects.prefetch_related(
        ...     'energy_charges', 'demand_charges', 'customer_charges'
        ... ).get(pk=1)
        >>> charge_list = tariff_to_charge_list(tariff)
        >>> len(charge_list.energy_charges)
        3
    """
    # Convert each charge type using dedicated helper functions
    # Use tuple() for immutability as required by ChargeList
    energy_charges = tuple(energy_charge_to_dto(charge) for charge in tariff.energy_charges.all())

    demand_charges = tuple(demand_charge_to_dto(charge) for charge in tariff.demand_charges.all())

    customer_charges = tuple(
        customer_charge_to_dto(charge) for charge in tariff.customer_charges.all()
    )

    return ChargeList(
        energy_charges=energy_charges,
        demand_charges=demand_charges,
        customer_charges=customer_charges,
    )


def tariffs_to_charge_lists(tariffs_queryset) -> dict[int, ChargeList]:
    """
    Batch convert multiple tariffs to ChargeList DTOs.

    This is a convenience function for bulk conversions. It automatically
    handles prefetching for optimal performance.

    Args:
        tariffs_queryset: Django QuerySet of Tariff objects

    Returns:
        Dictionary mapping tariff.pk to ChargeList DTO

    Examples:
        >>> from tariffs.models import Tariff
        >>> active_tariffs = Tariff.objects.filter(active=True)
        >>> charge_lists = tariffs_to_charge_lists(active_tariffs)
        >>> charge_lists[1].energy_charges
        (EnergyCharge(...), EnergyCharge(...))
    """
    # Optimize query with single prefetch for all related charges
    tariffs = tariffs_queryset.prefetch_related(
        "energy_charges",
        "demand_charges",
        "customer_charges",
    )

    return {tariff.pk: tariff_to_charge_list(tariff) for tariff in tariffs}
