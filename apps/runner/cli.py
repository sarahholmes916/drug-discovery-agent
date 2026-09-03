from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

from drug_discovery_agent.config.models import PocketMinerRuntimeConfig, load_project_config
from drug_discovery_agent.pocketminer.runtime import inspect_installation, setup as setup_pocketminer
from drug_discovery_agent.project.layout import create_project

from .doctor import collect_capabilities
from .doctor import cloud_capabilities
from .cloud import PollingControlPlaneClient
from .registry import RunnerRegistry, runner_home
from .service import LocalRunnerService


def _refs(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"local reference must use ID=PATH: {value}")
        key, path = value.split("=", 1)
        if not key or key in result:
            raise ValueError(f"invalid or duplicate local reference ID: {key}")
        result[key] = Path(path)
    return result


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="drug-agent")
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="detect local scientific capabilities")
    doctor.add_argument("--config", help="optional project.yaml supplying PocketMiner runtime settings")
    pocket_setup = commands.add_parser("pocketminer-setup", help="install and verify pinned official PocketMiner locally")
    pocket_setup.add_argument("--config", help="optional project.yaml supplying PocketMiner runtime settings")
    pocket_inspect = commands.add_parser("pocketminer-inspect", help="show exact local PocketMiner identity")
    pocket_inspect.add_argument("--config", help="optional project.yaml supplying PocketMiner runtime settings")
    bridge = commands.add_parser("bridge", help="serve the authenticated scientific data plane on loopback")
    bridge.add_argument("--origin", action="append", required=True, help="allowed hosted UI origin")
    bridge.add_argument("--token", default=os.environ.get("DRUG_AGENT_BRIDGE_TOKEN"))
    bridge.add_argument("--port", type=int, default=8765)
    companion = commands.add_parser(
        "companion",
        help="run the downloadable companion with browser-approved automatic pairing",
    )
    companion.add_argument(
        "--origin",
        action="append",
        default=None,
        help="optional exact website origin; repeat for multiple trusted sites",
    )
    companion.add_argument("--port", type=int, default=8765)
    companion.add_argument("--database", default=str(runner_home() / "control_plane.sqlite3"))
    ui = commands.add_parser("ui", help="serve the complete UI, API, bridge, and local worker")
    ui.add_argument("--token", default=os.environ.get("DRUG_AGENT_LOCAL_TOKEN"))
    ui.add_argument("--port", type=int, default=8000)
    ui.add_argument("--database", default=str(runner_home() / "control_plane.sqlite3"))
    init = commands.add_parser("init", help="create a local project from a project YAML")
    init.add_argument("config")
    init.add_argument("--projects-root", default=str(runner_home() / "projects"))
    init.add_argument("--ref", action="append", default=[], metavar="ID=PATH")
    run = commands.add_parser("run", help="run a local project")
    run.add_argument("config")
    resume = commands.add_parser("resume", help="resume a local run")
    resume.add_argument("run_id")
    status = commands.add_parser("status", help="show local run status")
    status.add_argument("run_id")
    cancel = commands.add_parser("cancel", help="request cancellation")
    cancel.add_argument("run_id")
    connect = commands.add_parser("connect", help="poll and execute outbound control-plane jobs")
    connect.add_argument("--endpoint", required=True)
    connect.add_argument("--machine-id", required=True)
    connect.add_argument("--token", required=True)
    connect.add_argument("--poll-interval", type=float, default=5.0)
    connect.add_argument("--once", action="store_true")
    return root


def _progress(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def main(argv: list[str] | None = None) -> int:
    from .tool_paths import activate_managed_tools

    activate_managed_tools()
    args = parser().parse_args(argv)
    try:
        if args.command in {"pocketminer-setup", "pocketminer-inspect"}:
            runtime = (
                load_project_config(args.config).pocketminer.runtime
                if args.config else PocketMinerRuntimeConfig()
            )
            report = setup_pocketminer(runtime) if args.command == "pocketminer-setup" else inspect_installation(runtime)
            print(json.dumps(report, indent=2))
            return 0 if report["available"] else 1
        if args.command == "ui":
            from apps.local_ui import run_local_ui
            run_local_ui(
                token=args.token,
                port=args.port,
                database=args.database,
            )
            return 0
        if args.command == "companion":
            from .companion import run_companion
            run_companion(
                port=args.port,
                database=args.database,
                allowed_origins=args.origin,
            )
            return 0
        if args.command == "bridge":
            if not args.token or len(args.token) < 32:
                raise ValueError("set --token or DRUG_AGENT_BRIDGE_TOKEN to at least 32 characters")
            from .bridge import create_bridge
            try:
                import uvicorn
            except ImportError as exc:
                raise RuntimeError("install the runner extra to serve the localhost bridge") from exc
            registry = RunnerRegistry()
            projects = registry.load().get("projects", {})
            service = LocalRunnerService(registry)
            app = create_bridge(
                token=args.token,
                allowed_origins=args.origin,
                projects=projects,
                cancel_run=service.cancel,
                resume_run=service.resume,
            )
            uvicorn.run(app, host="127.0.0.1", port=args.port)
            return 0
        if args.command == "doctor":
            runtime = load_project_config(args.config).pocketminer.runtime if args.config else None
            capabilities = collect_capabilities(runtime)
            for item in capabilities:
                mark = "[+]" if item.available else "[x]"
                details = " - ".join(value for value in (item.version, item.detail) if value)
                print(f"{mark} {item.name}{': ' + details if details else ''}")
            tools = {item.name: item.available for item in capabilities}
            print("\nVina workflows are available." if tools.get("NumPy") and tools.get("RDKit") and tools.get("AutoDock Vina") and tools.get("Meeko CLI")
                  else "\nVina workflows are unavailable or incomplete.")
            print("Boltz GPU execution is available." if tools.get("Boltz-2") and tools.get("GPU")
                  else "Boltz GPU execution is unavailable or incomplete.")
            return 0
        if args.command == "init":
            config = load_project_config(args.config)
            layout = create_project(args.projects_root, config, _refs(args.ref))
            RunnerRegistry().register_project(config.project.id, layout.root)
            print(layout.root)
            return 0
        service = LocalRunnerService()
        if args.command == "run":
            state = service.start(args.config, progress=_progress)
        elif args.command == "resume":
            state = service.resume(args.run_id, progress=_progress)
        elif args.command == "status":
            state = service.status(args.run_id)
        elif args.command == "cancel":
            state = service.cancel(args.run_id)
        elif args.command == "connect":
            if args.poll_interval < 1:
                raise ValueError("poll interval must be at least one second")
            client = PollingControlPlaneClient(args.endpoint, args.token)
            capabilities = cloud_capabilities(collect_capabilities())
            while True:
                client.heartbeat({"machine_id": args.machine_id, "status": "CONNECTED",
                                  "capabilities": capabilities})
                job = client.claim_job(args.machine_id)
                if job:
                    sanitized = job.get("sanitized_config", {})
                    project_id = sanitized.get("project_id") if isinstance(sanitized, dict) else None
                    if not isinstance(project_id, str):
                        raise ValueError("claimed job has no opaque project_id")
                    job_id, run_id = str(job["job_id"]), str(job["run_id"])
                    finished = threading.Event()

                    def watch_cancellation() -> None:
                        while not finished.wait(args.poll_interval):
                            if client.job_state(job_id) == "CANCEL_REQUESTED":
                                service.cancel(run_id)
                                return

                    watcher = threading.Thread(target=watch_cancellation, daemon=True)
                    watcher.start()
                    try:
                        service.start_assigned(
                            project_id,
                            run_id,
                            progress=lambda payload: client.report_event(job_id, payload),
                        )
                    finally:
                        finished.set()
                        watcher.join(timeout=args.poll_interval + 1)
                if args.once:
                    break
                time.sleep(args.poll_interval)
            return 0
        else:
            return 2
        print(json.dumps(state.model_dump(mode="json"), indent=2))
        return 0 if state.status in {
            "SUCCESS", "PARTIAL", "NEEDS_REVIEW", "CANCELLED", "AWAITING_USER_SELECTION",
        } else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
