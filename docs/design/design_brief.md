# Energy Bill Engine & Extensibility Challenge

An important part of our business is explaining to customers how they are accurately billed. Utility tariffs can be surprisingly complex and opaque to the end user.

We have a client with a large manufacturing facility and have obtained their raw energy usage data (KW). We need a program that calculates their monthly bill based on their Utility Tariff.

## The Goal

By the end of this exercise, we want to provide the client with clarity on how they are billed, identify where the majority of their costs originate, and offer actionable insights to decrease their bill.

## Deliverables
Please send the following to us before the end of the day Friday 16th. Let me know if this works for you or if you think you may need more time.

- **Source Code**: A link to a GitHub repository or a zip file.
- **README**: Brief instructions on how to run your code.
- **Presentation**: Your slides or visual aids.

## Resources Provided

- Usage Data: A CSV file containing 15-minute interval energy usage (KW) for a single customer over a 12-month period.
- Tariff Details: Screenshots describing the PG&E B-19 tariff.
- Sample Bill: An anonymized bill for reference (Note: This is for structural reference only; the numbers may not match your calculated dataset).

## Requirements
Write a program in a language of your choosing that ingests the usage data and calculates the total monthly bill any month. Your calculator must account for:

- Time-of-Use Energy Charges ($/kWh): Peak vs. Part-Peak vs. Off-Peak (Summer/Winter logic).
- Demand Charges ($/kW): The specific logic for "Max Peak Demand" vs. "Max Part-Peak Demand" vs. "Max Demand" (Non-coincident).
- Customer Charge: The daily fixed rate.

*Out of scope:*

- PDP rates, power factor adjustments, generation credit, franchise fee surcharge, utility users' tax (anything outside of the TOU energy, demand, and customer charges)
- Current implementation does not handle block rates.

## Assessment Criteria

While calculating the correct cost is important, we are equally interested in your software design.

**Scalability Scenario:** Imagine that next month we need to add 50 more tariff types (PG&E B-10, SCE TOU-8, etc.) and process 1,000 customers. Structure your code so it is extensible.
