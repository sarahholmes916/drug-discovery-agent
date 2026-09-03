from __future__ import annotations

import hmac
import threading
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable, Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from drug_discovery_agent.config.models import load_project_config
from drug_discovery_agent.pocketminer.models import CandidatePocket, PocketSelectionRequest
from drug_discovery_agent.pocketminer.parser import parse_normalized_scores
from drug_discovery_agent.pocketminer.selection import load_valid_selection, make_selection, write_selection
from drug_discovery_agent.project.io import read_json
from drug_discovery_agent.project.layout import ProjectLayout
from drug_discovery_agent.project.manifest import ProjectManifest

from .doctor import capability_dicts, collect_capabilities


def create_bridge(
    *,
    token: str | None = None,
    allowed_origins: list[str] | None = None,
    projects: Mapping[str, str | Path],
    cancel_run: Callable[[str], object] | None = None,
    resume_run: Callable[[str], object] | None = None,
    token_authorizer: Callable[[str, str], bool] | None = None,
    origin_validator: Callable[[str], bool] | None = None,
    project_resolver: Callable[[str], str | Path] | None = None,
    project_lister: Callable[[], Mapping[str, str | Path]] | None = None,
):
    origins = allowed_origins or []
    if token_authorizer is None:
        if token is None or len(token) < 32:
            raise ValueError("localhost bridge token must contain at least 32 characters")
        if not origins or any(origin == "*" for origin in origins):
            raise ValueError("localhost bridge requires an explicit origin allowlist")
    elif token is not None:
        raise ValueError("configure either a fixed token or a dynamic token authorizer")
    if origin_validator is None:
        origin_validator = lambda value: value in origins
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, JSONResponse
        from starlette.background import BackgroundTask
    except ImportError as exc:
        raise RuntimeError("FastAPI is required for the localhost bridge") from exc
    # With postponed annotations and optional FastAPI imports, expose Request to
    # FastAPI's dependency resolver without making FastAPI a base dependency.
    globals()["Request"] = Request

    app = FastAPI(title="Drug Discovery Agent Local Bridge", docs_url=None, redoc_url=None)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        )
    roots = {project_id: Path(path).resolve() for project_id, path in projects.items()}

    @app.middleware("http")
    async def enforce_browser_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if not origin or not origin_validator(origin):
            return JSONResponse(status_code=403, content={"detail": "origin not allowed"})
        if request.method == "POST" and request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            return JSONResponse(status_code=415, content={"detail": "JSON requests required"})
        return await call_next(request)

    def authorize(request: Request, authorization: str = Header(default="")) -> None:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="invalid local bridge token")
        supplied = authorization.removeprefix("Bearer ")
        origin = request.headers.get("origin", "")
        if token_authorizer is not None:
            accepted = token_authorizer(origin, supplied)
        else:
            accepted = bool(token and hmac.compare_digest(supplied, token))
        if not accepted:
            raise HTTPException(status_code=401, detail="invalid local bridge token")

    def layout_for(project_id: str) -> ProjectLayout:
        root = roots.get(project_id)
        if root is None and project_resolver is not None:
            try:
                root = Path(project_resolver(project_id)).resolve()
            except KeyError:
                root = None
        if root is None:
            raise HTTPException(status_code=404, detail="unknown project")
        return ProjectLayout(root)

    def current_project_roots() -> dict[str, Path]:
        current = dict(roots)
        if project_lister is not None:
            current.update({
                project_id: Path(path).resolve()
                for project_id, path in project_lister().items()
            })
        return current

    def result_files(layout: ProjectLayout, *, include_metadata: bool = False) -> list[Path]:
        root = layout.root.resolve()
        selected: dict[str, Path] = {}

        def add(path: Path) -> None:
            resolved = path.resolve()
            if resolved.is_file() and resolved.is_relative_to(root):
                selected[resolved.relative_to(root).as_posix()] = resolved

        manifest = read_json(layout.manifest, {"schema_version": 1})
        if isinstance(manifest, dict):
            for item in manifest.get("artifacts", []):
                if isinstance(item, dict) and isinstance(item.get("relative_path"), str):
                    add(root / item["relative_path"])
        reports = root / "reports"
        if reports.is_dir():
            for path in reports.rglob("*"):
                add(path)
        if include_metadata:
            for path in (
                layout.config,
                layout.run_state,
                layout.manifest,
                layout.provenance,
                layout.state / "selected_pocket.json",
            ):
                add(path)
        return [selected[name] for name in sorted(selected)]

    def project_summary(project_id: str, root: Path) -> dict[str, object]:
        layout = ProjectLayout(root)
        config = load_project_config(layout.config)
        state = read_json(layout.run_state, {})
        if not isinstance(state, dict):
            state = {}
        artifacts = result_files(layout)
        updated_at = state.get("updated_at")
        if not isinstance(updated_at, str):
            updated_at = datetime.fromtimestamp(layout.config.stat().st_mtime, UTC).isoformat()
        return {
            "project_id": project_id,
            "display_name": config.project.display_name or project_id,
            "available": True,
            "workflow": config.workflow.value,
            "features": {
                "pocketminer": config.pocket.mode == "pocketminer",
                "boltz_constrained": config.boltz.constrained.enabled,
                "boltz_unconstrained": config.boltz.unconstrained.enabled,
            },
            "receptor_preparation": config.target.preparation.model_dump(mode="json"),
            "downstream_selection": {
                "count": config.analysis.vina_shortlist,
                "metric": config.analysis.vina_selection_metric,
            },
            "run_id": state.get("run_id"),
            "status": state.get("status", "NOT_STARTED"),
            "active_stage": state.get("active_stage"),
            "updated_at": updated_at,
            "artifact_count": len(artifacts),
            "results_available": bool(artifacts),
        }

    def pocket_context(project_id: str):
        layout = layout_for(project_id)
        config = load_project_config(layout.config)
        payload = read_json(layout.local_references, {})
        references = payload.get("references", {}) if isinstance(payload, dict) else {}
        receptor_value = references.get(config.target.receptor_ref)
        if not receptor_value:
            raise HTTPException(status_code=409, detail="project receptor reference is unavailable")
        receptor = Path(receptor_value).expanduser().resolve()
        ranked = read_json(layout.root / "pocketminer" / "candidates" / "ranked_pockets.json", {})
        candidates = [CandidatePocket.model_validate(item) for item in ranked.get("candidates", [])]
        return layout, config, receptor, ranked, candidates

    @app.get("/v1/health", dependencies=[Depends(authorize)])
    def health():
        return {"status": "ok", "service": "drug-agent-local"}

    @app.get("/v1/capabilities", dependencies=[Depends(authorize)])
    def capabilities():
        return {"capabilities": capability_dicts(collect_capabilities())}

    @app.get("/v1/projects", dependencies=[Depends(authorize)])
    def projects_list():
        projects = []
        for project_id, root in current_project_roots().items():
            try:
                projects.append(project_summary(project_id, root))
            except (OSError, ValueError):
                projects.append({
                    "project_id": project_id,
                    "display_name": project_id,
                    "available": False,
                    "status": "UNAVAILABLE",
                    "updated_at": None,
                    "artifact_count": 0,
                    "results_available": False,
                })
        projects.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return {"projects": projects}

    @app.get("/v1/projects/{project_id}/status", dependencies=[Depends(authorize)])
    def project_status(project_id: str):
        layout = layout_for(project_id)
        state = read_json(layout.run_state)
        if state is None:
            raise HTTPException(status_code=404, detail="project has no run")
        return state

    @app.get("/v1/projects/{project_id}/progress", dependencies=[Depends(authorize)])
    def project_progress(project_id: str):
        layout = layout_for(project_id)
        state = read_json(layout.run_state)
        if not isinstance(state, dict):
            raise HTTPException(status_code=404, detail="project has no run")
        stages = state.get("stages", {})
        if not isinstance(stages, dict):
            stages = {}
        active_stage = state.get("active_stage")
        status = str(state.get("status", "NOT_STARTED"))
        ordered = sorted(
            (item for item in stages.values() if isinstance(item, dict)),
            key=lambda item: str(item.get("ended_at") or item.get("started_at") or ""),
        )
        latest = ordered[-1] if ordered else {}
        last_stage = active_stage if isinstance(active_stage, str) else latest.get("name")
        stage = stages.get(active_stage, {}) if isinstance(active_stage, str) else latest
        if not active_stage and status == "RUNNING":
            if latest.get("status") in {"RUNNING", "FAILED", "PARTIAL", "NEEDS_REVIEW"}:
                if latest.get("status") in {"FAILED", "PARTIAL", "NEEDS_REVIEW"}:
                    status = str(latest["status"])
        items = stage.get("items", {}) if isinstance(stage, dict) else {}
        if not isinstance(items, dict):
            items = {}
        completed = sum(
            isinstance(item, dict) and item.get("status") in {"SUCCESS", "SKIPPED"}
            for item in items.values()
        )
        stage_started_at = stage.get("started_at") if isinstance(stage, dict) else None
        failed = sum(
            isinstance(item, dict) and item.get("status") == "FAILED"
            and (
                stage.get("status") != "RUNNING"
                or not isinstance(stage_started_at, str)
                or not isinstance(item.get("updated_at"), str)
                or item["updated_at"] >= stage_started_at
            )
            for item in items.values()
        )
        total = len(items)
        if active_stage == "PREPARE_LIGANDS":
            total = len(list((layout.root / "ligands" / "source").glob("*.sdf")))
            completed = len(list((layout.root / "ligands" / "prepared_pdbqt").glob("*.pdbqt")))
        elif active_stage == "RUN_VINA":
            total = len(list((layout.root / "ligands" / "prepared_pdbqt").glob("*.pdbqt")))
            completed = len(list((layout.root / "vina" / "docked").glob("*_out.pdbqt")))
        elif active_stage in {"RUN_BOLTZ_CONSTRAINED", "RUN_BOLTZ_UNCONSTRAINED"}:
            branch = (
                "boltz_constrained"
                if active_stage == "RUN_BOLTZ_CONSTRAINED"
                else "boltz_unconstrained"
            )
            inputs_root = layout.root / branch / "inputs"
            results_root = layout.root / branch / "results"
            total = max(total, len(list(inputs_root.glob("*.yaml"))))
            # Item state is committed after the bounded Boltz scheduler returns.
            # Affinity output is written once an individual prediction finishes,
            # so count unique task directories to expose live per-ligand progress.
            predicted = sum(
                any(task_dir.rglob("affinity_*.json"))
                for task_dir in results_root.iterdir()
                if task_dir.is_dir()
            ) if results_root.is_dir() else 0
            completed = max(completed, predicted)
        failures = state.get("failures", [])
        if total == 0 and isinstance(last_stage, str) and isinstance(failures, list):
            failed = sum(
                isinstance(item, dict) and item.get("stage") == last_stage
                for item in failures
            )
        message = stage.get("message") if isinstance(stage, dict) else None
        if not message and failed and status in {"FAILED", "PARTIAL", "NEEDS_REVIEW"}:
            message = (
                f"{failed} of {total} items failed in {last_stage}."
                if total else f"{failed} failure records were reported in {last_stage}."
            )
        return {
            "project_id": project_id,
            "run_id": state.get("run_id"),
            "status": status,
            "active_stage": active_stage,
            "last_stage": last_stage,
            "stage_status": stage.get("status") if isinstance(stage, dict) else None,
            "completed": completed,
            "total": total,
            "failed": failed,
            "message": message,
            "updated_at": state.get("updated_at"),
        }

    @app.get("/v1/projects/{project_id}/pocketminer/scores", dependencies=[Depends(authorize)])
    def pocketminer_scores(project_id: str):
        layout = layout_for(project_id)
        payload = read_json(layout.root / "pocketminer" / "scores" / "residue_scores.json")
        if payload is None:
            raise HTTPException(status_code=404, detail="PocketMiner scores are unavailable")
        return payload

    @app.get("/v1/projects/{project_id}/pockets", dependencies=[Depends(authorize)])
    def pockets(project_id: str):
        _, _, _, ranked, candidates = pocket_context(project_id)
        if not ranked:
            raise HTTPException(status_code=404, detail="ranked pocket candidates are unavailable")
        return {
            **ranked,
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "displayed_candidates": [
                item.model_dump(mode="json")
                for item in candidates[:int(ranked.get("max_displayed_candidates", len(candidates)))]
            ],
        }

    @app.get("/v1/projects/{project_id}/receptor/visualization", dependencies=[Depends(authorize)])
    def receptor_visualization(project_id: str):
        layout = layout_for(project_id)
        path = layout.root / "pocketminer" / "visualization" / "receptor_pocketminer_scores.pdb"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="PocketMiner visualization receptor is unavailable")
        return FileResponse(path, filename=path.name, media_type="chemical/x-pdb")

    @app.get("/v1/projects/{project_id}/pocket-selection", dependencies=[Depends(authorize)])
    def pocket_selection(project_id: str):
        layout, config, receptor, _, candidates = pocket_context(project_id)
        selection = load_valid_selection(
            layout.state / "selected_pocket.json",
            candidates=candidates,
            receptor=receptor,
            pocketminer_config=config.pocketminer.model_dump(mode="json"),
        )
        if selection is None:
            raise HTTPException(status_code=404, detail="no pocket has been selected")
        return selection.model_dump(mode="json")

    @app.post("/v1/projects/{project_id}/pocket-selection", dependencies=[Depends(authorize)])
    def select_pocket(project_id: str, request: PocketSelectionRequest):
        layout, config, receptor, _, candidates = pocket_context(project_id)
        try:
            score_path = layout.root / "pocketminer" / "scores" / "residue_scores.json"
            scores = parse_normalized_scores(score_path) if score_path.is_file() else []
            selection = make_selection(
                request,
                candidates=candidates,
                receptor=receptor,
                pocketminer_config=config.pocketminer.model_dump(mode="json"),
                scores=scores,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        write_selection(selection, layout.state / "selected_pocket.json")
        return {**selection.model_dump(mode="json"), "resume_required": True}

    @app.get("/v1/projects/{project_id}/artifacts/{artifact_id}", dependencies=[Depends(authorize)])
    def artifact(project_id: str, artifact_id: str):
        layout = layout_for(project_id)
        manifest = ProjectManifest.model_validate(read_json(layout.manifest, {"schema_version": 1}))
        matches = [item for item in manifest.artifacts if item.artifact_id == artifact_id]
        if len(matches) != 1:
            raise HTTPException(status_code=404, detail="unknown artifact")
        path = layout.resolve_artifact(matches[0].relative_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact is unavailable")
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    @app.get("/v1/projects/{project_id}/results", dependencies=[Depends(authorize)])
    def project_results(project_id: str):
        layout = layout_for(project_id)
        if not result_files(layout):
            raise HTTPException(status_code=404, detail="project has no downloadable results")
        temporary = NamedTemporaryFile(prefix=f"{project_id}-", suffix=".zip", delete=False)
        archive = Path(temporary.name)
        temporary.close()
        try:
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as bundle:
                for path in result_files(layout, include_metadata=True):
                    bundle.write(path, path.resolve().relative_to(layout.root.resolve()).as_posix())
        except Exception:
            archive.unlink(missing_ok=True)
            raise
        return FileResponse(
            archive,
            filename=f"{project_id}-results.zip",
            media_type="application/zip",
            background=BackgroundTask(archive.unlink, missing_ok=True),
        )

    @app.post("/v1/runs/{run_id}/cancel", dependencies=[Depends(authorize)])
    def cancel(run_id: str):
        if cancel_run is None:
            raise HTTPException(status_code=503, detail="cancellation service unavailable")
        cancel_run(run_id)
        return {"run_id": run_id, "cancellation_requested": True}

    @app.post("/v1/runs/{run_id}/resume", dependencies=[Depends(authorize)])
    def resume(run_id: str):
        if resume_run is None:
            raise HTTPException(status_code=503, detail="resume service unavailable")
        thread = threading.Thread(target=resume_run, args=(run_id,), daemon=True, name=f"resume-{run_id}")
        thread.start()
        return {"run_id": run_id, "resume_started": True}

    return app
