from fastapi.testclient import TestClient

from app import app, get_chat_service


class FakeChat:
    def chat(self, message, session_id=None, phone=None):
        return {
            "message": f"reply: {message}",
            "session_id": session_id or "session-1",
        }


def test_health_and_chat_endpoint_without_live_services():
    app.dependency_overrides[get_chat_service] = lambda: FakeChat()
    try:
        client = TestClient(app)
        assert client.get("/health").json() == {"status": "ok"}
        response = client.post(
            "/api/chat", json={"message": "hello", "phone": "415-555-0190"}
        )
        assert response.status_code == 200
        assert response.json() == {
            "message": "reply: hello",
            "session_id": "session-1",
        }
    finally:
        app.dependency_overrides.clear()

