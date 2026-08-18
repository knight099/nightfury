# Deploying coturn — step-by-step

Follow this when you have a GCP project ready and a public-IP VM to dedicate
to the TURN relay. It's a small box — TURN only relays media for the
fraction of live-view sessions that can't connect peer-to-peer, it's not
in the path for every viewer.

## 0. Prerequisites

- A GCP project with billing enabled (same one as the rest of Nightwatch, or a separate one — doesn't matter, this box has no dependency on the others).
- A domain you control, if you want TLS (recommended before onboarding real trial users — see step 5). If you don't have one yet, you can start on plain UDP/TCP port 3478 with no TLS and add it later; note that as a known gap, not a blocker for an internal/dev trial.
- `gcloud` CLI installed and authenticated (`gcloud auth login`), or use the GCP Console UI if you prefer clicking over typing.

## 1. Create the VM

Smallest practical size — coturn is lightweight; `e2-small` (2 vCPU burst, 2GB RAM) is comfortable for a handful of pilot users.

```bash
gcloud compute instances create nightwatch-coturn \
  --zone=asia-south1-a \
  --machine-type=e2-small \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --tags=coturn
```

Pick whichever `--zone` is closest to your pilot users (`asia-south1-a` = Mumbai, if that's where your trial sites are). Note the external IP it prints — you'll need it for DNS and for the backend's `TURN_URL`.

## 2. Open the firewall

coturn needs UDP/TCP 3478 (STUN/TURN) and 5349 (TLS variant), plus a UDP range for the actual relayed media (coturn's default relay port range is 49152–65535, but for a small pilot you can narrow it — see the optional `min-port`/`max-port` note in step 4).

```bash
gcloud compute firewall-rules create nightwatch-coturn-turn \
  --allow=tcp:3478,udp:3478,tcp:5349,udp:5349 \
  --target-tags=coturn \
  --source-ranges=0.0.0.0/0

gcloud compute firewall-rules create nightwatch-coturn-relay \
  --allow=udp:49152-65535 \
  --target-tags=coturn \
  --source-ranges=0.0.0.0/0
```

(If you'd rather not open 16K ports to the world, add `min-port=49160` / `max-port=49200` — or similar, a few dozen ports — to `turnserver.conf` in step 4, and narrow the second firewall rule to match. Fine to skip for a first trial; tighten before wider rollout.)

## 3. SSH in and install coturn

```bash
gcloud compute ssh nightwatch-coturn --zone=asia-south1-a

# on the VM:
sudo apt update
sudo apt install -y coturn certbot
```

## 4. Copy the config and fill in real values

From your local machine, copy the two files already in this repo up to the VM:

```bash
gcloud compute scp deploy/coturn/turnserver.conf nightwatch-coturn:~/turnserver.conf --zone=asia-south1-a
gcloud compute scp deploy/coturn/nightwatch-coturn.service nightwatch-coturn:~/nightwatch-coturn.service --zone=asia-south1-a
```

Back on the VM, edit `~/turnserver.conf`:

- `realm=turn.yourdomain.com` → your real subdomain (step 5), or the VM's external IP if you're skipping TLS for now.
- `static-auth-secret=CHANGE_ME_SHARED_WITH_BACKEND` → generate a real secret and put it here:
  ```bash
  openssl rand -hex 32
  ```
  **Save this value somewhere safe — you'll paste the exact same string into the backend's `TURN_SHARED_SECRET` env var in step 6. If they don't match, every credential the backend mints will be rejected by coturn.**

Then move both files into place:

```bash
sudo mv ~/turnserver.conf /etc/coturn/turnserver.conf
sudo mv ~/nightwatch-coturn.service /etc/systemd/system/nightwatch-coturn.service
```

## 5. TLS certificate (skip if going IP-only for now)

Point your subdomain's DNS A record at the VM's external IP first, then:

```bash
sudo certbot certonly --standalone -d turn.yourdomain.com
sudo mkdir -p /etc/coturn
sudo cp /etc/letsencrypt/live/turn.yourdomain.com/fullchain.pem /etc/coturn/cert.pem
sudo cp /etc/letsencrypt/live/turn.yourdomain.com/privkey.pem /etc/coturn/key.pem
```

(`certbot certonly --standalone` briefly needs port 80 free — stop anything else listening on it first, or use the `--webroot` method if you already run a web server on this box, which you shouldn't need to for this VM.)

Certs renew automatically via certbot's systemd timer, but coturn won't pick up a renewed cert without a restart — add a renewal hook:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/coturn-restart.sh <<'EOF'
#!/bin/sh
cp /etc/letsencrypt/live/turn.yourdomain.com/fullchain.pem /etc/coturn/cert.pem
cp /etc/letsencrypt/live/turn.yourdomain.com/privkey.pem /etc/coturn/key.pem
systemctl restart nightwatch-coturn
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/coturn-restart.sh
```

If skipping TLS for now: comment out or delete the `cert=`/`pkey=`/`tls-listening-port=` lines in `turnserver.conf` so coturn doesn't fail to start looking for certs that don't exist.

## 6. Start coturn

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nightwatch-coturn
sudo systemctl status nightwatch-coturn
```

Should show `active (running)`. Check logs at `/var/log/coturn.log` if not.

## 7. Point the backend at it

Wherever the backend's environment is configured (`.env` for local, Cloud Run env vars / Secret Manager for prod — see the root `CLAUDE.md`'s backend deployment section), set:

```
TURN_URL=turn.yourdomain.com:3478
TURN_SHARED_SECRET=<the exact openssl rand -hex 32 value from step 4>
```

(If you skipped TLS and are using the raw IP: `TURN_URL=<vm-external-ip>:3478`.)

Restart/redeploy the backend so it picks up the new env vars. `GET /api/webrtc/ice-servers` returns STUN-only until both vars are set — no code changes needed, this is purely config.

## 8. Verify end-to-end

1. From the frontend, open live view for any camera whose agent has a control-socket connection.
2. Open the browser's DevTools → Network tab, find the call to `/api/webrtc/ice-servers` — confirm the response includes a `turn:` entry (not just `stun:`).
3. Chrome's `chrome://webrtc-internals` page, while the connection is active, shows the ICE candidate pairs — look for one using `relay` as the candidate type, which confirms TURN actually got used (it'll usually still prefer a direct/`srflx` pair if one succeeds — TURN only shows as the winning pair when direct P2P genuinely failed, which is expected and fine).

## Known gaps (tracked, not blockers for a first trial)

- The agent's and relay's own WebRTC peer connections (`agent/webrtcsignal/answer.go`, `relay/webrtcsignal/viewer.go`) still hardcode STUN-only — only the browser side got TURN wired in. For a connection to survive symmetric NAT/CGNAT on *both* ends, that side needs the same treatment eventually.
- `min-port`/`max-port` narrowing (step 2's optional note) — worth doing before opening this up beyond a handful of trial users, to reduce the firewall's exposed surface.
