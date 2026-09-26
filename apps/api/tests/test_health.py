from fastapi.testclient import TestClient

from app.main import app


def test_openapi_loads() -> None:
    client = TestClient(app)
    assert client.get("/openapi.json").status_code == 200
