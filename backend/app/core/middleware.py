import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import async_session_factory
from app.services.audit_log_service import audit_log_service


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = time.perf_counter() - start
        response.headers["X-Response-Time"] = f"{elapsed:.3f}s"
        return response


class ImpersonationAuditMiddleware(BaseHTTPMiddleware):
    """Logs every mutating request made during an impersonated session.

    Reads request.state.session (set by get_current_user, per Task 1) AFTER
    call_next() returns — at that point every route dependency, including
    auth, has already run. Requests that never reach an authenticated route
    (public endpoints, failed auth) simply have no request.state.session,
    handled via getattr's default.
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return response

        session = getattr(request.state, "session", None)
        impersonated_by = session.get("impersonated_by") if session else None
        if not impersonated_by:
            return response

        async with async_session_factory() as db:
            await audit_log_service.record(
                db,
                actor_user_id=uuid.UUID(impersonated_by["user_id"]),
                actor_username=impersonated_by["username"],
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                target_user_id=uuid.UUID(session["user_id"]),
                target_org_id=uuid.UUID(session["org_id"]) if session.get("org_id") else None,
            )
            await db.commit()

        return response
