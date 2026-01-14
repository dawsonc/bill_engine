"""Custom exceptions for billing services."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from customers.models import Customer


class BillingServiceError(Exception):
    """Base exception for billing service errors."""

    pass


class InvalidDateRangeError(BillingServiceError):
    """Raised when date range is invalid."""

    def __init__(self, message: str, start_date: date, end_date: date):
        super().__init__(message)
        self.start_date = start_date
        self.end_date = end_date


class NoUsageDataError(BillingServiceError):
    """Raised when no usage data exists for the requested period."""

    def __init__(self, customer: Customer, start_date: date, end_date: date):
        self.customer = customer
        self.start_date = start_date
        self.end_date = end_date
        super().__init__(
            f"No usage data found for {customer.name} "
            f"between {start_date} and {end_date}"
        )


class IncompleteDataError(BillingServiceError):
    """Raised when usage data has gaps that cannot be filled."""

    def __init__(self, message: str, missing_intervals: int, expected_intervals: int):
        super().__init__(message)
        self.missing_intervals = missing_intervals
        self.expected_intervals = expected_intervals
