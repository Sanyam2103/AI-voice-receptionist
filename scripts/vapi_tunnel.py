from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

DEFAULT_PORT = 8000


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Open a public HTTPS tunnel to this machine so Vapi can POST "
            "tool calls to /api/vapi/webhook."
        )
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--provider",
        choices=("auto", "cloudflared", "ngrok"),
        default="auto",
    )
    args = parser.parse_args()
    provider = _resolve_provider(args.provider)

    print(
        "Keep FastAPI running in another terminal:\n"
        f"  uvicorn app:app --reload --port {args.port}\n"
    )
    print(
        "When the tunnel prints an https URL, set every Vapi tool Server URL to:\n"
        f"  https://<that-host>/api/vapi/webhook\n"
    )
    print("Ctrl+C stops the tunnel. Free URLs usually change each run.\n")
    subprocess.run(_command(provider, args.port), check=False)


def _resolve_provider(requested: str) -> str:
    if requested != "auto":
        if not shutil.which(requested):
            raise SystemExit(_install_hint(requested))
        return requested
    if shutil.which("cloudflared"):
        return "cloudflared"
    if shutil.which("ngrok"):
        return "ngrok"
    raise SystemExit(
        "No tunnel client found.\n"
        + _install_hint("cloudflared")
        + "\n"
        + _install_hint("ngrok")
    )


def _command(provider: str, port: int) -> list[str]:
    if provider == "cloudflared":
        return ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"]
    return ["ngrok", "http", str(port)]


def _install_hint(name: str) -> str:
    if name == "cloudflared":
        return "Install Cloudflare Tunnel: brew install cloudflared"
    return (
        "Install ngrok: brew install ngrok\n"
        "Then: ngrok config add-authtoken <token from https://dashboard.ngrok.com>"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
