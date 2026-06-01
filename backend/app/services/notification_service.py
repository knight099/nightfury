import hashlib
import hmac
import json
import logging

import httpx

from app.config import settings
from app.models.alert_rule import AlertRule
from app.models.event import Event

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=10)

    async def send(
        self,
        channel: str,
        recipient: str,
        event: Event,
        rule: AlertRule,
        webhook_url: str | None = None,
    ) -> bool:
        try:
            if channel == "whatsapp":
                return await self._send_whatsapp(recipient, event)
            elif channel == "email":
                return await self._send_email(recipient, event)
            elif channel == "webhook":
                return await self._send_webhook(webhook_url or recipient, event)
            else:
                logger.warning(f"Unknown channel: {channel}")
                return False
        except Exception as e:
            logger.error(f"Notification failed [{channel}→{recipient}]: {e}")
            return False

    async def _send_whatsapp(self, phone: str, event: Event) -> bool:
        if not settings.gupshup_api_key:
            logger.warning("WhatsApp not configured (no Gupshup API key)")
            return False

        message = (
            f"🚨 *{event.severity.upper()} Alert*\n\n"
            f"📷 Camera: {event.camera_id}\n"
            f"🕐 Time: {event.timestamp.strftime('%H:%M:%S')}\n"
            f"⚡ Event: {event.event_type.replace('_', ' ').title()}\n"
            f"📝 {event.description}\n\n"
            f"Confidence: {event.confidence:.0%}"
        )

        payload = {
            "channel": "whatsapp",
            "source": settings.whatsapp_business_number,
            "destination": phone,
            "message": json.dumps({"type": "text", "text": message}),
            "src.name": settings.gupshup_app_name,
        }

        resp = await self.http_client.post(
            "https://api.gupshup.io/wa/api/v1/msg",
            data=payload,
            headers={"apikey": settings.gupshup_api_key},
        )
        return resp.status_code == 200

    async def send_text_whatsapp(self, phone: str, text: str) -> bool:
        """Send a free-form text WhatsApp message (used by digests, not alerts)."""
        if not settings.gupshup_api_key:
            logger.warning("WhatsApp not configured (no Gupshup API key)")
            return False
        try:
            payload = {
                "channel": "whatsapp",
                "source": settings.whatsapp_business_number,
                "destination": phone,
                "message": json.dumps({"type": "text", "text": text}),
                "src.name": settings.gupshup_app_name,
            }
            resp = await self.http_client.post(
                "https://api.gupshup.io/wa/api/v1/msg",
                data=payload,
                headers={"apikey": settings.gupshup_api_key},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("send_text_whatsapp failed: %s", e)
            return False

    async def _send_email(self, email: str, event: Event) -> bool:
        if not settings.sendgrid_api_key:
            logger.warning("Email not configured (no SendGrid API key)")
            return False

        subject = f"[{event.severity.upper()}] {event.event_type.replace('_', ' ').title()} detected"
        html_body = f"""
        <div style="font-family: sans-serif; background: #0D0D0D; color: #F5F5F5; padding: 20px;">
            <h2 style="color: #1E90FF;">🚨 {event.severity.upper()} Alert</h2>
            <p><strong>Event:</strong> {event.event_type.replace('_', ' ').title()}</p>
            <p><strong>Time:</strong> {event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p><strong>Description:</strong> {event.description}</p>
            <p><strong>Confidence:</strong> {event.confidence:.0%}</p>
            <p><img src="{event.snapshot_url}" style="max-width: 600px; border-radius: 8px;" /></p>
        </div>
        """

        payload = {
            "personalizations": [{"to": [{"email": email}]}],
            "from": {"email": settings.sendgrid_from_email, "name": "Nightwatch Alerts"},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}],
        }

        resp = await self.http_client.post(
            "https://api.sendgrid.com/v3/mail/send",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
        )
        return resp.status_code in (200, 202)

    async def _send_webhook(self, url: str, event: Event) -> bool:
        payload = {
            "event_id": str(event.id),
            "event_type": event.event_type,
            "severity": event.severity,
            "confidence": event.confidence,
            "description": event.description,
            "camera_id": str(event.camera_id),
            "site_id": str(event.site_id),
            "timestamp": event.timestamp.isoformat(),
            "snapshot_url": event.snapshot_url,
            "clip_url": event.clip_url,
        }

        body = json.dumps(payload, sort_keys=True)
        signature = hmac.HMAC(
            settings.secret_key.encode(), body.encode(), hashlib.sha256
        ).hexdigest()

        resp = await self.http_client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Nightwatch-Signature": signature,
            },
        )
        return 200 <= resp.status_code < 300


notification_service = NotificationService()
