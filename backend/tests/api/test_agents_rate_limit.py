import pytest
import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _clear_paircode_rate(test_user):
    from app.core.redis import get_redis

    r = await get_redis()
    await r.delete(f"paircode:rate:{test_user.id}")
    yield
    await r.delete(f"paircode:rate:{test_user.id}")


@pytest.mark.asyncio
async def test_pair_code_rate_limit(auth_client):
    for _ in range(5):
        resp = await auth_client.post("/api/agents/pair-codes")
        assert resp.status_code == 201, resp.text

    sixth = await auth_client.post("/api/agents/pair-codes")
    assert sixth.status_code == 429, sixth.text
