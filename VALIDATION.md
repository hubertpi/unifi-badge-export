# Verification

- 16 offline Python unittest checks pass: complete paging, repeated and truncated pages, changing totals, CSV quoting/Unicode/leading zeros, active/inactive status, deactivation/reactivation, unknown-status handling, missing and duplicate employee numbers, deliberate empty exports, preservation on fetch/validation/write failures, avatar API routing and fallback, token redaction, endpoint restriction, ingress restriction and manual sync.
- YAML configuration parses; option/schema keys agree. Python source compiles.
- ZIP integrity checked after packaging.
- Docker is not installed in the development workspace, so a container image build was not run here.
- No connection to the user's live UniFi Access, HA Supervisor, Samba share or Windows CardExchange was made. Installation and live CSV compatibility must be confirmed there.
