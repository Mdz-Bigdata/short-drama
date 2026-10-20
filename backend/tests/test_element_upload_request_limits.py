import asyncio

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.platform.request_limits import ElementUploadGuardMiddleware


def _guarded_app(
    *, maximum: int = 32, rate_limit: int = 10, byte_limit: int = 1024, total_timeout: float = 5
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        ElementUploadGuardMiddleware,
        model_max_bytes=maximum,
        image_max_bytes=maximum,
        global_concurrency=4,
        client_concurrency=2,
        session_rate_limit=rate_limit,
        ip_rate_limit=rate_limit,
        session_byte_limit=byte_limit,
        ip_byte_limit=byte_limit,
        rate_window_seconds=60,
        idle_timeout_seconds=1,
        total_timeout_seconds=total_timeout,
        session_verifier=lambda token: "test-user" if token == "valid" else None,
    )

    @app.post("/api/elements/{element_id}/model")
    async def receive_model(element_id: str, request: Request):
        size = len(await request.body())
        if request.query_params.get("delay") == "1":
            await asyncio.sleep(1)
        return {"id": element_id, "size": size}

    return app


def test_rejects_declared_oversized_upload_before_route_body_parsing():
    with TestClient(_guarded_app()) as client:
        response = client.post(
            "/api/elements/scene-1/model", content=b"x" * 33, cookies={"auth_token": "valid"}
        )
    assert response.status_code == 413


def test_rejects_chunked_upload_when_actual_stream_crosses_limit():
    def chunks():
        yield b"x" * 20
        yield b"y" * 20

    with TestClient(_guarded_app()) as client:
        response = client.post(
            "/api/elements/scene-1/model",
            content=chunks(),
            headers={"Transfer-Encoding": "chunked"},
            cookies={"auth_token": "valid"},
        )
    assert response.status_code == 413


def test_rate_limits_repeated_upload_attempts_before_reading_more_bodies():
    with TestClient(_guarded_app(maximum=128, rate_limit=1)) as client:
        first = client.post(
            "/api/elements/scene-1/model", content=b"ok", cookies={"auth_token": "valid"}
        )
        second = client.post(
            "/api/elements/scene-1/model", content=b"again", cookies={"auth_token": "valid"}
        )
    assert first.status_code == 200
    assert second.status_code == 429


def test_rejects_unauthenticated_upload_before_reading_the_body():
    with TestClient(_guarded_app(maximum=128)) as client:
        response = client.post("/api/elements/scene-1/model", content=b"small")
    assert response.status_code == 401


def test_enforces_total_processing_timeout_and_byte_budget():
    with TestClient(_guarded_app(maximum=128, byte_limit=6, total_timeout=0.01)) as client:
        timed_out = client.post(
            "/api/elements/scene-1/model?delay=1",
            content=b"ok",
            cookies={"auth_token": "valid"},
        )
        within_budget = client.post(
            "/api/elements/scene-1/model",
            content=b"abc",
            cookies={"auth_token": "valid"},
        )
        over_budget = client.post(
            "/api/elements/scene-1/model",
            content=b"de",
            cookies={"auth_token": "valid"},
        )
    assert timed_out.status_code == 408
    assert within_budget.status_code == 200
    assert over_budget.status_code == 429
