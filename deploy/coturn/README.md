# coturn deployment

Fallback-only TURN relay for live view when direct WebRTC P2P between
browser and edge box fails (symmetric NAT/CGNAT).

## Setup
1. `apt install coturn` on a small public-IP VM.
2. Copy `turnserver.conf` to `/etc/coturn/`, replace `static-auth-secret`
   and `realm`, provision a TLS cert (e.g. via certbot) at the paths
   referenced in the config.
3. Copy `nightwatch-coturn.service` to `/etc/systemd/system/`,
   `systemctl enable --now nightwatch-coturn`.
4. Set `TURN_SHARED_SECRET` (same value as `static-auth-secret`) and
   `TURN_URL` in Backend's environment so it can mint short-lived
   credentials for ICE server config.
