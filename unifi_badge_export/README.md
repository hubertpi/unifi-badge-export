# UniFi Badge Export

Exports active UniFi Access users to a CSV database for CardExchange Producer Premium.
Runs locally, reads the Access API using a token, and refreshes the same CSV every five minutes.
Includes a Home Assistant web panel with status, Sync now and Download CSV.

Built against the supplied UniFi Access API reference for an Access 4.3.24 installation.
Names and employee numbers come directly from UniFi. This add-on does not change UniFi users or door settings.
No live console or Home Assistant installation was available for integration testing.
