"""Short-lived Vertex AI token broker for edge boxes.

Edge boxes (paired Agents) call the /api/edge/gemini-token route to obtain a
short-lived Vertex AI access token instead of holding a long-lived service
account key on hardware that could be physically stolen.

We mint the token via GCP's `impersonated_credentials` mechanism: Backend's
own service account (the ambient credentials from `google.auth.default()`)
impersonates itself, which lets us cap the resulting token's lifetime to the
requested TTL. This is the standard pattern for issuing short-lived tokens
without provisioning a second static secret.

PRODUCTION IAM PREREQUISITE
---------------------------
Self-impersonation is not implicit. The Backend service account must be
granted `roles/iam.serviceAccountTokenCreator` **on itself**, e.g.::

    gcloud iam service-accounts add-iam-policy-binding \\
        BACKEND_SA@PROJECT.iam.gserviceaccount.com \\
        --member="serviceAccount:BACKEND_SA@PROJECT.iam.gserviceaccount.com" \\
        --role="roles/iam.serviceAccountTokenCreator"

There is no IAM-provisioning code in this repo, so this binding must be
applied out of band. Without it the first real call fails with a 403 from
the IAM Credentials API, surfaced here as GeminiBrokerUnavailable.

CREDENTIAL LIFECYCLE
--------------------
The *source* credentials object is safe to cache at module scope — it just
represents Backend's own ambient identity — but it is resolved LAZILY, on
first use, never at import. `google.auth.default()` raises
DefaultCredentialsError in any environment without ADC (dev laptops, CI),
and this module is imported transitively from `main.py`, so resolving at
import time would take down the entire API rather than one endpoint. This
mirrors the deliberate lazy pattern in `app.services.gcs._get_client`.

What must NOT be shared or cached across requests is the *impersonated*
`Credentials` object itself (and its `.token`): a fresh one is minted on
every call to `mint_vertex_token`, so distinct agents/requests never see a
reused token.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request as GoogleAuthRequest

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

_lock = threading.Lock()
_source_creds = None
_project: str | None = None


class GeminiBrokerUnavailable(Exception):
    """The broker cannot mint a token in this environment.

    Raised instead of letting google.auth's DefaultCredentialsError (no ADC),
    AttributeError (ADC user credentials have no `service_account_email`), or
    a RefreshError (missing serviceAccountTokenCreator binding) escape as an
    unhandled 500. Route handlers map this to a clean 503.
    """


def _get_source_credentials():
    """Resolve and cache Backend's own ambient credentials, lazily.

    Not resolved at import time — see the module docstring.
    """
    global _source_creds, _project
    if _source_creds is None:
        with _lock:
            if _source_creds is None:
                _source_creds, _project = google.auth.default(scopes=_SCOPES)
    return _source_creds


def mint_vertex_token(ttl_seconds: int = 1800) -> tuple[str, datetime]:
    """Mint a fresh, short-lived Vertex AI access token.

    Creates a brand-new `impersonated_credentials.Credentials` object per
    call (never cached/reused across requests or agents) so tokens are not
    shared between callers.

    Returns ``(access_token, expires_at)`` where ``expires_at`` is the
    ACTUAL expiry reported by the credentials object after refresh, not a
    client-side `now + ttl` guess — callers refresh against the real expiry.

    Raises GeminiBrokerUnavailable if credentials can't be resolved or the
    impersonation call fails.
    """
    try:
        source = _get_source_credentials()
        service_account_email = getattr(source, "service_account_email", None)
        if not service_account_email:
            # ADC user/oauth credentials (a developer laptop, or CI running
            # as a human identity) have no service_account_email; there is
            # nothing to self-impersonate.
            raise GeminiBrokerUnavailable(
                "ambient credentials are not a service account; "
                "self-impersonation requires running as a service account"
            )
        target = impersonated_credentials.Credentials(
            source_credentials=source,
            target_principal=service_account_email,
            target_scopes=_SCOPES,
            lifetime=ttl_seconds,
        )
        target.refresh(GoogleAuthRequest())
    except GeminiBrokerUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize every auth failure
        logger.warning("Vertex token broker unavailable: %s", exc)
        raise GeminiBrokerUnavailable(str(exc)) from exc

    expires_at = target.expiry
    if expires_at is None:
        # Defensive only: google.auth populates .expiry on refresh. If a
        # library version ever doesn't, fall back to the requested TTL.
        logger.warning("impersonated credentials returned no expiry; using requested TTL")
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    elif expires_at.tzinfo is None:
        # google.auth reports expiry as a naive UTC datetime.
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return target.token, expires_at
