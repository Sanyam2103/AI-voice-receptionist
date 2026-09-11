from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from grooming.config import DEFAULT_OAUTH_PORT, Settings, parse_oauth_port
from grooming.google import get_google_credentials, oauth_client_type


def _write_client(path: Path, client_type: str) -> Path:
    payload = {
        client_type: {
            "client_id": "test.apps.googleusercontent.com",
            "client_secret": "test-secret",
            "redirect_uris": [f"http://localhost:{DEFAULT_OAUTH_PORT}/"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_oauth_port_defaults_to_8080_and_reads_env(monkeypatch):
    assert parse_oauth_port(None) == 8080
    assert parse_oauth_port("") == 8080
    assert parse_oauth_port("9090") == 9090
    monkeypatch.delenv("GOOGLE_OAUTH_PORT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("GOOGLE_CALENDAR_ID", "")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "")
    settings = Settings.from_env()
    assert settings.google_oauth_port == DEFAULT_OAUTH_PORT == 8080
    monkeypatch.setenv("GOOGLE_OAUTH_PORT", "9090")
    assert Settings.from_env().google_oauth_port == 9090


def test_oauth_client_type_accepts_desktop_and_web(tmp_path: Path):
    desktop = _write_client(tmp_path / "desktop.json", "installed")
    web = _write_client(tmp_path / "web.json", "web")
    assert oauth_client_type(desktop) == "installed"
    assert oauth_client_type(web) == "web"
    service = tmp_path / "sa.json"
    service.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Desktop app"):
        oauth_client_type(service)


@pytest.mark.parametrize("client_type", ["installed", "web"])
def test_consent_uses_configured_loopback_port(tmp_path: Path, monkeypatch, client_type):
    captured = {}

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            captured["secrets_path"] = path
            return cls()

        def run_local_server(self, **kwargs):
            captured["kwargs"] = kwargs
            return SimpleNamespace(to_json=lambda: '{"token": "fake"}')

    monkeypatch.setattr("grooming.google.InstalledAppFlow", FakeFlow)
    credentials_path = _write_client(tmp_path / "credentials.json", client_type)
    token_path = tmp_path / "token.json"
    get_google_credentials(credentials_path, token_path, oauth_port=8080)
    assert captured["kwargs"]["host"] == "localhost"
    assert captured["kwargs"]["port"] == 8080
    assert captured["kwargs"]["redirect_uri_trailing_slash"] is True
    assert token_path.exists()


def test_consent_propagates_custom_oauth_port(tmp_path: Path, monkeypatch):
    captured = {}

    class FakeFlow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            return cls()

        def run_local_server(self, **kwargs):
            captured["kwargs"] = kwargs
            return SimpleNamespace(to_json=lambda: '{"token": "fake"}')

    monkeypatch.setattr("grooming.google.InstalledAppFlow", FakeFlow)
    credentials_path = _write_client(tmp_path / "credentials.json", "web")
    get_google_credentials(credentials_path, tmp_path / "token.json", oauth_port=9090)
    assert captured["kwargs"]["port"] == 9090
