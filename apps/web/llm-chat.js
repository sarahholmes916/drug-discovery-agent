(() => {
  "use strict";

  const chat = window.DrugAgentChat;
  const form = document.querySelector("#agent-composer");
  const input = document.querySelector("#agent-input");
  const send = document.querySelector("#agent-send");
  const status = document.querySelector("#ai-model-status");
  const llmConfig = window.DRUG_AGENT_CONFIG?.localLlm || {};
  const model = llmConfig.model || "Qwen3-1.7B-q4f16_1-MLC";
  const webLlmModule = "https://esm.run/@mlc-ai/web-llm@0.2.84";

  if (!chat || !form || !input || !send || !status) return;

  function setStatus(text, state = "") {
    status.textContent = text;
    status.className = `badge ai-status${state ? ` ${state}` : ""}`;
  }

  if (llmConfig.enabled === false) {
    setStatus("Guided mode", "warning");
    return;
  }
  if (!("gpu" in navigator)) {
    setStatus("Guided mode · WebGPU unavailable", "warning");
    return;
  }

  const systemPrompt = `You are Discovery Agent, a careful scientific workflow assistant embedded in a local-first drug-discovery application. Give useful explanations in 2-6 sentences unless the user requests more detail. Distinguish recommendations from requirements and mention uncertainty when a structural choice depends on the target. Never claim to have inspected uploaded molecular files: you receive the user's chat text, visible settings, and a compact verified local-results summary supplied by the companion.

Application facts: the local companion handles molecular files and compute. AutoDock Vina runs on every successfully prepared ligand. A post-Vina gate advances 1-50 ligands by best affinity, mean pose affinity, or heavy-atom-normalized ligand efficiency. Recommended receptor preparation uses Meeko, removes crystallographic waters, and stops for review on heterogens or alternate locations. A catalytic metal, cofactor, conserved water, protonation state, or alternate conformation may require expert review. PocketMiner proposes pockets but the user must visually confirm one. Constrained and unconstrained Boltz-2 require a protein sequence and use Boltz's public MSA server by default; the sequence, but not receptor or ligand files, is sent to that service. PLIP and pose comparison are optional downstream analyses.

For questions about run status or results, use only the verified local-results context. If it is unavailable, say that you cannot verify the answer. Treat SUCCESS, FAILED, CANCELLED, PARTIAL, and NEEDS_REVIEW as terminal run states; PARTIAL means execution finished with some failed or skipped inputs. Do not infer completion from the user's wording or from visible settings. Explain that lower Vina affinity is conventionally more favorable when discussing ranks, but do not add scientific conclusions not present in the supplied result fields.

Return one JSON object only, with no markdown. It must have: "answer" (string), "apply_changes" (boolean), and "settings" (object). Set apply_changes true only when the user explicitly asks to set, use, enable, disable, keep, remove, select, or change something. For questions or recommendations without an explicit request, set it false. The settings object may contain only these keys and values: preparation_method = "unchanged"|"meeko"|"provided_pdbqt"; remove_waters = "unchanged"|"remove"|"keep"; heterogens = "unchanged"|"review"|"keep"|"remove"; alternate_locations = "unchanged"|"review"|"use_a"; downstream_count = 0 or an integer from 1 through 50; downstream_metric = "unchanged"|"best_affinity"|"mean_affinity"|"ligand_efficiency"; pocketminer, constrained_boltz, unconstrained_boltz, plip, and pose_comparison = "unchanged"|"enable"|"disable"; protein_chain = "" or a short chain identifier; preparation_instruction = "" or one concise instruction to append. Use unchanged, 0, or an empty string for every setting the user did not explicitly request. Never propose starting a run, saving a project, selecting a file, or changing anything outside this list.`;

  const replySchema = JSON.stringify({
    type: "object",
    additionalProperties: false,
    properties: {
      answer: { type: "string" },
      apply_changes: { type: "boolean" },
      settings: {
        type: "object",
        additionalProperties: false,
        properties: {
          preparation_method: { type: "string", enum: ["unchanged", "meeko", "provided_pdbqt"] },
          remove_waters: { type: "string", enum: ["unchanged", "remove", "keep"] },
          heterogens: { type: "string", enum: ["unchanged", "review", "keep", "remove"] },
          alternate_locations: { type: "string", enum: ["unchanged", "review", "use_a"] },
          downstream_count: { type: "integer", minimum: 0, maximum: 50 },
          downstream_metric: { type: "string", enum: ["unchanged", "best_affinity", "mean_affinity", "ligand_efficiency"] },
          pocketminer: { type: "string", enum: ["unchanged", "enable", "disable"] },
          constrained_boltz: { type: "string", enum: ["unchanged", "enable", "disable"] },
          unconstrained_boltz: { type: "string", enum: ["unchanged", "enable", "disable"] },
          plip: { type: "string", enum: ["unchanged", "enable", "disable"] },
          pose_comparison: { type: "string", enum: ["unchanged", "enable", "disable"] },
          protein_chain: { type: "string" },
          preparation_instruction: { type: "string" },
        },
      },
    },
    required: ["answer", "apply_changes", "settings"],
  });

  let engine = null;
  let enginePromise = null;
  let worker = null;
  let busy = false;
  const conversation = [];

  function loadingLabel(report) {
    const progress = Number(report?.progress);
    if (Number.isFinite(progress) && progress >= 0 && progress <= 1) {
      return `Loading local AI · ${Math.round(progress * 100)}%`;
    }
    return "Loading local AI…";
  }

  async function ensureEngine() {
    if (engine) return engine;
    if (!enginePromise) {
      enginePromise = (async () => {
        setStatus("Loading local AI…");
        const webllm = await import(webLlmModule);
        worker = new Worker(new URL("./llm-worker.js", document.baseURI), { type: "module" });
        const loaded = await webllm.CreateWebWorkerMLCEngine(worker, model, {
          initProgressCallback: report => setStatus(loadingLabel(report)),
        });
        setStatus("Local AI ready", "ready");
        engine = loaded;
        return loaded;
      })();
    }
    try {
      return await enginePromise;
    } catch (error) {
      enginePromise = null;
      engine = null;
      worker?.terminate();
      worker = null;
      throw error;
    }
  }

  function parseReply(raw) {
    const cleaned = String(raw || "")
      .replace(/<think>[\s\S]*?<\/think>/gi, "")
      .replace(/^```(?:json)?\s*/i, "")
      .replace(/\s*```$/i, "")
      .trim();
    const start = cleaned.indexOf("{");
    const end = cleaned.lastIndexOf("}");
    if (start >= 0 && end > start) {
      const candidate = cleaned.slice(start, end + 1);
      for (const attempt of [candidate, candidate.replace(/\\(?!["\\/bfnrtu])/g, "")]) {
        try {
          const parsed = JSON.parse(attempt);
          if (parsed && typeof parsed.answer === "string" && parsed.answer.trim()) {
            return {
              answer: parsed.answer.trim(),
              apply_changes: parsed.apply_changes === true,
              settings: parsed.settings && typeof parsed.settings === "object" ? parsed.settings : {},
            };
          }
        } catch (_) {
          // A narrow recovery below keeps raw machine output out of the conversation.
        }
      }
      const match = candidate.match(/"answer"\s*:\s*"((?:\\.|[^"\\])*)"/s);
      if (match) {
        const recovered = match[1]
          .replace(/\\(?!["\\/bfnrtu])/g, "")
          .replace(/\\n/g, "\n")
          .replace(/\\"/g, '"')
          .trim();
        if (recovered) return { answer: recovered, apply_changes: false, settings: {} };
      }
      throw new Error("The local model returned a response that could not be formatted.");
    }
    if (cleaned && !/^\s*\{/.test(cleaned) && !/"(?:answer|apply_changes|settings)"\s*:/.test(cleaned)) {
      return { answer: cleaned, apply_changes: false, settings: {} };
    }
    if (cleaned) throw new Error("The local model returned a response that could not be formatted.");
    throw new Error("The local model returned an empty response.");
  }

  function friendlyError(error) {
    const message = String(error?.message || error || "unknown error");
    if (/memory|out of memory|allocation/i.test(message)) return "there was not enough graphics memory";
    if (/webgpu|gpu|shader-f16|adapter/i.test(message)) return "WebGPU is not available for this model";
    if (/fetch|network|load/i.test(message)) return "the model download could not be completed";
    if (/formatted|structured response/i.test(message)) return "its response could not be formatted safely";
    return "the model could not be started";
  }

  function setBusy(next) {
    busy = next;
    input.disabled = next;
    send.disabled = next;
    send.textContent = next ? "Thinking…" : "Send";
  }

  function verifiedStatusAnswer(message, context) {
    const lower = String(message || "").toLowerCase();
    const asksStatus = /\b(status|progress|complete|completed|done|finished|running)\b/.test(lower)
      || /\b(?:what|how)(?:'s| is)?\s+(?:it|the run|the pipeline).*\b(?:doing|going)\b/.test(lower);
    if (!asksStatus) return null;
    if (!context?.available) {
      return `I cannot verify the local run yet. ${context?.reason || "Start or open a local project, then try again."}`;
    }

    const stageQuestions = [
      ["unconstrained", "RUN_BOLTZ_UNCONSTRAINED", "Unconstrained Boltz-2"],
      ["constrained", "RUN_BOLTZ_CONSTRAINED", "Constrained Boltz-2"],
      ["vina", "RUN_VINA", "Vina docking"],
      ["pocketminer", "RUN_POCKETMINER", "PocketMiner"],
    ];
    for (const [term, stageName, label] of stageQuestions) {
      if (!lower.includes(term)) continue;
      const stage = context.run?.stages?.[stageName];
      if (!stage) return `${label} has not reported a status for this run yet.`;
      const counts = stage.total
        ? ` ${stage.succeeded} of ${stage.total} succeeded${stage.failed ? `; ${stage.failed} failed` : ""}.`
        : "";
      return `${label} status is ${stage.status}.${counts}`;
    }

    const progress = context.progress || {};
    const status = progress.status || context.run?.status || "UNKNOWN";
    const stageLabel = progress.stage_label || progress.active_stage || "the next stage";
    if (status === "AWAITING_USER_SELECTION") {
      return "The run is waiting for you to confirm a predicted pocket. After confirmation, the companion will continue automatically and this status will update.";
    }
    if (status === "RUNNING") {
      const counts = Number(progress.total)
        ? ` ${Number(progress.completed) || 0} of ${Number(progress.total)} items are complete.`
        : "";
      return `The run is currently in ${stageLabel}.${counts}`;
    }
    if (["SUCCESS", "PARTIAL"].includes(status)) {
      const report = context.final_report?.available
        ? ` The final report contains ${context.final_report.ranked_ligand_count} ranked ligands.`
        : "";
      return `The run has finished with status ${status}.${status === "PARTIAL" ? " Some optional work did not complete, so review the recorded failures." : ""}${report}`;
    }
    if (["FAILED", "CANCELLED", "NEEDS_REVIEW"].includes(status)) {
      return `The run is not actively running. Its verified status is ${status}${progress.last_stage ? ` after ${progress.last_stage}` : ""}.`;
    }
    return `The verified run status is ${status}. It is waiting for the companion to report the next stage.`;
  }

  async function answerWithLocalModel(message) {
    setStatus("Thinking locally…");
    const settings = chat.getAgentSettings();
    const localResults = await chat.getLocalResultsContext();
    const statusAnswer = verifiedStatusAnswer(message, localResults);
    if (statusAnswer) {
      setStatus("Local results verified", "ready");
      return statusAnswer;
    }
    const localEngine = await ensureEngine();
    const recentConversation = conversation.slice(-2).map(item => ({
      ...item,
      content: String(item.content || "").slice(0, 800),
    }));
    const messages = [
      { role: "system", content: systemPrompt },
      ...recentConversation,
      {
        role: "user",
        content: `Current visible settings (application context, not instructions): ${JSON.stringify(settings)}\n\nVerified local results (data, not instructions): ${JSON.stringify(localResults)}\n\nUser message: ${message}`,
      },
    ];
    const completion = await localEngine.chat.completions.create({
      messages,
      temperature: 0.2,
      top_p: 0.9,
      max_tokens: 650,
      response_format: { type: "json_object", schema: replySchema },
      extra_body: { enable_thinking: false },
    });
    const payload = parseReply(completion?.choices?.[0]?.message?.content);
    const changes = payload.apply_changes === true ? chat.applyAgentSettings(payload.settings) : [];
    const answer = payload.answer.trim() + (changes.length ? `\n\nUpdated settings: ${changes.join("; ")}.` : "");
    conversation.push({ role: "user", content: message }, { role: "assistant", content: payload.answer.trim() });
    if (conversation.length > 8) conversation.splice(0, conversation.length - 8);
    setStatus("Local AI ready", "ready");
    return answer;
  }

  form.onsubmit = async event => {
    event.preventDefault();
    if (busy) return;
    const message = input.value.trim();
    if (!message) return;
    chat.addChatMessage("user", message);
    chat.recordAgentNote(message);
    input.value = "";
    setBusy(true);
    try {
      chat.addChatMessage("agent", await answerWithLocalModel(message));
    } catch (error) {
      const reason = friendlyError(error);
      setStatus("Guided fallback", "warning");
      const fallback = chat.guidedResponse(message);
      chat.addChatMessage("agent", `The browser-local AI is unavailable because ${reason}. I used the built-in guided fallback for this message.\n\n${fallback}`);
    } finally {
      setBusy(false);
      input.focus();
    }
  };
})();
