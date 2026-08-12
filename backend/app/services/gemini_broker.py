"""Short-lived Vertex AI token broker for edge boxes.

Edge boxes (paired Agents) call the /api/edge/gemini-token route to obtain a
short-lived Vertex AI access token instead of holding a long-lived service
account key on hardware that could be physically stolen.

We mint the token via GCP's `impersonated_credentials` mechanism: Backend's
own service account (the ambient credentials from `google.auth.default()`)
impersonates itself, which lets us cap the resulting token's lifetime to the
requested TTL. This is the standard pattern for issuing short-lived tokens
without provisioning a second static secret.

The *source* credentials object (`_source_creds`) is safe to share at module
scope — it just represents Backend's own ambient identity. What must NOT be
shared or cached across requests is the *impersonated* `Credentials` object
itself (and its `.token`): a fresh one is minted on every call to
`mint_vertex_token`, so distinct agents/requests never see a reused token.
"""

from datetime import datetime, timedelta, timezone

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request as GoogleAuthRequest

_source_creds, _project = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def mint_vertex_token(ttl_seconds: int = 1800) -> tuple[str, datetime]:
    """Mint a fresh, short-lived Vertex AI access token.

    Creates a brand-new `impersonated_credentials.Credentials` object per
    call (never cached/reused across requests or agents) so tokens are not
    shared between callers.
    """
    target = impersonated_credentials.Credentials(
        source_credentials=_source_creds,
        target_principal=_source_creds.service_account_email,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=ttl_seconds,
    )
    target.refresh(GoogleAuthRequest())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return target.token, expires_at
