# coturn deployment

Fallback-only TURN relay for live view when direct WebRTC P2P between
browser and edge box fails (symmetric NAT/CGNAT).

## Scope

**This task sets up the coturn server itself, and nothing else.**

No code in this branch mints or uses TURN credentials — not the backend, not
the agent, not the frontend. There is no `TURN_SHARED_SECRET` reader, no
credential-minting endpoint, and no `turn:` URL anywhere in the ICE server
configuration (the agent's `webrtcsignal` still uses a STUN server only).

All of that is future work:
- Backend: read `TURN_SHARED_SECRET`/`TURN_URL` and expose short-lived
  time-limited TURN credentials (the coturn `use-auth-secret` scheme).
- Frontend + agent: include those credentials as an ICE server on the
  `RTCPeerConnection` config.

Until that exists, the server deployed here is inert — nothing will use it.

## Setup
1. `apt install coturn` on a small public-IP VM.
2. Copy `turnserver.conf` to `/etc/coturn/`, replace `static-auth-secret`
   and `realm`, provision a TLS cert (e.g. via certbot) at the paths
   referenced in the config.
3. Copy `nightwatch-coturn.service` to `/etc/systemd/system/`,
   `systemctl enable --now nightwatch-coturn`.
4. (Future) Once the backend gains a TURN credential endpoint, set
   `TURN_SHARED_SECRET` (same value as `static-auth-secret`) and `TURN_URL`
   in Backend's environment. Nothing reads these variables today.
