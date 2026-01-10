# Models/data types

# Customer usage

Customer usage is stored on a 5-minute basis. Often, it will be billed on a 15-minute or hourly basis, but we will store it in the most granular possible form.

# Tariffs

A tariff defines the rules by which customers are billed.

A tariff can have zero or more energy, demand, and customer components. It must have at least one component, but it does not need to have one of each. Each charge has a name (e.g. "On peak energy").

- Energy charges assign a $/kWh charge to energy used in each time period.
    - An energy charge is represented as a list of non-overlapping time periods with a $/kWh price assigned to each time period.
    - Each energy charge has an applicable date range (could be the entire year, but could be a subset; range is inclusive of the start and end days).
    - Each energy charge can apply to all days or just business days (non-holiday weekdays).

- A demand charge assigns a $/kW charge to the maximum power measured in each time period.
    - A demand charge is represented as a single time period with a $/kW price for the maximum demand in that time period.
    - A demand charge may be either daily or monthly (i.e. the maximimum is either over a period in one day or over all periods in a month). 
    - Each demand charge has an applicable date range (could be the entire year, but could be a subset; range is inclusive of the start and end days).
    - Each demand charge can apply to all days or just business days (non-holiday weekdays).

- A customer charge is a $ amount added to each monthly bill regardless of usage.

- Time periods are represented by start and end times. An interval is incldued in a time period if the start of the interval is before the end time of the period. I.e. a period from 12:00:00 to 13:59:59 will include the interval starting 13:55:00 and will not include the interval starting 14:00:00. All time periods are canonically represented in UTC.

Each row represents a tariff and has: columns:
- name
- utility_id (FK)
- Zero or more energy charges
- Zero or more demand charges
- Zero or more customer charges

Each row represents a energy charge and has columns:
- name
- tariff_id (FK)
- rate_usd_per_kwh
- period_start_time_utc
- period_end_time_utc
- applies_start_date (nullable)
- applies_end_date (nullable)
- applies_weekends (boolean)
- applies_holidays (boolean)

Each row represents a demand charge and has columns:
- name
- tariff_id (FK)
- rate_usd_per_kw
- period_start_time_utc
- period_end_time_utc
- applies_start_date (nullable)
- applies_end_date (nullable)
- applies_weekends (boolean)
- applies_holidays (boolean)
- peak_type ("daily" or "monthly")

Each row represents a customer charge and has columns:
- name
- tariff_id (FK)
- usd_per_month

## Tariff YAML Serialization Format

For bulk upload of tariffs, use the following YAML format:

```yaml
name: "PG&E B-19 Secondary"
utility: "Pacific Gas & Electric"
timezone: "America/Los_Angeles"  # IANA timezone for converting local times to UTC

energy_charges:
  - name: "Summer Peak Energy"
    rate_usd_per_kwh: 0.15234
    period_start_time: "12:00:00"  # Local time in utility timezone
    period_end_time: "18:59:59"
    applies_start_date: "2024-06-01"
    applies_end_date: "2024-09-30"
    applies_weekends: false
    applies_holidays: false

  - name: "Summer Part-Peak Energy"
    rate_usd_per_kwh: 0.10123
    period_start_time: "08:30:00"
    period_end_time: "11:59:59"
    applies_start_date: "2024-06-01"
    applies_end_date: "2024-09-30"
    applies_weekends: false
    applies_holidays: false

  - name: "Winter Part-Peak Energy"
    rate_usd_per_kwh: 0.09876
    period_start_time: "08:30:00"
    period_end_time: "13:29:59"
    applies_start_date: "2024-10-01"
    applies_end_date: "2024-05-31"
    applies_weekends: false
    applies_holidays: false

demand_charges:
  - name: "Summer Peak Demand"
    rate_usd_per_kw: 18.95
    period_start_time: "12:00:00"
    period_end_time: "18:59:59"
    applies_start_date: "2024-06-01"
    applies_end_date: "2024-09-30"
    applies_weekends: false
    applies_holidays: false
    peak_type: "monthly"

  - name: "Summer Part-Peak Demand"
    rate_usd_per_kw: 5.74
    period_start_time: "08:30:00"
    period_end_time: "11:59:59"
    applies_start_date: "2024-06-01"
    applies_end_date: "2024-09-30"
    applies_weekends: false
    applies_holidays: false
    peak_type: "monthly"

  - name: "Max Demand (Non-Coincident)"
    rate_usd_per_kw: 16.42
    period_start_time: "00:00:00"
    period_end_time: "23:59:59"
    applies_start_date: null  # applies year-round
    applies_end_date: null
    applies_weekends: true
    applies_holidays: true
    peak_type: "monthly"

customer_charges:
  - name: "Customer Charge"
    usd_per_month: 335.74
```

Notes on the format:
- Times are specified in the local timezone of the utility (use IANA timezone names like "America/Los_Angeles")
- The `timezone` field is used to convert local times to UTC for storage, but is not stored in the tariff record
- The system will validate that the specified timezone matches the utility's timezone in the database
- Dates use ISO 8601 format (YYYY-MM-DD)
- Times use HH:MM:SS format in 24-hour notation
- Use `null` for date fields that don't apply
- The utility name should match an existing utility in the database (or be created if it doesn't exist)
- Multiple tariffs can be uploaded in a single YAML file by using YAML's document separator (`---`)

# Utilities

Each row represents a utility and has columns:
- Name

Each utility may define a list of holidays. Each row represents a holiday and has columns:
- utility_id (FK)
- name
- date

# Customer

Each row represents a customer and has columns:
- Name
- current_tariff_id (FK)
- Time zone

For now, we assume that there is a 1-1 relation between customers and meters.

# CustomerUsage

Each row represents customer usage in a 5-minute interval and has columns:
- customer_id (FK)
- interval_start_utc (Datetime)
- interval_end_utc (Datetime)
- energy_kwh
- peak_demand_kw
- temperature_c
- created_at_utc (Datetime)

We enforce the constraint that (customer_id, interval_start_utc) is unique.