import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditLogService:
    async def record(
        self,
        db: AsyncSession,
        actor_user_id: uuid.UUID,
        actor_username: str,
        method: str,
        path: str,
        status_code: int,
        target_user_id: uuid.UUID | None = None,
        target_org_id: uuid.UUID | None = None,
    ) -> None:
        db.add(
            AuditLog(
                actor_user_id=actor_user_id,
                actor_username=actor_username,
                target_user_id=target_user_id,
                target_org_id=target_org_id,
                method=method,
                path=path,
                status_code=status_code,
            )
        )
        await db.flush()


audit_log_service = AuditLogService()
