from unittest.mock import AsyncMock, MagicMock
import pytest

from app.services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_send_text_whatsapp_uses_gupshup_endpoint(monkeypatch):
    svc = NotificationService()
    fake_response = MagicMock()
    fake_response.status_code = 200
    svc.http_client = MagicMock()
    svc.http_client.post = AsyncMock(return_value=fake_response)

    monkeypatch.setattr("app.services.notification_service.settings.gupshup_api_key", "k")
    monkeypatch.setattr("app.services.notification_service.settings.gupshup_app_name", "app")
    monkeypatch.setattr("app.services.notification_service.settings.whatsapp_business_number", "919999999999")

    ok = await svc.send_text_whatsapp("919876543210", "hello world")
    assert ok is True
    args, kwargs = svc.http_client.post.await_args
    assert "gupshup.io" in args[0]
    assert kwargs["data"]["destination"] == "919876543210"


@pytest.mark.asyncio
async def test_send_text_whatsapp_returns_false_when_unconfigured(monkeypatch):
    monkeypatch.setattr("app.services.notification_service.settings.gupshup_api_key", "")
    svc = NotificationService()
    ok = await svc.send_text_whatsapp("919876543210", "hello")
    assert ok is False
