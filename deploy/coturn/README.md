# coturn deployment

Fallback-only TURN relay for live view when direct WebRTC P2P between
browser and edge box fails (symmetric NAT/CGNAT).

## Scope

**Backend + frontend wiring is in place; the agent/relay side is not.**

- Backend (`app/services/turn_credentials.py`, `GET /api/webrtc/ice-servers`)
  mints short-lived time-limited TURN credentials using coturn's
  `use-auth-secret` scheme, reading `turn_url`/`turn_shared_secret` from
  settings.
- Frontend (`WebRTCPlayer.tsx`) fetches `/api/webrtc/ice-servers` before
  constructing its `RTCPeerConnection` and includes the returned TURN entry
  alongside STUN — falling back to STUN-only if the fetch fails, so a TURN
  outage never blocks live view outright.
- **Not yet done:** the agent's and relay's own `webrtcsignal` peer
  connections (`agent/webrtcsignal/answer.go`, `relay/webrtcsignal/viewer.go`)
  still hardcode STUN only. For a connection to survive symmetric NAT/CGNAT
  on *both* ends, that side needs the same TURN wiring too — tracked as
  separate follow-up work, not done here.

## Setup
1. `apt install coturn` on a small public-IP VM.
2. Copy `turnserver.conf` to `/etc/coturn/`, replace `static-auth-secret`
   and `realm`, provision a TLS cert (e.g. via certbot) at the paths
   referenced in the config.
3. Copy `nightwatch-coturn.service` to `/etc/systemd/system/`,
   `systemctl enable --now nightwatch-coturn`.
4. Set `TURN_SHARED_SECRET` (same value as `static-auth-secret`) and
   `TURN_URL` (e.g. `turn.yourdomain.com:3478`) in Backend's environment —
   `GET /api/webrtc/ice-servers` returns STUN-only until both are set.
