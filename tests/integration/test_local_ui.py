from __future__ import annotations

from fastapi.testclient import TestClient

from apps.local_ui import create_local_ui_app


def test_combined_local_ui_serves_page_and_prefixed_api(tmp_path) -> None:
    token = "c" * 64
    client = TestClient(create_local_ui_app(database=tmp_path / "control.sqlite3", token=token))
    page = client.get("/")
    assert page.status_code == 200
    assert "Drug Discovery Agent" in page.text
    assert "Pairing token" not in page.text
    assert "Control-plane token" not in page.text
    assert "Connect companion" in page.text
    assert "discovery.automatic_pairing" in page.text
    assert "running||latest" in page.text
    assert "Local scientific tools" in page.text
    assert 'id="local-tools-panel"' in page.text
    assert 'id="refresh-tools"' in page.text
    assert "Official setup guide" in page.text
    assert "Install automatically" in page.text
    assert "/tools/installers" in page.text
    assert "/tools/installations/" in page.text
    assert "public MSA service" in page.text
    assert "Discovery Agent" in page.text
    assert "Open-source AI runs privately in this browser" in page.text
    assert "No API key is needed" in page.text
    assert "Agent preparation" in page.text
    assert "AutoDock Vina" in page.text
    assert "Ligands advancing after Vina" in page.text
    assert "Best Vina affinity (recommended)" in page.text
    assert 'id="downstream-count"' in page.text
    assert 'max="50"' in page.text
    assert "all Vina scores remain in the report" in page.text
    assert 'id="vina"' not in page.text
    assert "Receptor structure" in page.text
    assert "Extracted automatically from the selected receptor chain" in page.text
    assert 'id="protein-sequence-status"' in page.text
    assert "/receptor/sequence" in page.text
    assert "Ligand SDF files" in page.text
    assert "Ligand folder" in page.text
    assert 'id="ligand-folder"' in page.text
    assert "webkitdirectory" in page.text
    assert "Recent local projects" in page.text
    assert "Save project to this computer" in page.text
    assert 'id="refresh-projects"' in page.text
    assert "Download results" in page.text
    assert "requireLocalProject" in page.text
    assert "is not saved on this computer" in page.text
    assert "Install the missing local tool" in page.text
    assert "'Meeko CLI'" in page.text
    assert "This project is saved, but no local run has started yet" in page.text
    assert "/progress" in page.text
    assert "monitorLocalRun" in page.text
    assert "payload.last_stage" in page.text
    assert 'id="progress-detail"' in page.text
    assert 'class="results-console"' in page.text
    assert 'role="log"' in page.text
    assert "wasNearBottom" in page.text
    assert "localResultEntries.length>500" in page.text
    assert "resultsView.scrollTop=resultsView.scrollHeight" in page.text
    assert "getLocalResultsContext" in page.text
    assert "report:json" in page.text
    assert "chatMilestones" in page.text
    assert "RUN_BOLTZ_CONSTRAINED:'Constrained Boltz-2'" in page.text
    assert "pocketLoadRequests" in page.text
    assert "pollInFlight" in page.text
    assert "completedRunStatuses" in page.text
    assert "Vina docking" in page.text
    assert "Low 0 (blue)" in page.text
    assert "High 1 (red)" in page.text
    assert "wireframe:true" in page.text
    assert "focusCurrentBox" in page.text
    assert "sphere:{radius:.35}" not in page.text
    web_config = client.get("/config.js")
    assert web_config.status_code == 200
    assert "github.com/ccsb-scripps/AutoDock-Vina/releases/latest" in web_config.text
    assert "github.com/jwohlwend/boltz#installation" in web_config.text
    llm_chat = client.get("/llm-chat.js")
    assert llm_chat.status_code == 200
    assert "Qwen3-1.7B-q4f16_1-MLC" in llm_chat.text
    assert "applyAgentSettings" in llm_chat.text
    assert "@mlc-ai/web-llm@0.2.84" in llm_chat.text
    assert "response_format" in llm_chat.text
    assert "replySchema" in llm_chat.text
    assert "Verified local results" in llm_chat.text
    assert "chat.getLocalResultsContext()" in llm_chat.text
    assert "verifiedStatusAnswer" in llm_chat.text
    assert "Local results verified" in llm_chat.text
    assert "could not be formatted safely" in llm_chat.text
    assert client.get("/llm-worker.js").status_code == 200
    # Release archives are external; CI must not require an ignored local ZIP.
    assert client.get("/companion-downloads.js").status_code == 200
    assert 'id="companion-platform"' in page.text
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "data_plane": False}
