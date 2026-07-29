from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_rule import AlertRule
from app.models.camera import Camera
from app.models.organization import Organization
from app.models.site import Site
from app.models.user import User


class SoftDeleteService:
    """Soft-delete / restore for the five entities that can be deleted today.

    Cascades mirror what the old ORM `delete-orphan` relationships used to do
    (org -> users/sites/cameras/alert_rules, site -> cameras), but as an
    explicit, reversible `deleted_at` sweep instead of an irreversible
    `db.delete()` cascade.
    """

    async def delete_organization(self, org: Organization, db: AsyncSession) -> None:
        now = datetime.now(timezone.utc)
        org.deleted_at = now
        for model in (User, Site, Camera, AlertRule):
            await db.execute(
                update(model)
                .where(model.org_id == org.id, model.deleted_at.is_(None))
                .values(deleted_at=now)
            )
        await db.flush()

    async def restore_organization(self, org: Organization, db: AsyncSession) -> None:
        org.deleted_at = None
        for model in (User, Site, Camera, AlertRule):
            await db.execute(
                update(model)
                .where(model.org_id == org.id, model.deleted_at.isnot(None))
                .values(deleted_at=None)
            )
        await db.flush()

    async def delete_site(self, site: Site, db: AsyncSession) -> None:
        now = datetime.now(timezone.utc)
        site.deleted_at = now
        await db.execute(
            update(Camera)
            .where(Camera.site_id == site.id, Camera.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        await db.flush()

    async def restore_site(self, site: Site, db: AsyncSession) -> None:
        site.deleted_at = None
        await db.execute(
            update(Camera)
            .where(Camera.site_id == site.id, Camera.deleted_at.isnot(None))
            .values(deleted_at=None)
        )
        await db.flush()

    async def delete_camera(self, camera: Camera, db: AsyncSession) -> None:
        camera.deleted_at = datetime.now(timezone.utc)
        await db.flush()

    async def restore_camera(self, camera: Camera, db: AsyncSession) -> None:
        camera.deleted_at = None
        await db.flush()

    async def delete_alert_rule(self, rule: AlertRule, db: AsyncSession) -> None:
        rule.deleted_at = datetime.now(timezone.utc)
        await db.flush()

    async def restore_alert_rule(self, rule: AlertRule, db: AsyncSession) -> None:
        rule.deleted_at = None
        await db.flush()

    async def delete_user(self, user: User, db: AsyncSession) -> None:
        user.deleted_at = datetime.now(timezone.utc)
        await db.flush()

    async def restore_user(self, user: User, db: AsyncSession) -> None:
        user.deleted_at = None
        await db.flush()


soft_delete_service = SoftDeleteService()
