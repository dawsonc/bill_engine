# Billing engine design

## Architecture

We will separate concerns between the `tariffs` and `billing` apps.
    - `tariffs` is responsible for storing and validating tariffs and line item charges. This app interacts with the Django ORM, provides appropriate admin panes, etc..
    - `billing` is responsible for applying line items to customer usage. This core of this app is a set of pure functions that are independent of Django (although the app can also provide some Django-connected admin panes etc.).

## Pipeline

1. Get customer usage for a time period as a pandas DataFrame. Convert usage timestamps from canonical UTC to customer local time.
2. Get the customer's tariff and charges. Get all holidays from their utility.
3. Organize usage, intervals, and weekday/weekend/holiday labels into a DataFrame (see below for schema).
4. Apply each charge to the customer usage, adding a column to a billing DataFrame that shows the charge in each interval (e.g. energy charge in that interval, or the demand charge allocated across intervals where the peak occured).
5. Return the total bill, line item subtotals, and billing dataframe for each month.

## `billing` components

`billing.core` should have the core functions for computing bill line items. This module should be decoupled from the broader django app.
    - The general strategy is to create a time series for each line item/charge:
        - Customer charges should be evenly spread across all intervals
        - Energy charges should be allocated based on usage in each interval
        - Demand charges should be allocated evenly across all intervals with the maximum demand
    - Once we have a dataframe where each row represents an interval and each column represents a timeseries of costs for each charge (labeled using unique IDs for each charge), we can:
        - Get line item subtotals for each month by grouping by month and summing each column
        - Get total bill for each month by summing line item subtotals

```python
# billing/core/calculator.py
def calculate_monthly_bills(usage: pd.DataFrame, charges: ChargeList) -> tuple[list[MonthlyBillResult], pd.DataFrame]:
    ...

def apply_charges(usage: pd.DataFrame, charges: ChargeList) -> pd.DataFrame:
    ...

# billing/core/charges/customer.py
def apply_customer_charge(usage: pd.DataFrame, customer_charge: CustomerCharge) -> pd.Series:
    ...

# billing/core/charges/energy.py
def apply_energy_charge(usage: pd.DataFrame, energy_charge: EnergyCharge) -> pd.Series:
    ...

# billing/core/charges/demand.py
def apply_demand_charge(usage: pd.DataFrame, demand_charge: DemandCharge) -> pd.Series:
    ...


# billing/core/applicability.py

def construct_applicability_mask(usage: pd.DataFrame, rule: ApplicabilityRule) -> pd.Series[bool]:
    ...

# billing/core/data.py

def fill_missing_data(usage: pd.DataFrame, strategy: str = "extrapolate_last"):
    ...


def validate_usage_dataframe(usage: pd.DataFrame):
    ...

```

`billing.core.types` should have dataclasses defining data transfer objects (DTOs) for different charges, including a charge for applicability windows (shared between energy and demand charges). It should provide the following types
    - Each type of charge (DemandCharge, EnergyCharge, CustomerCharge), including a unique charge ID for labeling
    - ApplicabilityRule for period start/end times, start/end dates, weekday/weekend/holiday applicability
    - ChargeList wrapping three lists (energy charges, demand charges, customer charges)
    - MonthlyBillResult: first of month date, line items, total

`billing.services` defines a BillingService class that provides a `calculate_bill(customer, usage)` function. The service is allowed to interact with the django ORM and will orchestrate the pipeline defined above.

`billing.adapters` provides lightweight mappings from Django models to DTOs


### Handling billing months

- Energy charges are just summed over intervals
- Customer charges
    - Daily customer charges are allocated to days and summed
    - Monthly customer charges are allocated by billing month
- Demand charges
    - Daily demand charges are allocated to days and summed
    - Monthly demand charges are allocated by billing month
        - All demand charges should be scaled by the fraction of calendar days they apply to / total days in billing period