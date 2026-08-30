# Vortex Telemetry (development companion)

This is a background-only Overwolf extension. It has no desktop or in-game
window. Its only job is to subscribe to VALORANT GEP events and send them to a
running Vortex instance on `127.0.0.1`, trying ports 8765 through 8814.

## Local setup

1. Install and sign in to Overwolf.
2. In Overwolf, open **Settings → About → Development options**.
3. Choose **Load unpacked extension** and select this folder.
4. Start Vortex, then start VALORANT. Keep Overwolf running in the tray.

Overwolf requires the account loading an unpacked extension to be enabled for
developer mode. This is a development package, not yet an installable public
Overwolf app. Production distribution requires an Overwolf application UID,
packaging it as an OPK, and Overwolf review.

Do not add any in-game windows or tactical prompts to this extension. It is
intentionally limited to forwarding the player’s own event data to Vortex.
