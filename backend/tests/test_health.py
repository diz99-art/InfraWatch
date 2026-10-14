from fastapi.testclient import TestClient

from app.main import create_app


def test_health():
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "InfraWatch"}


def test_not_found():
    with TestClient(create_app()) as client:
        response = client.get("/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == 404


def test_unexpected_error_hides_details():
    app = create_app()

    @app.get("/broken")
    def broken():
        raise RuntimeError("private detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/broken")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": 500, "message": "Internal server error"}
    }
