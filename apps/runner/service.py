from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from drug_discovery_agent.config.models import ProjectConfig, load_project_config
from drug_discovery_agent.execution.commands import CancellationToken
from drug_discovery_agent.pipeline.orchestrator import PipelineContext, PipelineOrchestrator, StageOutcome
from drug_discovery_agent.privacy import progress_payload
from drug_discovery_agent.project.io import read_json
from drug_discovery_agent.project.layout import ProjectLayout
from drug_discovery_agent.project.provenance import collect_provenance, write_provenance
from drug_discovery_agent.project.state import RunState, StageName, StageStatus, StateStore

from .registry import RunnerRegistry
from .tool_paths import managed_tool_metadata


def load_local_references(layout: ProjectLayout) -> dict[str, Path]:
    payload = read_json(layout.local_references)
    if not isinstance(payload, dict) or not isinstance(payload.get("references"), dict):
        raise ValueError(f"local reference map is missing or invalid: {layout.local_references}")
    return {key: Path(value).expanduser().resolve() for key, value in payload["references"].items()}


class LocalRunnerService:
    def __init__(self, registry: RunnerRegistry | None = None) -> None:
        self.registry = registry or RunnerRegistry()
        self._tokens: dict[str, CancellationToken] = {}

    def start(self, config_path: str | Path, *, progress=None) -> RunState:
        config_path = Path(config_path).expanduser().resolve()
        config = load_project_config(config_path)
        layout = ProjectLayout(config_path.parent)
        if layout.config != config_path:
            raise ValueError("project config must be named project.yaml at the project root")
        run_id = f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        state = RunState(run_id=run_id, project_id=config.project.id)
        store = StateStore(layout.run_state, layout.root)
        store.save(state)
        self.registry.register_run(run_id, config.project.id, layout.root)
        return self._execute(config, layout, state, store, progress=progress)

    def resume(self, run_id: str, *, progress=None) -> RunState:
        layout = ProjectLayout(self.registry.run_root(run_id))
        config = load_project_config(layout.config)
        store = StateStore(layout.run_state, layout.root)
        state = store.load()
        if state.run_id != run_id:
            raise ValueError(f"project current run is {state.run_id}, not {run_id}")
        state.cancellation_requested = False
        store.save(state)
        return self._execute(config, layout, state, store, progress=progress)

    def start_assigned(self, project_id: str, run_id: str, *, progress=None) -> RunState:
        """Start or resume a cloud-assigned run against an existing local project mapping."""
        layout = ProjectLayout(self.registry.project_root(project_id))
        config = load_project_config(layout.config)
        if config.project.id != project_id:
            raise ValueError("cloud project ID does not match the registered local project")
        store = StateStore(layout.run_state, layout.root)
        if layout.run_state.exists():
            current = store.load()
            if current.run_id == run_id:
                current.cancellation_requested = False
                store.save(current)
                state = current
            else:
                state = RunState(run_id=run_id, project_id=project_id)
                store.save(state)
        else:
            state = RunState(run_id=run_id, project_id=project_id)
            store.save(state)
        self.registry.register_run(run_id, project_id, layout.root)
        return self._execute(config, layout, state, store, progress=progress)

    def _execute(self, config: ProjectConfig, layout: ProjectLayout, state: RunState,
                 store: StateStore, *, progress=None) -> RunState:
        # Keep optional scientific imports out of doctor/status/control-plane
        # commands. Missing science dependencies should disable execution only.
        from .local_pipeline import make_handlers

        token = CancellationToken()
        self._tokens[state.run_id] = token
        context = PipelineContext(config=config, layout=layout, run_state=state, state_store=store,
                                  cancellation=token, local_references=load_local_references(layout))
        context.data["tool_versions"] = {
            tool_id: metadata
            for tool_id in ("boltz", "plip")
            if (metadata := managed_tool_metadata(tool_id)) is not None
        }
        files = [path for path in context.local_references.values() if path.is_file()]
        write_provenance(
            layout.provenance,
            collect_provenance(
                repository=Path(__file__).resolve().parents[2],
                config=config.scientific_projection(),
                input_paths=files,
            ),
        )

        def publish(stage: StageName, outcome: StageOutcome) -> None:
            awaiting = outcome.status == StageStatus.AWAITING_USER_SELECTION
            payload = progress_payload(
                run_id=state.run_id,
                stage="pocket_selection" if awaiting else stage.value,
                status="awaiting_user_selection" if awaiting else outcome.status.value,
                completed=outcome.completed,
                total=outcome.total,
                failed=outcome.failed,
                candidate_count=outcome.candidate_count if awaiting else None,
            )
            if progress:
                progress(payload)

        try:
            return PipelineOrchestrator(make_handlers(layout.state / "commands")).run(context, publish)
        finally:
            self._tokens.pop(state.run_id, None)

    def status(self, run_id: str) -> RunState:
        layout = ProjectLayout(self.registry.run_root(run_id))
        return StateStore(layout.run_state, layout.root).load()

    def cancel(self, run_id: str) -> RunState:
        layout = ProjectLayout(self.registry.run_root(run_id))
        store = StateStore(layout.run_state, layout.root)
        state = store.load()
        store.request_cancellation(state)
        token = self._tokens.get(run_id)
        if token:
            token.cancel()
        return state
