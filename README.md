# Bill Engine

A Django application for calculating electricity bills with support for complex tariff structures including time-of-use rates, demand charges, and seasonal applicability rules.

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd bill_engine

# Install dependencies with uv
uv sync --all-extras

# Copy environment file (SQLite is used by default for development)
cp .env.example .env

# Run migrations
uv run python manage.py migrate

# Create a superuser for admin access
uv run python manage.py createsuperuser
```

## Running the Application

```bash
# Start the development server
uv run python manage.py runserver

# Access the admin interface at http://localhost:8000/admin/
```

## Adding Data

### 1. Add a Utility

Utilities represent electricity providers (e.g., PG&E, SCE).

**Via Django Admin:**
1. Navigate to http://localhost:8000/admin/utilities/utility/
2. Click "Add Utility"
3. Enter the utility name (e.g., "PG&E")
4. Optionally add holidays under Utilities > Holidays

**Via Django Shell:**
```bash
uv run python manage.py shell
```
```python
from utilities.models import Utility, Holiday
from datetime import date

utility = Utility.objects.create(name="PG&E")

# Add holidays (used for tariff applicability)
Holiday.objects.create(utility=utility, name="New Year's Day", date=date(2024, 1, 1))
Holiday.objects.create(utility=utility, name="Independence Day", date=date(2024, 7, 4))
```

### 2. Add a Tariff

Tariffs define the rate structure with energy charges, demand charges, and customer charges.

**Via YAML Import (Recommended):**
1. Navigate to http://localhost:8000/admin/tariffs/tariff/
2. Click "Import from YAML"
3. Upload a YAML file (see format below)

**Via Django Admin:**
1. Navigate to http://localhost:8000/admin/tariffs/tariff/
2. Click "Add Tariff"
3. Select the utility and enter tariff name
4. Add charges inline (energy, demand, customer)
5. Create applicability rules and link them to charges

**Via Django Shell:**
```python
from utilities.models import Utility
from tariffs.models import Tariff, EnergyCharge, DemandCharge, CustomerCharge, ApplicabilityRule
from datetime import time, date
from decimal import Decimal

utility = Utility.objects.get(name="PG&E")
tariff = Tariff.objects.create(utility=utility, name="B-19 Secondary")

# Create applicability rules
peak_rule = ApplicabilityRule.objects.create(
    name="Summer Peak",
    period_start_time_local=time(12, 0),
    period_end_time_local=time(18, 0),
    applies_start_date=date(2000, 6, 1),  # Year is ignored, only month/day used
    applies_end_date=date(2000, 9, 30),
    applies_weekdays=True,
    applies_weekends=False,
    applies_holidays=False,
)

# Create charges and link rules
energy = EnergyCharge.objects.create(
    tariff=tariff,
    name="Summer Peak Energy",
    rate_usd_per_kwh=Decimal("0.15432"),
)
energy.applicability_rules.add(peak_rule)

demand = DemandCharge.objects.create(
    tariff=tariff,
    name="Peak Demand",
    rate_usd_per_kw=Decimal("25.00"),
    peak_type="monthly",
)
demand.applicability_rules.add(peak_rule)

CustomerCharge.objects.create(
    tariff=tariff,
    name="Service Charge",
    amount_usd=Decimal("25.00"),
    charge_type="monthly",
)
```

### 3. Add a Customer

Customers are linked to a tariff and have timezone/billing configuration.

**Via CSV Import:**
1. Navigate to http://localhost:8000/admin/customers/customer/
2. Click "Import from CSV"
3. Upload a CSV with columns: `name,timezone,utility_name,tariff_name`

```csv
name,timezone,utility_name,tariff_name
Building A,US/Pacific,PG&E,B-19 Secondary
Building B,US/Pacific,PG&E,B-19 Secondary
```

**Via Django Admin:**
1. Navigate to http://localhost:8000/admin/customers/customer/
2. Click "Add Customer"
3. Fill in name, timezone, tariff, billing interval (default 5 min), and billing day

**Via Django Shell:**
```python
from customers.models import Customer
from tariffs.models import Tariff

tariff = Tariff.objects.get(name="B-19 Secondary")
customer = Customer.objects.create(
    name="Building A",
    timezone="US/Pacific",
    current_tariff=tariff,
    billing_interval_minutes=5,
    billing_day=15,  # Bills end on the 15th of each month
)
```

### 4. Add Usage Data

Usage data contains interval-level energy and demand measurements.

**Via CSV Import (Recommended for bulk data):**
1. Navigate to http://localhost:8000/admin/customers/customer/
2. Select a customer and click "Import Usage Data"
3. Upload a CSV with interval data

```csv
interval_start,interval_end,usage,usage_unit,peak_demand,peak_demand_unit
2024-01-01 00:00:00,2024-01-01 00:05:00,0.42,kWh,5.0,kW
2024-01-01 00:05:00,2024-01-01 00:10:00,0.38,kWh,4.5,kW
2024-01-01 00:10:00,2024-01-01 00:15:00,0.45,kWh,5.4,kW
```

**Via Django Shell:**
```python
from customers.models import Customer
from usage.models import CustomerUsage
from datetime import datetime, timezone
from decimal import Decimal

customer = Customer.objects.get(name="Building A")

CustomerUsage.objects.create(
    customer=customer,
    interval_start_utc=datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc),
    interval_end_utc=datetime(2024, 1, 1, 8, 5, tzinfo=timezone.utc),
    energy_kwh=Decimal("0.42"),
    peak_demand_kw=Decimal("5.0"),
)
```

## Calculating Bills

**Via Admin Interface:**
1. Navigate to http://localhost:8000/admin/customers/customer/
2. Select a customer
3. Click "Calculate Bill"
4. Select the billing period and view results

**Via Python:**
```python
from datetime import date
from customers.models import Customer
from billing.services import calculate_customer_bill

customer = Customer.objects.get(name="Building A")
result = calculate_customer_bill(
    customer=customer,
    start_date=date(2024, 1, 1),
    end_date=date(2024, 1, 31),
)

print(f"Total: ${result.grand_total_usd}")
for month in result.billing_months:
    print(f"  {month.period_start} - {month.period_end}: ${month.total_usd}")
```

## Tariff YAML Format

Tariffs can be imported/exported as YAML for version control and sharing.

```yaml
applicability_rules:
  - name: "Summer Peak"
    period_start_time_local: "12:00"
    period_end_time_local: "18:00"
    applies_start_date: "2000-06-01"
    applies_end_date: "2000-09-30"
    applies_weekdays: true
    applies_weekends: false
    applies_holidays: false

tariffs:
  - name: "Example TOU Tariff"
    utility: "PG&E"
    energy_charges:
      - name: "Summer Peak Energy"
        rate_usd_per_kwh: 0.15432
        applicability_rules:
          - "Summer Peak"
    demand_charges:
      - name: "Peak Demand"
        rate_usd_per_kw: 25.00
        peak_type: monthly
        applicability_rules:
          - "Summer Peak"
    customer_charges:
      - name: "Service Charge"
        amount_usd: 25.00
        charge_type: monthly
```

## PG&E B-19 Tariff

```yaml
applicability_rules:
- name: Maximum Demand Summer Rule
  period_start_time_local: 00:00
  period_end_time_local: '23:59'
  applies_start_date: '2000-06-01'
  applies_end_date: '2000-09-30'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Maximum Demand Winter (Jan-May) Rule
  period_start_time_local: 00:00
  period_end_time_local: '23:59'
  applies_start_date: '2000-01-01'
  applies_end_date: '2000-05-31'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Maximum Demand Winter (Oct-Dec) Rule
  period_start_time_local: 00:00
  period_end_time_local: '23:59'
  applies_start_date: '2000-10-01'
  applies_end_date: '2000-12-31'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Maximum Part-Peak Demand Summer  (night) Rule
  period_start_time_local: '21:00'
  period_end_time_local: '23:00'
  applies_start_date: '2000-06-01'
  applies_end_date: '2000-09-30'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Maximum Part-Peak Demand Summer (afternoon) Rule
  period_start_time_local: '14:00'
  period_end_time_local: '16:00'
  applies_start_date: '2000-06-01'
  applies_end_date: '2000-09-30'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Maximum Peak Demand Summer Rule
  period_start_time_local: '16:00'
  period_end_time_local: '21:00'
  applies_start_date: '2000-06-01'
  applies_end_date: '2000-09-30'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Maximum Peak Demand Winter (Jan-May) Rule
  period_start_time_local: '16:00'
  period_end_time_local: '21:00'
  applies_start_date: '2000-01-01'
  applies_end_date: '2000-05-31'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Maximum Peak Demand Winter (Oct-Dec) Rule
  period_start_time_local: '16:00'
  period_end_time_local: '21:00'
  applies_start_date: '2000-10-01'
  applies_end_date: '2000-12-31'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Off-Peak Summer Rule
  period_start_time_local: 00:00
  period_end_time_local: '14:00'
  applies_start_date: '2000-06-01'
  applies_end_date: '2000-09-30'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Off-Peak Winter (Jan-May) Rule
  period_start_time_local: 00:00
  period_end_time_local: 09:00
  applies_start_date: '2000-01-01'
  applies_end_date: '2000-05-31'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Off-Peak Winter (Oct-Dec) Rule
  period_start_time_local: 00:00
  period_end_time_local: 09:00
  applies_start_date: '2000-10-01'
  applies_end_date: '2000-12-31'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Part-Peak Summer (afternoon) Rule
  period_start_time_local: '14:00'
  period_end_time_local: '16:00'
  applies_start_date: '2000-06-01'
  applies_end_date: '2000-09-30'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Part-Peak Summer (night) Rule
  period_start_time_local: '21:00'
  period_end_time_local: '23:00'
  applies_start_date: '2000-06-01'
  applies_end_date: '2000-09-30'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Peak Summer Rule
  period_start_time_local: '16:00'
  period_end_time_local: '21:00'
  applies_start_date: '2000-06-01'
  applies_end_date: '2000-09-30'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Peak Winter (Jan-May) Rule
  period_start_time_local: '16:00'
  period_end_time_local: '21:00'
  applies_start_date: '2000-01-01'
  applies_end_date: '2000-05-31'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
- name: Peak Winter (Oct-Dec) Rule
  period_start_time_local: '16:00'
  period_end_time_local: '21:00'
  applies_start_date: '2000-10-01'
  applies_end_date: '2000-12-31'
  applies_weekdays: true
  applies_weekends: true
  applies_holidays: true
tariffs:
- name: Voluntary B-19 Secondary Bundled
  utility: PG&E
  energy_charges:
  - name: Off-Peak Summer
    rate_usd_per_kwh: 0.16048
    applicability_rules:
    - Off-Peak Summer Rule
  - name: Off-Peak Winter (Jan-May)
    rate_usd_per_kwh: 0.11886
    applicability_rules:
    - Off-Peak Winter (Jan-May) Rule
  - name: Off-Peak Winter (Oct-Dec)
    rate_usd_per_kwh: 0.11886
    applicability_rules:
    - Off-Peak Winter (Oct-Dec) Rule
  - name: Part-Peak Summer (afternoon)
    rate_usd_per_kwh: 0.14635
    applicability_rules:
    - Part-Peak Summer (afternoon) Rule
  - name: Part-Peak Summer (night)
    rate_usd_per_kwh: 0.14635
    applicability_rules:
    - Part-Peak Summer (night) Rule
  - name: Peak Summer
    rate_usd_per_kwh: 0.18508
    applicability_rules:
    - Peak Summer Rule
  - name: Peak Winter (Jan-May)
    rate_usd_per_kwh: 0.16048
    applicability_rules:
    - Peak Winter (Jan-May) Rule
  - name: Peak Winter (Oct-Dec)
    rate_usd_per_kwh: 0.16048
    applicability_rules:
    - Peak Winter (Oct-Dec) Rule
  demand_charges:
  - name: Maximum Demand Summer
    rate_usd_per_kw: 38.50000
    peak_type: monthly
    applicability_rules:
    - Maximum Demand Summer Rule
  - name: Maximum Demand Winter (Jan-May)
    rate_usd_per_kw: 38.50000
    peak_type: monthly
    applicability_rules:
    - Maximum Demand Winter (Jan-May) Rule
  - name: Maximum Demand Winter (Oct-Dec)
    rate_usd_per_kw: 38.50000
    peak_type: monthly
    applicability_rules:
    - Maximum Demand Winter (Oct-Dec) Rule
  - name: Maximum Part-Peak Demand Summer  (night)
    rate_usd_per_kw: 10.83000
    peak_type: monthly
    applicability_rules:
    - Maximum Part-Peak Demand Summer  (night) Rule
  - name: Maximum Part-Peak Demand Summer (afternoon)
    rate_usd_per_kw: 10.83000
    peak_type: monthly
    applicability_rules:
    - Maximum Part-Peak Demand Summer (afternoon) Rule
  - name: Maximum Peak Demand Summer
    rate_usd_per_kw: 47.24000
    peak_type: monthly
    applicability_rules:
    - Maximum Peak Demand Summer Rule
  - name: Maximum Peak Demand Winter (Jan-May)
    rate_usd_per_kw: 2.31000
    peak_type: monthly
    applicability_rules:
    - Maximum Peak Demand Winter (Jan-May) Rule
  - name: Maximum Peak Demand Winter (Oct-Dec)
    rate_usd_per_kw: 2.31000
    peak_type: monthly
    applicability_rules:
    - Maximum Peak Demand Winter (Oct-Dec) Rule
  customer_charges:
  - name: Customer Charge Voluntary B-19
    amount_usd: 11.87069
    charge_type: daily
```

## Running Tests

```bash
uv run pytest
```

## License

See LICENSE.txt for details.
