# Installation

Copy this entire `unifi_badge_export` folder into Home Assistant's local add-on directory, normally `/addons` as exposed through HA file sharing. The final path inside that share should be `/addons/unifi_badge_export/config.yaml`. The Debian host path depends on the Supervisor data directory; do not place this in `/config` or `custom_components`.

Open Settings → Add-ons → Add-on Store, use the store menu to check for updates, then find **UniFi Badge Export** under Local add-ons. Refresh the browser if needed. Install it. Supervisor builds the image locally; an Internet connection to Docker Hub is needed for the Python base image.

## Configuration

Set these in the add-on Configuration tab, then save and start the add-on:

| Option | Value |
| --- | --- |
| `console_url` | Local console IP or HTTPS hostname. Without an explicit port, the documented Access API port **12445** is used. Example: `https://192.168.1.50:12445`. Use the API port, not the web interface's port 443. |
| `api_token` | Existing UniFi Access API token with **view:user** permission. Enter it here, not in chat. A Network, Protect or Site Manager token is not interchangeable. |
| `verify_ssl` | Defaults to true. If the console uses an untrusted self-signed certificate, false allows it; transport remains HTTPS but certificate identity is not checked. |
| `sync_interval_seconds` | Defaults to 300. Sync also runs on startup and when Sync now is clicked. |
| `output_folder` | Defaults to `unifi-badges`, within HA's `/share` directory. Simple folder name only. |
| `allow_empty_export` | Defaults to false. A zero-user response preserves the previous CSV. An all-deactivated directory exports normally. Set true only if clearing the export to headers is intended. |
| `export_photos` | Optional, defaults to false. Requires **view:system_log** as well as **view:user**. |
| `windows_photo_folder` | When photos are enabled, the path Windows uses for `/share/unifi-badges/photos`, e.g. `\\HA-SERVER\share\unifi-badges\photos`. Leave blank when photos are off. |

Restart the add-on after changing configuration. Open its Web UI to check status.

## Output and Windows access

The export is `/share/unifi-badges/employees.csv`. A `schema.ini` text-provider sidecar is written alongside it. With the HA Samba share add-on already configured, Windows can access it as `\\HA-SERVER\share\unifi-badges\employees.csv`; substitute the actual HA hostname or IP. This add-on writes the shared folder but does not install or configure Samba itself.

For initial testing you can also download the CSV through the Web UI. A downloaded copy does not update itself; use the shared file for regular badge printing.

## CardExchange connection

In CardExchange, configure a **Comma-separated values** connection. Set **Database** to the containing shared folder, for example `\\HA-SERVER\share\unifi-badges` (leave off `employees.csv`). On the next page select `employees.csv` (possibly displayed as `employees#csv`) as **View name** and `UserID` as **Primary key**. This is a direct CSV data source; repeatedly importing rows into the sample internal database is unnecessary.

Use comma delimiter, double quote text qualifier, header row, and UTF-8 encoding. The file uses a UTF-8 BOM, CRLF Windows line endings and quoted fields. `schema.ini` explicitly declares the six original columns as text and ActiveEmployee as Bit for Microsoft Text providers; some native readers ignore it. Confirm ID is treated as text in your reader if employee numbers contain leading zeros.

| CSV column | Meaning / mapping |
| --- | --- |
| `UserID` | Stable UniFi UUID; use this as the unique record key. |
| `FirstName` | First name. |
| `LastName` | Last name. |
| `FullName` | First and last name joined with one space. Map the badge's single centered name box here. |
| `ID` | Existing UniFi **employee_number**, copied as text. Map the printed employee number here. It is not a generated row number. |
| `PhotoPath` | Windows path of a successfully downloaded photo, or blank. |
| `ActiveEmployee` | `true` for UniFi ACTIVE users; `false` for DEACTIVATED users. Declared as Bit in schema.ini. |

Changing the database connection requires mapping your current saved badge design to these CSV columns. The package does not modify your portrait layout or name box. Use CardExchange's Refresh data after a sync; automatic refresh behavior is controlled by CardExchange.

## Reliability and diagnostics

All users with `ACTIVE` or `DEACTIVATED` status are exported. Deactivation keeps the row and sets `ActiveEmployee=false`; reactivation sets it back to true under the same UserID. A deleted user disappears after the next successful sync. Unknown statuses abort the export to avoid guessing. People with no employee number remain in the export with a blank ID and a warning. Duplicate employee numbers are also reported; UserID remains the key. No NFC card numbers, PINs, emails or access policies are exported.

The exporter fetches every page before replacing the CSV. Bad credentials, permission errors, incomplete pagination, repeated records, invalid field types and failed writes preserve the last successful CSV. A change in total user count during pagination also aborts and retries on the next interval. It cannot detect every possible same-count change during a multi-page read.

Check Web UI status and the add-on Log tab. Errors do not print the token or full API responses. A previous export remains available during an outage, but may be stale; check last_success.

Photos use the documented static-avatar API only. Returned external URLs are never fetched with the token. Unknown avatar paths or failed photo requests produce warnings and retain an existing exported photo when available. Users without an avatar get a blank PhotoPath. Photos have content-specific filenames so writing a new photo does not break the previous CSV. Old photo files are retained and can be cleaned up manually when no badge client uses them.

The web panel is available through authenticated HA ingress only. No host web port is exposed. The add-on has no HA Core or Supervisor API access and uses no UniFi write endpoints.

## Sources

Implementation follows the supplied `api_reference.pdf`: sections 2.6–2.8, 3.1, 3.5 and 9.5. Home Assistant app manifest reference: https://contributors.home-assistant.io/apps/reference/configuration/. CardExchange database support: https://help.cardexchangesolutions.com/producer/en/using_databases.html.

## Updating from 1.0.0

Version 1.1.0 appends ActiveEmployee and includes deactivated users. Your existing name/ID mappings and CSV path stay the same. Update the add-on, then run Sync now. CardExchange may cache the old schema: close and reopen it, or reopen the database wizard and reselect the employees.csv view if the new field is missing. To restrict the badge list to current employees, configure a CardExchange filter for ActiveEmployee=true; the CSV itself intentionally retains deactivated people.
