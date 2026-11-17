# UniFi Badge Export

For normal repository installation, upload the extracted package contents to a Git repository named `unifi-badge-export`. Keep `repository.yaml` and `unifi_badge_export/` at the root. Add the repository URL to Home Assistant's Add-on Store → menu → Repositories, then install UniFi Badge Export.

For optional local installation, extract the `unifi_badge_export` folder into Home Assistant's `/addons` local add-on directory. Keep the folder intact. See `unifi_badge_export/DOCS.md` for token permissions, shared-folder access and CardExchange mappings.

The `tests` folder contains offline verification and is not needed on the HA host. Run with `python3 -m unittest discover -s tests -v` from this package directory.
