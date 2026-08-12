from app.services.device_token_service import DeviceTokenService


def test_mint_returns_token_hash_and_token_id():
    token, hashed, token_id = DeviceTokenService.mint()
    assert isinstance(token, str)
    assert isinstance(hashed, str)
    assert isinstance(token_id, str)
    assert len(token) >= 32
    assert token != hashed
    assert token_id == DeviceTokenService.token_id(token)


def test_verify_accepts_correct_token():
    token, hashed, _ = DeviceTokenService.mint()
    assert DeviceTokenService.verify(token, hashed) is True


def test_verify_rejects_wrong_token():
    _, hashed, _ = DeviceTokenService.mint()
    assert DeviceTokenService.verify("not-the-real-token", hashed) is False
