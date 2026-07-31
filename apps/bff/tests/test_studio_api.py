import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_bff.main import create_app
from oneiroi_bff.settings import BffSettings


@pytest.mark.asyncio
async def test_create_job_and_cancel_isolated_by_user() -> None:
    transport = ASGITransport(app=create_app(BffSettings()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "conversationId": "demo",
            "draft": {
                "prompt": "A person opens a cabinet and reaches for a book.",
                "quality": "快速",
                "ratio": "16:9",
                "resolution": "720p",
                "duration": 5,
                "seed": 42,
                "firstFrame": {"name": "head.png", "url": "data:image/png;base64,abc"},
            },
        }
        response = await client.post("/v1/jobs/i2v", json=payload)
        assert response.status_code == 202
        job_id = response.json()["id"]

        hidden = await client.get(
            f"/v1/jobs/{job_id}", headers={"X-Oneiroi-User": "another-user"}
        )
        assert hidden.status_code == 404

        cancelled = await client.post(f"/v1/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["stage"] == "cancelled"


@pytest.mark.asyncio
async def test_asset_crud() -> None:
    transport = ASGITransport(app=create_app(BffSettings()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/assets",
            json={
                "title": "测试参考图",
                "type": "image",
                "previewUrl": "data:image/png;base64,abc",
            },
        )
        assert created.status_code == 201
        asset_id = created.json()["id"]

        listed = await client.get("/v1/assets")
        assert [item["id"] for item in listed.json()] == [asset_id]

        deleted = await client.delete(f"/v1/assets/{asset_id}")
        assert deleted.status_code == 204
        assert (await client.get("/v1/assets")).json() == []
