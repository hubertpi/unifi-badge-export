# UniFi Badge Export

Home Assistant add-on that exports UniFi Access people with an ActiveEmployee true/false field to a shared CSV for CardExchange Producer Premium. Includes scheduled/manual sync, status, optional photos and preservation of the last successful CSV.

## Install from this repository

1. In Home Assistant, open Settings → Add-ons → Add-on Store → menu → Repositories. Add `https://github.com/hubertpi/unifi-badge-export`.
2. Install **UniFi Badge Export**. Read its Documentation tab for configuration and CSV mappings.

[Add repository to Home Assistant](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fhubertpi%2Funifi-badge-export)

The repository must be readable by the HA Supervisor. A public repository is the simplest setup; there are no tokens or employee data in this source package. Enter the Access API token in the installed add-on's Configuration tab.

Supervisor builds the container on your HA machine. No GitHub Actions or prebuilt image registry is required. See [configuration and CardExchange setup](unifi_badge_export/DOCS.md) and [verification](VALIDATION.md).
