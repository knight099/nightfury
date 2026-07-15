import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_rule import AlertRule
from app.models.organization import Organization

WHATSAPP_RULE_NAME = "WhatsApp Instant Alerts"
MAX_CONTACTS = 4
PHONE_RE = re.compile(r"^\+\d{8,15}$")


class WhatsAppAlertService:
    """Manages an org's WhatsApp instant-alert contacts and keeps the
    auto-provisioned catch-all AlertRule in sync with them."""

    async def add_contact(self, org: Organization, number: str, db: AsyncSession) -> list[dict]:
        contacts = org.whatsapp_alert_contacts
        if len(contacts) >= MAX_CONTACTS:
            raise ValueError(f"Maximum of {MAX_CONTACTS} WhatsApp numbers per organization")
        self._validate_number(number)
        if any(c["number"] == number for c in contacts):
            raise ValueError("This number is already added")

        org.whatsapp_alert_contacts = contacts + [
            {"id": str(uuid4()), "number": number, "enabled": False}
        ]
        return await self._persist(org, db)

    async def update_contact(
        self,
        org: Organization,
        contact_id: str,
        db: AsyncSession,
        number: str | None = None,
        enabled: bool | None = None,
    ) -> list[dict]:
        contacts = org.whatsapp_alert_contacts
        idx = next((i for i, c in enumerate(contacts) if c["id"] == contact_id), None)
        if idx is None:
            raise LookupError("Contact not found")

        updated = dict(contacts[idx])
        if number is not None:
            self._validate_number(number)
            if any(c["number"] == number for c in contacts if c["id"] != contact_id):
                raise ValueError("This number is already added")
            updated["number"] = number
        if enabled is not None:
            updated["enabled"] = enabled

        new_contacts = list(contacts)
        new_contacts[idx] = updated
        org.whatsapp_alert_contacts = new_contacts

        return await self._persist(org, db)

    async def delete_contact(self, org: Organization, contact_id: str, db: AsyncSession) -> list[dict]:
        contacts = org.whatsapp_alert_contacts
        if not any(c["id"] == contact_id for c in contacts):
            raise LookupError("Contact not found")

        org.whatsapp_alert_contacts = [c for c in contacts if c["id"] != contact_id]
        return await self._persist(org, db)

    def _validate_number(self, number: str) -> None:
        if not PHONE_RE.match(number):
            raise ValueError("Number must be in +<countrycode><number> format")

    async def _persist(self, org: Organization, db: AsyncSession) -> list[dict]:
        await self._sync_alert_rule(org, db)
        await db.flush()
        return org.whatsapp_alert_contacts

    async def _sync_alert_rule(self, org: Organization, db: AsyncSession) -> None:
        enabled_numbers = [c["number"] for c in org.whatsapp_alert_contacts if c["enabled"]]

        result = await db.execute(
            select(AlertRule).where(
                AlertRule.org_id == org.id,
                AlertRule.name == WHATSAPP_RULE_NAME,
                AlertRule.deleted_at.is_(None),
            )
        )
        rule = result.scalar_one_or_none()

        if not enabled_numbers:
            if rule:
                rule.enabled = False
                rule.notify_contacts = []
            return

        contacts = [{"type": "whatsapp", "value": n} for n in enabled_numbers]
        if rule:
            rule.notify_contacts = contacts
            rule.enabled = True
        else:
            db.add(
                AlertRule(
                    org_id=org.id,
                    name=WHATSAPP_RULE_NAME,
                    cameras=[],
                    event_types=[],
                    min_severity="low",
                    zones=[],
                    notify_channels=["whatsapp"],
                    notify_contacts=contacts,
                    cooldown_seconds=60,
                    enabled=True,
                )
            )


whatsapp_alert_service = WhatsAppAlertService()
