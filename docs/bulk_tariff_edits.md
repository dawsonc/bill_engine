# Bulk Tariff Import/Export

The tariff admin interface supports bulk import and export of tariffs via YAML files. This enables faster data entry, version control of tariff definitions, and batch updates of rates.

## Exporting Tariffs

### Export All Tariffs
1. Navigate to the Tariffs list in Django admin
2. Click the "Export All to YAML" button in the top right
3. Downloads `tariffs.yaml` containing all tariffs with their charges

### Export Selected Tariffs
1. Check the boxes next to the tariffs you want to export
2. Select "Export selected tariffs to YAML" from the action dropdown
3. Click "Go"
4. Downloads `tariffs_selected.yaml` containing only the selected tariffs

## YAML Format

The YAML file has a top-level `tariffs` key containing a list of tariff objects. Each tariff includes:
- `name` - Tariff name (required)
- `utility` - Utility name, must match existing utility (required)
- `energy_charges` - List of energy charges (optional)
- `demand_charges` - List of demand charges (optional)
- `customer_charges` - List of customer charges (optional)

### Format Conventions
- **Times**: `HH:MM` format (e.g., "12:00" for noon). All times are specified in the local time of the customer facility (time zone is tracked on a per-customer basis).
- **Dates**: `YYYY-MM-DD` format, or `null` for year-round charges
- **Decimals**: Energy rates have up to 5 decimal places, demand/customer charges have 2
- **Booleans**: `true`/`false` for `applies_weekdays`, `applies_weekends`, `applies_holidays` (all default to `true` if omitted)

### Example

```yaml
tariffs:
  - name: "B-19 Secondary"
    utility: "PG&E"

    energy_charges:
      - name: "Summer Peak Energy"
        rate_usd_per_kwh: 0.15432
        period_start_time_local: "12:00"
        period_end_time_local: "18:00"
        applies_start_date: "2024-06-01"
        applies_end_date: "2024-09-30"
        applies_weekdays: true
        applies_weekends: false
        applies_holidays: false

    demand_charges:
      - name: "Summer Peak Demand"
        rate_usd_per_kw: 18.50
        period_start_time_local: "12:00"
        period_end_time_local: "18:00"
        peak_type: "monthly"  # "daily" or "monthly"
        applies_start_date: "2024-06-01"
        applies_end_date: "2024-09-30"
        applies_weekdays: true
        applies_weekends: false
        applies_holidays: false

    customer_charges:
      - name: "Basic Service"
        usd_per_month: 15.00
```

For a complete example with detailed comments, download the [sample template](/static/tariffs/sample_template.yaml) from the import page.

See [models.md](design/models.md) for complete field specifications.

## Importing Tariffs

1. **Navigate** to the Tariffs list in Django admin
2. **Click** "Import from YAML" button
3. **Upload** a `.yaml` or `.yml` file (maximum 10MB)
4. **Choose** duplicate handling:
   - **Unchecked** (default): Skip tariffs that already exist with the same utility+name
   - **Checked**: Replace existing tariffs (deletes all old charges and creates new ones)
5. **Click** "Upload and Import"
6. **Review** the results page showing:
   - **Created**: New tariffs successfully imported (clickable links to edit)
   - **Updated**: Existing tariffs that were replaced
   - **Skipped**: Tariffs that already exist (when replace not checked)
   - **Errors**: Failed imports with detailed error messages

## Validation & Error Handling

### Validation Rules
- **Period end time** must be after period start time
- **Applicable end date** must be on or after start date (when both provided)
- **Utility** must exist in the database
- **Peak type** must be "daily" or "monthly"
- Times must be in **HH:MM** format
- Dates must be in **YYYY-MM-DD** format or `null`

### Import Behavior
- Each tariff is imported in its own transaction (atomic)
- If one tariff fails validation, others continue processing
- Validation errors are isolated and reported per tariff
- Results page shows detailed error messages for each field

### Common Errors

**"Utility not found"**
- The utility name in the YAML doesn't match any utility in the database
- Create the utility first via the admin interface

**"Period end time must be after period start time"**
- Check that `period_end_time_local` is later than `period_start_time_local`
- Both times are in local utility time

**"Applicable end date must be on or after the start date"**
- Check that `applies_end_date` is on or after `applies_start_date`
- Use `null` for both if the charge applies year-round

**"Invalid YAML syntax"**
- Check file structure, indentation (use spaces, not tabs), and quotes
- Validate YAML syntax using an online validator or IDE

**"File size exceeds 10MB limit"**
- Split the file into multiple smaller files
- Import them separately

## Common Use Cases

### Initial Tariff Setup
1. Create utilities first via the admin interface
2. Prepare YAML file using the sample template as a guide
3. Import with "replace existing" **unchecked**
4. Review created tariffs on the results page

### Seasonal Rate Updates
1. Export current tariffs to YAML
2. Modify rates in the exported file
3. Import with "replace existing" **checked**
4. Verify updates on the results page

### Version Control
1. Export current tariffs to YAML
2. Commit YAML file to version control (e.g., git)
3. Track changes to tariff definitions over time
4. Restore previous versions by importing old YAML files
