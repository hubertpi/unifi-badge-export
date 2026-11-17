# 1.1.1

- Added a custom navy, white and cyan employee badge sync icon for the Home Assistant add-on store.

# 1.1.0

- Added ActiveEmployee as true/false, mapped from UniFi ACTIVE/DEACTIVATED status.
- Retain deactivated users in the CSV instead of dropping their rows. Filter ActiveEmployee in CardExchange when only current employees should be displayed.
- Declared the new field as Bit in schema.ini; existing columns and UserID keys are unchanged.
- Added inactive_users and exported_users to status. An all-inactive directory now exports normally; only a completely empty user directory requires allow_empty_export.
- Unknown statuses abort the sync and preserve the previous CSV.
- Corrected CardExchange setup: select the containing folder as Database and employees.csv as the view.

# 1.0.0

- Active-user export with stable UniFi key, names, employee number and optional photo paths.
- Complete pagination validation and atomic CSV replacement.
- UTF-8 Windows CSV, text-provider schema and shared-folder output.
- Scheduled and manual sync through HA ingress, with status and CSV download.
