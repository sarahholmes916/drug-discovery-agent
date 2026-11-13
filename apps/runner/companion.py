from __future__ import annotations

import secrets
import threading
import signal
import time
import webbrowser
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlsplit

from apps.api.main import create_app as create_control_plane
from pydantic import BaseModel, ConfigDict, Field

from .bridge import create_bridge
from .cloud import PollingControlPlaneClient
from .doctor import cloud_capabilities, collect_capabilities
from .pairing import PairingLaunch, PairingManager
from .project_uploads import (
    MAX_LIGAND_FILES,
    ProjectUploadOptions,
    create_project_from_uploads,
    inspect_receptor_upload,
)
from .registry import RunnerRegistry, runner_home
from .service import LocalRunnerService
from .tool_install import ToolInstallManager
from .tool_paths import activate_managed_tools


_APPROVAL_PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pair Drug Discovery Agent</title>
<style>
body{font:16px system-ui;max-width:620px;margin:10vh auto;padding:0 1.25rem;color:#18202a}
.card{border:1px solid #ccd4dc;border-radius:12px;padding:1.5rem;box-shadow:0 8px 30px #0001}
.origin{font-family:ui-monospace,monospace;overflow-wrap:anywhere;background:#f5f7f9;padding:.75rem;border-radius:6px}
button{padding:.65rem 1.1rem;margin:.4rem .4rem .2rem 0;border-radius:6px;border:1px solid #9aa6b2;cursor:pointer}
#approve{color:white;background:#165d9c;border-color:#165d9c}.muted{color:#647080}
</style>
<main class="card">
<h1>Connect this website?</h1>
<p>The following website wants to use Drug Discovery Agent on this computer:</p>
<p class="origin" id="origin">Unknown website</p>
<p class="muted">Molecular inputs and results stay on this computer. Only approve a website you recognize.</p>
<button id="approve">Allow this website</button><button id="deny">Deny</button>
<p id="status" aria-live="polite"></p>
</main>
<script>
const values=new URLSearchParams(location.hash.slice(1)),requestId=values.get('request_id'),secret=values.get('secret');
document.querySelector('#origin').textContent=values.get('origin')||'Unknown website';
async function decide(decision){
 const status=document.querySelector('#status');
 try{
  const response=await fetch('/v1/pairing/'+encodeURIComponent(requestId)+'/'+decision,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approval_secret:secret})});
  if(!response.ok)throw new Error('The pairing request expired or was already used.');
  status.textContent=decision==='approve'?'Connected. You can close this tab and return to the app.':'Connection denied. You can close this tab.';
  document.querySelectorAll('button').forEach(button=>button.disabled=true);
  location.hash='';
 }catch(error){status.textContent=error.message}
}
document.querySelector('#approve').onclick=()=>decide('approve');
document.querySelector('#deny').onclick=()=>decide('deny');
</script>
</html>
"""


class PairingApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_secret: str = Field(min_length=32, max_length=256)


def _origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _approval_url(base_url: str, launch: PairingLaunch) -> str:
    fragment = urlencode({
        "request_id": launch.request_id,
        "secret": launch.approval_secret,
        "origin": launch.origin,
    })
    return f"{base_url.rstrip('/')}/pair/approve#{fragment}"


def create_companion_app(
    *,
    database: str | Path,
    approval_base_url: str = "http://127.0.0.1:8765",
    allowed_origins: list[str] | None = None,
    auto_approve_origins: list[str] | None = None,
    registry: RunnerRegistry | None = None,
    service: LocalRunnerService | None = None,
    pairing: PairingManager | None = None,
    tool_installs: ToolInstallManager | None = None,
    approval_opener: Callable[[str], object] = webbrowser.open,
    projects_root: str | Path | None = None,
):
    try:
        from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import HTMLResponse
    except ImportError as exc:
        raise RuntimeError("install the runner extra to serve the companion") from exc
    # BackgroundTasks is imported lazily because FastAPI is a runner extra. Make
    # it visible when FastAPI resolves postponed endpoint annotations.
    globals()["BackgroundTasks"] = BackgroundTasks
    globals()["Request"] = Request

    activate_managed_tools()
    runner_registry = registry or RunnerRegistry()
    runner_service = service or LocalRunnerService(runner_registry)
    install_manager = tool_installs or ToolInstallManager()
    persisted_origins = runner_registry.trusted_origins() if allowed_origins is None else []
    effective_origins = allowed_origins if allowed_origins is not None else persisted_origins
    automatic_origins = frozenset(auto_approve_origins or [])
    if any(origin not in effective_origins for origin in automatic_origins):
        raise ValueError("automatic pairing origins must also be explicitly allowed")
    if any(urlsplit(origin).hostname not in {"127.0.0.1", "localhost", "::1"}
           for origin in automatic_origins):
        raise ValueError("automatic pairing is restricted to loopback UI origins")
    pairing_manager = pairing or PairingManager(
        allowed_origins=effective_origins,
        learn_first_origin=not effective_origins,
        on_first_origin_approved=runner_registry.trust_origin,
    )
    service_token = secrets.token_urlsafe(48)
    approval_origin = _origin_of(approval_base_url)
    local_projects_root = Path(projects_root) if projects_root else runner_home() / "projects"

    app = FastAPI(title="Drug Discovery Agent Companion", docs_url=None, redoc_url=None)
    if effective_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=effective_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        )
    else:
        # An unconfigured build may receive an HTTPS pairing request, but access
        # is still denied until the exact origin is approved locally.
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"https://[^/]+|http://(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?",
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        )

    def browser_origin(origin: str | None) -> str:
        if not origin or not pairing_manager.accepts_origin(origin):
            raise HTTPException(status_code=403, detail="website origin is not allowed to pair")
        return origin

    @app.get("/v1/companion")
    def discovery(origin: str | None = Header(default=None)):
        accepted_origin = browser_origin(origin)
        return {
            "status": "ready",
            "service": "drug-agent-companion",
            "pairing_required": True,
            "automatic_pairing": accepted_origin in automatic_origins,
        }

    @app.post("/v1/pairing/requests", status_code=201)
    def begin_pairing(
        background_tasks: BackgroundTasks,
        origin: str | None = Header(default=None),
        content_type: str = Header(default=""),
        x_requested_with: str = Header(default=""),
    ):
        if content_type.split(";", 1)[0] != "application/json":
            raise HTTPException(status_code=415, detail="JSON pairing requests are required")
        if x_requested_with != "DrugDiscoveryAgent":
            raise HTTPException(status_code=400, detail="invalid pairing client")
        accepted_origin = browser_origin(origin)
        launch = pairing_manager.begin(accepted_origin)
        if accepted_origin in automatic_origins:
            # The combined localhost UI and companion are started by the same
            # process and are origin-bound. Reissue an ephemeral browser session
            # silently after a restart; hosted origins still require approval.
            if not pairing_manager.approve(launch.request_id, launch.approval_secret):
                raise HTTPException(status_code=409, detail="automatic pairing request expired")
        else:
            background_tasks.add_task(approval_opener, _approval_url(approval_base_url, launch))
        return {
            "request_id": launch.request_id,
            "status": "pending",
            "expires_in": max(0, int(launch.expires_at - time.time())),
        }

    @app.get("/v1/pairing/requests/{request_id}")
    def pairing_status(request_id: str, origin: str | None = Header(default=None)):
        try:
            return pairing_manager.status(request_id, browser_origin(origin))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def decide(
        request_id: str,
        payload: PairingApproval,
        approve: bool,
        origin: str | None,
    ) -> dict[str, bool]:
        if origin != approval_origin:
            raise HTTPException(status_code=403, detail="approval must come from the local confirmation page")
        accepted = (
            pairing_manager.approve(request_id, payload.approval_secret)
            if approve else pairing_manager.deny(request_id, payload.approval_secret)
        )
        if not accepted:
            raise HTTPException(status_code=409, detail="pairing request expired or was already decided")
        return {"accepted": True}

    @app.post("/v1/pairing/{request_id}/approve")
    def approve_pairing(
        request_id: str,
        payload: PairingApproval,
        origin: str | None = Header(default=None),
    ):
        return decide(request_id, payload, True, origin)

    @app.post("/v1/pairing/{request_id}/deny")
    def deny_pairing(
        request_id: str,
        payload: PairingApproval,
        origin: str | None = Header(default=None),
    ):
        return decide(request_id, payload, False, origin)

    @app.get("/pair/approve", response_class=HTMLResponse, include_in_schema=False)
    def approval_page():
        return HTMLResponse(
            _APPROVAL_PAGE,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )

    def authorize_browser_request(request: Request) -> str:
        origin = browser_origin(request.headers.get("origin"))
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="paired companion session required")
        token = authorization.removeprefix("Bearer ")
        if not pairing_manager.authorize(origin, token):
            raise HTTPException(status_code=401, detail="paired companion session required")
        return origin

    @app.get("/v1/tools/installers")
    def tool_installers(request: Request):
        authorize_browser_request(request)
        return {"installers": install_manager.catalog()}

    @app.post("/v1/tools/{tool_id}/install", status_code=202)
    def install_tool(tool_id: str, request: Request):
        authorize_browser_request(request)
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise HTTPException(status_code=415, detail="JSON install requests are required")
        try:
            return install_manager.start(tool_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="automatic setup is unavailable for this tool") from exc

    @app.get("/v1/tools/installations/{task_id}")
    def tool_installation_status(task_id: str, request: Request):
        authorize_browser_request(request)
        try:
            return install_manager.status(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown tool installation") from exc

    @app.post("/v1/receptor/sequence")
    async def receptor_sequence(request: Request):
        authorize_browser_request(request)
        if request.headers.get("content-type", "").split(";", 1)[0] != "multipart/form-data":
            raise HTTPException(status_code=415, detail="multipart receptor upload required")
        try:
            form = await request.form(max_files=1, max_fields=2)
            receptor_structure = form.get("receptor_structure")
            protein_chain = form.get("protein_chain", "A")
            if not hasattr(receptor_structure, "read"):
                raise ValueError("a receptor PDB or mmCIF structure is required")
            if not isinstance(protein_chain, str):
                raise ValueError("protein_chain must be text")
            extracted = await inspect_receptor_upload(
                receptor_structure,
                protein_chain.strip() or "A",
            )
            return extracted.as_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/projects/import", status_code=201)
    async def import_local_project(request: Request):
        authorize_browser_request(request)
        if request.headers.get("content-type", "").split(";", 1)[0] != "multipart/form-data":
            raise HTTPException(status_code=415, detail="multipart project upload required")
        try:
            form = await request.form(max_files=MAX_LIGAND_FILES + 2, max_fields=20)
            receptor_structure = form.get("receptor_structure")
            receptor_pdbqt = form.get("receptor_pdbqt")
            ligand_files = list(form.getlist("ligands"))
            if not hasattr(receptor_structure, "read"):
                raise ValueError("a receptor PDB or mmCIF structure is required")
            if receptor_pdbqt is not None and not hasattr(receptor_pdbqt, "read"):
                raise ValueError("the receptor PDBQT input must be a file")
            if any(not hasattr(upload, "read") for upload in ligand_files):
                raise ValueError("ligand inputs must be SDF files")

            def text_field(name: str, default: str = "") -> str:
                value = form.get(name, default)
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be text")
                return value.strip()

            def boolean_field(name: str) -> bool:
                return text_field(name, "false").lower() in {"1", "true", "yes", "on"}

            def integer_field(name: str, default: int) -> int:
                try:
                    return int(text_field(name, str(default)))
                except ValueError as exc:
                    raise ValueError(f"{name} must be a whole number") from exc

            options = ProjectUploadOptions(
                project_id=text_field("project_id"),
                display_name=text_field("display_name") or text_field("project_id"),
                pocketminer=boolean_field("pocketminer"),
                boltz_constrained=boolean_field("boltz_constrained"),
                boltz_unconstrained=boolean_field("boltz_unconstrained"),
                downstream_ligand_count=integer_field("downstream_ligand_count", 50),
                downstream_selection_metric=text_field(
                    "downstream_selection_metric", "best_affinity"
                ),
                protein_sequence=text_field("protein_sequence") or None,
                protein_chain=text_field("protein_chain", "A") or "A",
                receptor_preparation=text_field("receptor_preparation", "provided_pdbqt"),
                remove_waters=boolean_field("remove_waters"),
                heterogens=text_field("heterogens", "review"),
                alternate_locations=text_field("alternate_locations", "review"),
                preparation_instructions=text_field("preparation_instructions") or None,
                agent_notes=text_field("agent_notes") or None,
                boltz_accelerator=text_field("boltz_accelerator", "gpu"),
            )
            if options.boltz_accelerator not in {"gpu", "cpu"}:
                raise ValueError("Boltz accelerator must be gpu or cpu")
            layout, config, uploaded_bytes = await create_project_from_uploads(
                options=options,
                receptor_structure=receptor_structure,
                receptor_pdbqt=receptor_pdbqt,
                ligand_files=ligand_files,
                projects_root=local_projects_root,
                registry=runner_registry,
            )
            return {
                "project_id": config.project.id,
                "display_name": config.project.display_name or config.project.id,
                "uploaded_file_count": 1 + len(ligand_files) + int(receptor_pdbqt is not None),
                "generated_file_count": int(config.target.preparation.method == "meeko"),
                "uploaded_bytes": uploaded_bytes,
                "workflow": config.workflow.value,
                "pocket_mode": config.pocket.mode,
                "receptor_preparation": config.target.preparation.method,
                "downstream_selection": {
                    "count": config.analysis.vina_shortlist,
                    "metric": config.analysis.vina_selection_metric,
                },
                "registered": layout.root.is_dir(),
            }
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def resolve_browser_token(token: str, origin: str | None) -> str | None:
        if origin and pairing_manager.authorize(origin, token):
            return "local-user"
        return None

    control_plane = create_control_plane(
        database=database,
        bearer_tokens={service_token: "local-user"},
        bearer_resolver=resolve_browser_token,
    )
    bridge = create_bridge(
        projects=runner_registry.load().get("projects", {}),
        cancel_run=runner_service.cancel,
        resume_run=runner_service.resume,
        token_authorizer=pairing_manager.authorize,
        origin_validator=pairing_manager.accepts_origin,
        project_resolver=runner_registry.project_root,
        project_lister=lambda: runner_registry.load().get("projects", {}),
    )
    app.mount("/api", control_plane)
    app.mount("/", bridge)
    app.state.pairing = pairing_manager
    app.state.runner_service = runner_service
    app.state.service_token = service_token
    app.state.tool_installs = install_manager
    return app


def run_worker_loop(
    *,
    endpoint: str,
    token: str,
    service: LocalRunnerService,
    shutdown: threading.Event,
    poll_interval: float = 1.0,
) -> None:
    client = PollingControlPlaneClient(endpoint, token, timeout_seconds=5)
    capabilities = cloud_capabilities(collect_capabilities())
    while not shutdown.is_set():
        try:
            client.heartbeat({
                "machine_id": "localhost_companion",
                "status": "CONNECTED",
                "capabilities": capabilities,
            })
            job = client.claim_job("localhost_companion")
            if job:
                sanitized = job.get("sanitized_config", {})
                project_id = sanitized.get("project_id") if isinstance(sanitized, dict) else None
                if not isinstance(project_id, str):
                    raise ValueError("claimed companion job has no opaque project_id")
                job_id, run_id = str(job["job_id"]), str(job["run_id"])
                finished = threading.Event()

                def watch_cancellation() -> None:
                    while not finished.wait(max(1.0, poll_interval)):
                        if client.job_state(job_id) == "CANCEL_REQUESTED":
                            service.cancel(run_id)
                            return

                watcher = threading.Thread(
                    target=watch_cancellation,
                    daemon=True,
                    name=f"cancel-{run_id}",
                )
                watcher.start()
                try:
                    service.start_assigned(
                        project_id,
                        run_id,
                        progress=lambda payload: client.report_event(job_id, payload),
                    )
                except Exception:
                    # A claimed job must always reach a terminal state. Keep the
                    # browser-facing event generic so local paths and exception
                    # details remain in the local process only.
                    client.report_event(job_id, {
                        "run_id": run_id,
                        "stage": "INGEST_PROJECT",
                        "status": "FAILED",
                        "completed": 0,
                        "total": 1,
                        "failed": 1,
                        "message_code": "stage_failed",
                    })
                finally:
                    finished.set()
                    watcher.join(timeout=max(2.0, poll_interval + 1))
        except Exception:
            # Startup races and scientific failures are retried or persisted by
            # the existing control-plane and LocalRunnerService contracts.
            shutdown.wait(poll_interval)
            continue
        shutdown.wait(poll_interval)


def run_companion(
    *,
    port: int,
    database: str | Path,
    allowed_origins: list[str] | None = None,
) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("companion port must be between 1024 and 65535")
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("install the runner extra to serve the companion") from exc

    endpoint = f"http://127.0.0.1:{port}"
    app = create_companion_app(
        database=database,
        approval_base_url=endpoint,
        allowed_origins=allowed_origins,
    )
    shutdown = threading.Event()
    worker = threading.Thread(
        target=run_worker_loop,
        kwargs={
            "endpoint": f"{endpoint}/api",
            "token": app.state.service_token,
            "service": app.state.runner_service,
            "shutdown": shutdown,
        },
        daemon=True,
        name="drug-agent-companion-worker",
    )
    worker.start()
    print(f"Drug Discovery Agent Companion: {endpoint}", flush=True)
    print("Pairing credentials are generated automatically and are never typed by the user.", flush=True)
    # Uvicorn captures shutdown signals and re-raises them after draining HTTP
    # requests. A default SIGBREAK then aborts Python on Windows, bypassing our
    # worker cleanup and potentially opening Windows Error Reporting. Consume
    # only that post-drain signal; Uvicorn still owns the live server handler.
    handled = [signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        handled.append(signal.SIGBREAK)
    previous = {sig: signal.signal(sig, lambda *_: None) for sig in handled}
    try:
        uvicorn.run(app, host="127.0.0.1", port=port)
    finally:
        shutdown.set()
        worker.join(timeout=3)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
