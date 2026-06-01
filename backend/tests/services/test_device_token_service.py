from app.services.device_token_service import DeviceTokenService


def test_mint_returns_token_and_hash():
    token, hashed = DeviceTokenService.mint()
    assert isinstance(token, str)
    assert isinstance(hashed, str)
    assert len(token) >= 32
    assert token != hashed


def test_verify_accepts_correct_token():
    token, hashed = DeviceTokenService.mint()
    assert DeviceTokenService.verify(token, hashed) is True


def test_verify_rejects_wrong_token():
    _, hashed = DeviceTokenService.mint()
    assert DeviceTokenService.verify("not-the-real-token", hashed) is False
