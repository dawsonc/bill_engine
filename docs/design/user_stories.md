# User stories

The analyst should do all of these tasks via the admin pane.

## Tariff setup

- [x] As an analyst, I want to view a list of utility tariffs, with the option to search by tariff name or utility name.

- [x] As an analyst, I want to view and edit a single utility tariff (energy, demand, and customers charges). There should be validation that each tariff is in consistent format (e.g. intervals divisible by 5-mins)

- [x] As an analyst, I want to add new utility tariffs using a web interface.

- [x] As an analyst, I want to bulk upload new utility tariffs using a YAML format.

## Customer setup

- [x] As an analyst, I want to view a list of customers, with the option to search by name or utility.

- [x] As an analyst, I want to be able to create, view, and edit individual customer records.

- [x] As an analyst, I want to bulk upload new customers using a CSV format.

## Customer usage data management

- [x] As an analyst, I want to import customer usage data for a single customer from a CSV. The CSV should have columns for interval start, interval end, usage, usage unit, peak demand, peak demand units, temperature, temperature units. Newly uploaded data should replace any old usage data for the same intervals.

- [x] As an analyst, I want to be able to see whether a customer is missing data. Each customer page should show a warning with missing data for each month.

- [x] As an analyst, I want to be able to view a time series of customer usage (energy and peak demand) as a graph that I can filter down to a specific date range. This graph should be part of the page where I view individual customers.

*(Out of scope for now, but we should be able to extend for this)* As an analyst, I want to be able to automatically pull customer data from an external interface like Green Button Connect on a regular schedule (e.g. nightly). *Don't need to implement this now, but keep it in mind for extensibility*

## Bill & customer usage analysis

- [x] As an analyst, I want to be able to estimate the total monthly bill for a customer in either a single month or in a range of months. The analysis should automatically fill in missing data for gaps (e.g. by using either the last known value or by linearly interpolating, based on my choice), and it should give a warning showing the total number of missing records in each month and the length of the longest gap. For each month, I want to generate:
    - A tabular breakdown of charges
    - A stacked bar chart showing the different charges in each month
    - For both energy and demand charges, a line chart of the total energy/demand charge in each month (also show a line for each component charge).

- [x] As an analyst, I want to be able to plot a time series of daily customer usage for a specific billing month. There should be plots for both energy and peak demand on each day.

- [ ] As an analyst, I want to be able to plot a time series of customer usage for a specific day. There should be plots for both energy and peak demand. Each plot should overlay the periods in which different energy and demand charges apply.

- [ ] As an analyst, I want to be able to generate these daily plots for the day that contributed the most to monthly demand charges.

*(Out of scope for now, but we should be able to extend for this)* As an analyst, I want to be able to do more advanced analytics of customer usage (e.g. correlations with temperature, computing daily or day-of-week average load profiles, etc.). No need to implement this suite of methods for now, but keep it in mind for extensibility.