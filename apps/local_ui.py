from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from apps.api.main import create_app
from apps.runner.companion import create_companion_app, run_worker_loop


def create_local_ui_app(*, database: str | Path, token: str | None = None):
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError("install the runner extra to serve the local UI") from exc
    app = FastAPI(title="Drug Discovery Agent Local UI", docs_url=None, redoc_url=None)
    index = Path(__file__).resolve().parent / "web" / "index.html"
    config = Path(__file__).resolve().parent / "web" / "config.js"
    llm_chat = Path(__file__).resolve().parent / "web" / "llm-chat.js"
    llm_worker = Path(__file__).resolve().parent / "web" / "llm-worker.js"
    downloads = Path(__file__).resolve().parent / "web" / "downloads"

    @app.get("/", include_in_schema=False)
    def web_ui():
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/config.js", include_in_schema=False)
    def web_config():
        return FileResponse(config, media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/llm-chat.js", include_in_schema=False)
    def web_llm_chat():
        return FileResponse(llm_chat, media_type="text/javascript")

    @app.get("/llm-worker.js", include_in_schema=False)
    def web_llm_worker():
        return FileResponse(llm_worker, media_type="text/javascript")

    @app.get("/companion-downloads.js", include_in_schema=False)
    def companion_downloads():
        return FileResponse(index.parent / "companion-downloads.js", media_type="text/javascript")

    app.mount("/downloads", StaticFiles(directory=downloads), name="companion-downloads")

    # Keep the old prefixed API available only when an explicit legacy token is
    # supplied. The browser now uses the automatically paired companion API.
    if token:
        app.mount("/api", create_app(database=database, bearer_tokens={token: "local-user"}))
    return app


def run_local_ui(*, token: str | None, port: int, database: str | Path) -> None:
    bridge_port = 8765
    if token is not None and len(token) < 32:
        raise ValueError("local UI token must contain at least 32 characters")
    if not 1024 <= port <= 65535 or port == bridge_port:
        raise ValueError("UI port must be non-privileged and different from bridge port 8765")
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("install the runner extra to serve the local UI") from exc

    origin = f"http://127.0.0.1:{port}"
    companion_origin = f"http://127.0.0.1:{bridge_port}"
    companion = create_companion_app(
        database=database,
        approval_base_url=companion_origin,
        allowed_origins=[origin],
        auto_approve_origins=[origin],
    )
    companion_server = uvicorn.Server(uvicorn.Config(
        companion, host="127.0.0.1", port=bridge_port, log_level="warning",
    ))
    threading.Thread(
        target=companion_server.run,
        daemon=True,
        name="drug-agent-companion",
    ).start()

    shutdown = threading.Event()
    threading.Thread(
        target=run_worker_loop,
        kwargs={
            "endpoint": f"{companion_origin}/api",
            "token": companion.state.service_token,
            "service": companion.state.runner_service,
            "shutdown": shutdown,
        },
        daemon=True,
        name="drug-agent-local-worker",
    ).start()
    app = create_local_ui_app(database=database, token=token)
    print(f"Drug Discovery Agent UI: {origin}", flush=True)
    print("Pairing is automatic; no token entry is required.", flush=True)
    threading.Timer(0.75, lambda: webbrowser.open(origin)).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=port)
    finally:
        shutdown.set()
        companion_server.should_exit = True
