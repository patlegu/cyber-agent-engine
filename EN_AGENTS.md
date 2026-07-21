# AGENTS.md — Cyber Agent Engine Specialist

Welcome to `cyber-agent-engine`. This document is the reference manual for any AI agent (coordinator, code agent) that needs to operate, evolve, or debug this engine.

---

## Documentation Update Rule

**Any development agent must keep `AGENTS.md` and `README.md` up to date after each significant piece of work.**

| File | Audience | Content to keep updated |
| --- | --- | --- |
| `AGENTS.md` | AI Agents, Advanced Developers | Internal architecture, development rules, technical gotchas, architecture decisions, interface contracts (schemas, errors) |
| `README.md` | Humans, Newcomers | Installation, HTTP API, configuration, available scripts, externally visible architecture decisions |
| `JOURNAL.md` | Team, AI Agents | Quantitative training results, ML learnings, technical decisions with dates |

### Brainstorming / Discussion Mode

When a work session takes the form of an exchange of thoughts (design, architecture trade-offs, option exploration), **both sides of the discussion must be recorded** — not just the conclusion.

This applies to roadmap files (`roadmaps/*.md`):
- The agent's thoughts (options considered, trade-offs, recommendations) are logged in the relevant file **as they are produced**, without waiting for a final decision.
- The manager's positions (business constraints, confirmed choices, specified use cases) are logged in the same way.
- The goal: the roadmap file becomes the living memory of the reasoning, not just a result.

**Cleaning up roadmap files**

Roadmap files can accumulate redundant or outdated entries. A cleanup can be triggered:
- By the manager, at any time.
- By the agent, if it identifies contradictions or redundancies — **but only after explicit validation from the manager before any modification**.

The agent never cleans up a roadmap file on its own initiative without prior agreement.

### When to Update

- **New agent or new mixin** → update the agent catalog in `AGENTS.md` + the `Architecture` table in `README.md`
- **New exposed function** → check that the documentation checklist is respected (see "Function Documentation" section below)
- **New script** → add a line in the `Scripts factory/scripts/` section of `README.md`
- **New environment variable** → add it to the Configuration sections of `README.md` and Environment Variables of `AGENTS.md`
- **New API route** → document in `README.md` (API section) and `AGENTS.md` (Auth section if protected)
- **Architecture decision** → record in `AGENTS.md` (Architecture section) **and** `README.md` (Architecture Decisions section) if it concerns code organization
- **Gotcha or non-obvious bug resolved** → add to the "Development Gotchas" section of `AGENTS.md`
- **Training run completed** → record in `JOURNAL.md` (parameters, loss, duration, observations, next actions)

The two files must remain consistent with each other. In case of contradiction, `AGENTS.md` is the reference for technical details.

---

## Server Role

This server is a **tool agent**, not a conversational agent.
It is designed to be called by a coordinator/reasoning agent (LangGraph, CrewAI, AutoGen…).
It executes concrete actions on network equipment by interpreting natural language.

---

## Architecture & "Mental Model"

### 1. Core Agent (`agents/base.py`)

The most critical file. Defines `ToolAgent`, which provides:

- **Fuzzy Matching with cache**: Flexible matching of function names via `SequenceMatcher`.
  The result is cached per instance (`_function_resolution_cache`) to avoid recalculations.
  -0.8 penalty on cross-category matches (ADD ↔ DEL) — never confuses "block/unblock".
- **Mandatory Argument Guard**: validates that all positional arguments without a default are present in the LLM's JSON before the call.
- **Multi-LoRA Switching**: switches between adapters (`opnsense`, `wireguard`) via the `NativeVLLMClient` singleton.
- **Structured Error Codes**: each failure returns an `ErrorCode` (see `agents/errors.py`) allowing the coordinator to decide on retry/fallback/escalation.
- **`get_capabilities()`**: introspection of `_functions` via `inspect.signature()` + docstrings → list of OpenAI function-calling schemas. Automatically deduplicates aliases (same callable → one schema with an `aliases` field).

### 2. Intent Routing (`agents/classifier.py`)

`AgentClassifier` assigns a weighted score to each agent via keywords at 4 levels:

```text
strong (+1.0) / medium (+0.5) / weak (+0.2) / negative (−1.0)
```

Returns `(agent_name, confidence)`. The server builds a priority list: the agent with the best score is tested first, then the others as a fallback.

> Rule: if an agent identifies the function (even if execution fails), the fallback stops — we don't let another agent hallucinate.

### 3. Structured Error Codes (`agents/errors.py`)

`ToolResult.error_code` allows the coordinator to make decisions:

| `ErrorCode` | Cause | Coordinator Action |
| --- | --- | --- |
| `FUNCTION_UNKNOWN` | No function recognized | Rephrase or escalate |
| `MISSING_ARG` | Mandatory argument missing | Ask the user for the info |
| `EXECUTION_ERROR` | Unexpected exception | Log and escalate |
| `API_UNREACHABLE` | Timeout / connection refused | Retry with backoff |
| `PERMISSION_DENIED` | HTTP 401/403 from equipment | Escalate to human operator |
| `INFERENCE_FAILED` | vLLM/Ollama error | Switch to simulation |

### 4. CPU Deployment — ONNX export of the fine-tuned LoRA (reflection 2026-02-27)

The base model Phi-3.5-mini-instruct exists in an official ONNX version (`microsoft/Phi-3.5-mini-instruct-onnx`). ONNX is an **inference-only format** — LoRA training remains in HuggingFace/PyTorch on GPU. But once the adapter is trained, it can be merged and exported for CPU-only inference.

**GPU → CPU Pipeline:**

```
train_opnsense_lora.py        merge_and_export.py          inference
(GPU, HF LoRA)          →     (GPU, one-time)       →    (CPU, onnxruntime-genai)
                               PeftModel.merge_and_unload()
                               + optimum-cli export onnx
                               + int4 quantization
```

**What this changes for deployment:**

| | Current (HF + LoRA) | After ONNX export |
|---|---|---|
| GPU required for inference | yes (~6 GB VRAM) | no |
| Inference RAM | ~6 GB | ~2.5 GB |
| Runtime dependencies | torch, transformers, peft | `onnxruntime-genai` only |
| Deployment | dedicated GPU server | lightweight VM, NAS, any machine |
| Dynamic LoRA swapping | yes (multi-LoRA) | no (static merged model) |

**Microsoft Olive** is the Microsoft tool to automate this pipeline (finetune → merge → quantize → ONNX) in a single JSON config.

**Limitations:** dynamic LoRA swapping (switching between opnsense/wireguard on the fly) is not possible with a merged ONNX model — it would require one ONNX model per agent. Acceptable if agents are deployed separately.

**Status:** path to explore after validation of run v3 (score ≥ 93%). Low priority as long as the GPU server is available.

### 5. High-Performance Inference (`factory/clients/native_vllm_client.py`)

- **Singleton**: a single `NativeVLLMClient` to avoid VRAM fragmentation.
- **Quantization**: 8-bit (`bitsandbytes`).
- **Context**: `VLLM_MAX_MODEL_LEN` (default 2048, reduce to 1024 if VRAM < 8 GB).
- **GPU utilization**: 0.6 in server mode (conservative).
- **Shutdown**: **must** call `vllm_client.shutdown()` on stop to free the CUDA cache. Forgetting this causes memory leaks on restart.
- **Thread safety**: `generate()` is blocking. It is wrapped in `loop.run_in_executor(None, ...)` — never call it directly in an `async` coroutine.

#### Structured Output (`TOOL_CALL_SCHEMA` + `StructuredOutputsParams`)

`TOOL_CALL_SCHEMA` is a strict JSON schema that forces the SLM to produce a valid array of calls:

```python
TOOL_CALL_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "arguments": {"type": "object"}
        },
        "required": ["name", "arguments"]
    },
    "minItems": 1, "maxItems": 1
}
```

`complete()` accepts an optional `json_schema`. If vLLM ≥ 0.15.0 and `StructuredOutputsParams` is available, it is injected into `SamplingParams` → the Outlines/xgrammar engine constrains the generated tokens. In case of failure (e.g., bitsandbytes + `enforce_eager` incompatible), the silent fallback reverts to free generation + regex parser.

`agents/base.py` passes `json_schema=TOOL_CALL_SCHEMA` to each `_infer_with_vllm()` call. **Do not remove this parameter** — the regex parser remains as a last resort but is less robust.

The log `"Structured output failed"` indicates that the fallback is active.

### 5. OPNsense Package (`agents/opnsense/`)

The OPNsense agent is split into mixins by functional domain:

```text
_base.py        OPNsenseAgent — inherits from all mixins + ToolAgent
_filters.py     FilterRulesMixin    — 6 methods (CRUD firewall rules)
_aliases.py     AliasesMixin        — 10 methods (IP/network/port aliases)
_nat.py         NATMixin            — 5 methods (port-forward, outbound NAT)
_diagnostics.py DiagnosticsMixin    — 7 methods (ping, traceroute, logs)
_config.py      ConfigMixin         — 9 methods (backup/restore, reconfigure)
_extended.py    ExtendedMixin       — 14 methods (GeoIP, firmware, DNS, DHCP)
_legacy.py      LegacyMixin         — block_ip / unblock_ip (backward compatibility)
_decorators.py  @safety_snapshot
```

Backward-compatible import: `from agents.opnsense_agent import OPNsenseAgent` still works.

**MRO Order**: `OPNsenseAgent` must call `super().__init__()` **after** initializing `self.platform` and `self._api_client`, because `_register_functions()` refers to them during `ToolAgent` init.

**When to create mixins for a new agent?** Only if the agent exceeds **~15-20 of its own functions** spread across distinct functional domains. Below this threshold, a single file is preferable — mixins add complexity (MRO, multiple files) without a readable benefit. `CrowdSecAgent` (6 functions) and `PfSenseAgent` (3 own functions + OPNsense inheritance) intentionally remain as single files.

### 6. `@safety_snapshot` Decorator

Used on **all** destructive OPNsense methods:

1. Calls `/api/firewall/filter/savepoint` before the modification.
2. Lets the modification execute.
3. In case of failure, rollback is available via the OPNsense console.

---

## Auth (`server.py`)

`X-API-Key` header required on `POST /agent/execute` and `GET /capabilities`.

- Environment variable: `AGENT_API_KEY`
- Not configured → dev mode, warning at startup, free access
- Wrong key → HTTP 401 `{"error": "UNAUTHORIZED"}`

---

## `/capabilities` Route

**Dynamic discovery** endpoint for tools. Used by the coordinator at startup to build its registry of available functions.

```json
{
  "server_version": "2.2",
  "agents": [
    {
      "name": "opnsense",
      "inference": "vllm|ollama|simulation",
      "function_count": 42,
      "functions": [ { "name": "...", "description": "...", "parameters": {}, "required": [], "aliases": [] } ]
    }
  ]
}
```

---

## Critical Security Protocols

### Dangerous Matches

Never allow a fuzzy match between opposing intents.

- **ADD Category**: `create`, `enable`, `add`, `block`, `start`, `new`
- **DEL Category**: `remove`, `disable`, `delete`, `unblock`, `stop`, `kill`

Rule: if the LLM hallucinates `remove_ip` but only `add_ip` exists → **FAIL** is mandatory, do not execute the opposite.

### Argument Sanitization

- Clearly type all method parameters.
- Positional arguments without a default are **mandatory** — the guard validates before any call.
- `**kwargs` tolerates extra hallucinated arguments without crashing.

### Bilingual FR/EN Support

System prompts and training data are bilingual. The engine parses `Pensée:` as a reasoning marker (in addition to `<thought>` and `Reasoning:`). Maintain this support.

---

## Function Documentation — Contract with `get_capabilities()`

`get_capabilities()` in `agents/base.py` introspects registered functions and automatically builds the OpenAI function-calling schemas exposed to the coordinator LLM. **The documentation of each agent method IS its interface — any gap directly translates into LLM hallucinations.**

Two mechanisms are automatically extracted:

### 1. `Literal[...]` → `enum` field in the schema

Any parameter annotated with `Literal["a", "b", "c"]` generates `"enum": ["a", "b", "c"]` in the JSON schema. The LLM sees the valid values directly in its context.

```python
# ✅ CORRECT — the LLM knows the valid values
async def _create_filter_rule(
    self,
    interface: Literal["wan", "lan", "opt1", "opt2"],
    action: Literal["block", "pass"] = "block",
) -> Dict:
    ...

# ❌ INCORRECT — enum missing from schema, hallucinations likely
async def _create_filter_rule(
    self,
    interface: str,    # LLM might generate "WAN", "eth0", "internet"...
    action: str = "block",
) -> Dict:
    ...
```

**Rule: any parameter with discrete values MUST be annotated with `Literal[...]`.**

### 2. `:param name:` → `description` field in the schema

`_parse_param_docs()` extracts `:param name: text` sections from the docstring and injects them as `"description"` in the parameter's schema. These descriptions guide the LLM to produce the correct values.

```python
# ✅ CORRECT — description + examples + anti-values documented
async def _ban_ip(
    self,
    ip: str,
    duration: str = "4h",
) -> Dict:
    """Bans an IP address via CrowdSec LAPI.

    :param ip: IP address to ban (e.g., "203.0.113.45").
    :param duration: Duration in Go duration format (e.g., "4h", "24h", "168h").
        Common values: "1h" (1 hour), "4h" (4 hours), "168h" (1 week).
    """

# ❌ INCORRECT — description missing from schema, LLM is on its own
async def _ban_ip(self, ip: str, duration: str = "4h") -> Dict:
    """Bans an IP."""
```

**Rule: each parameter MUST have a `:param name:` section in the docstring.**

### Best practices for `:param` descriptions

- Always include at least one concrete example: `(e.g., "203.0.113.45")`
- Document anti-values if the LLM is likely to hallucinate them:
  `DO NOT use 'allow', 'deny' or 'drop' — only 'block' or 'pass'`
- Specify the expected format for non-obvious types:
  `Go duration format (e.g., "4h", "24h", "168h")` or `RFC3339 format (e.g., "2026-01-01T00:00:00Z")`
- Document the behavior if omitted: `Omitted = all decisions`

### Checklist before committing an agent method

- [ ] All parameters with discrete values annotated `Literal[...]`
- [ ] Each parameter has a `:param name:` section in the docstring
- [ ] Concrete examples included in descriptions
- [ ] Anti-values documented if risk of hallucination
- [ ] `GET /capabilities` returns the expected `enum` and `description` after restart

### Git commit convention

Commit messages **must not** contain any reference to the agent or AI tool that produced the change (no `Co-Authored-By`, no `Generated by`, no mention of Claude, GPT, Copilot, etc.). The commit must describe the change, not its author.

---

## Development Gotchas

### 1. "Double Model" vLLM Error

If `NativeVLLMClient` is instantiated twice without `shutdown()`, `Distributed state already initialized` error occurs. Always use the `NativeVLLMClient._instance` singleton.

### Clean shutdown of coordinator / tool-agent (SIGINT / CTRL+C)

**Problem**: vLLM v1 runs its `EngineCore` in a subprocess (`EngineCore_DP0`). If the main process receives a raw SIGINT, the subprocess gets it simultaneously (same process group) and would die before cleanup, emitting:

```
[W] destroy_process_group() was not called before program exit (ProcessGroupNCCL.cpp)
```

**Fix applied (`__main__` entrypoints)**:

- Replace `uvicorn.run()` with `uvicorn.Server` + `install_signal_handlers = lambda: None`
- Install a custom SIGINT/SIGTERM handler that sets `server.should_exit = True`
- `timeout_graceful_shutdown=30` → uvicorn waits 30s for the lifespan to finish
- The lifespan calls `vllm_client.shutdown()` → `del self.llm` → `LLM.__del__` → EngineCore receives an IPC shutdown message instead of SIGKILL

**If launched via uvicorn CLI (not `__main__`)**: add `--timeout-graceful-shutdown 30` to the command.

**Sequential startup mandatory**: two vLLM instances on the same GPU cannot initialize in parallel. vLLM takes a snapshot of free VRAM at startup and fails with `AssertionError: Initial free memory X GiB, current free memory Y GiB` if another process modifies VRAM during the torch.compile phase (~80s).

```bash
# Step 1 — wait for "✅ Agents initialized."
python server.py

# Step 2 — only AFTER the tool-agent is stable
uvicorn coordinator.server:app --host 0.0.0.0 --port 3001 --timeout-graceful-shutdown 30
```

**VRAM Budget (RTX 4070 Ti 12 GB)**:

| Process | Model | `gpu_memory_utilization` | Physical VRAM |
|---|---|---|---|
| tool-agent (`server.py`) | Qwen2.5-3B-Instruct 4-bit LoRA | `TOOL_AGENT_GPU_UTIL=0.45` | ~5.4 GB |
| coordinator | Qwen2.5-3B-Instruct 8-bit | `COORDINATOR_GPU_UTIL=0.89` | ~3.3 GB |

**Total physical ~8.7 GB out of 12 GB.** The `COORDINATOR_GPU_UTIL` parameter must seem high (0.89) for a specific reason:

> vLLM measures **total VRAM** (all processes) during KV-cache profiling, not just its own delta.
> `kv_cache = GPU_UTIL × total − peak_profiling`
> `peak_profiling = tool_agent(5.4) + model_weights(2.29) + overhead(1.13) = 8.82 GB`
> With `VLLM_MAX_MODEL_LEN=8192`: `COORDINATOR_GPU_UTIL=0.89` → KV=0.89×12−8.82=1.85 GB
> (0.90 fails at startup: 0.90×12=10.8 > 10.75 GiB free at startup)

**General rule**: empirically measure `free_VRAM` at tool-agent startup (`nvidia-smi`), then `GPU_UTIL ≤ free_VRAM / total_VRAM`.

Alternative options:
- `COORDINATOR_GPU_UTIL=0.89` + `COORDINATOR_MODEL=Qwen/Qwen2.5-3B-Instruct` + `VLLM_MAX_MODEL_LEN=8192` ← CURRENT
- `COORDINATOR_BACKEND=anthropic` (external API, 0 GPU for the coordinator)

### 2. OPNsense 404 on savepoint

Some OPNsense versions use different savepoint endpoints. `OPNsenseAPIClient` has `suppress_log_404` in `_request` to handle these fallbacks silently.

### 3. WSL / CUDA

Under WSL, `pin_memory=False` is often necessary for stability. Handled automatically — monitor for CUDA errors in `server.log`.

### 5. HuggingFace XetHub / CAS: `HF_HUB_DISABLE_XET=1` required

Some HuggingFace models (including `unsloth/Phi-3-mini-4k-instruct`) use the XetHub/CAS storage backend.
Download via `xet_get` fails with `ReqwestMiddleware Error: Request failed after 5 retries` on
restrictive networks or behind a proxy.

**Fix**: export `HF_HUB_DISABLE_XET=1` before any training or download script:

```bash
HF_HUB_DISABLE_XET=1 python scripts/train_opnsense_lora.py
```

Alternative: use `microsoft/Phi-3-mini-4k-instruct` (identical weights, standard LFS storage, no xet).

### 6. Housekeeping — External repos cloned for data extraction

When an external repo is cloned to extract schemas or data (e.g., `opnsense-mcp-server`, `opnsense-typescript-client`), the clone is **temporary**. Rule:

1. Clone into `/tmp/` only (never in `/srv/`)
2. Extract the useful product to `data/schemas/` or `data/sft/`
3. Delete the clone immediately after extraction (`rm -rf /tmp/<repo>`)

Only the final artifacts are kept and versioned:
```
data/schemas/opnsense_mcp_full.json   ← extracted schemas (versioned)
data/sft/opnsense_mcp_train.jsonl     ← generated SFT examples (versioned)
```
Never commit a cloned repo, `node_modules/`, or compiled TypeScript binaries.

### 7. MCP Dataset — `content` dict instead of string

Some traces generated by `generate_opnsense_mcp_sft.py` produce an assistant message with `content` as a dict (`{'type': 'error', 'message': '...'}`) instead of a string. HuggingFace `datasets` raises an `ArrowInvalid` on load (column type change).

**Fix**: `merge_opnsense_datasets.py` systematically normalizes any non-string `content` to a JSON string on load. Do not remove this normalization.

### 4. CrowdSec: explicit stop tokens

The CrowdSec LoRA loops without stop tokens. `_infer_with_ollama` passes an explicit list:
`["OBSERVATION:", "Checking", "</s>", "<|endoftext|>"]`
Do not delete these tokens when updating the LoRA.

### 8. Unsloth 2026.2.x — `KeyError: 'sanitize_logprob'`

Since unsloth 2026.2.1, `unsloth/models/rl.py:289` references `RL_REPLACEMENTS["sanitize_logprob"]`
which does not exist in `unsloth_zoo/rl_replacements.py` of the same version (package desynchronization).

**Fix**: update `unsloth-zoo` alone (not `unsloth`):

```bash
pip install --upgrade unsloth-zoo
# unsloth_zoo 2026.2.1 → 2026.3.2
```

After update, Unsloth becomes operational again with triton kernels. If update is not possible, `_check_unsloth()` in `lora_trainer.py` catches `Exception` (not just `ImportError`) and falls back to standard HF.

### 10. Unsloth + `HF_HUB_OFFLINE=1` — model_name not resolved

Unsloth `FastLanguageModel.from_pretrained("Qwen/Qwen2.5-3B-Instruct")` with `HF_HUB_OFFLINE=1` raises:

```
RuntimeError: Unsloth: No config file found - are you sure the `model_name` is correct?
```

The model is however in the HF cache. The cause: `unsloth_zoo/hf_utils.py::get_transformers_model_type()` does not resolve the snapshot path correctly in offline mode.

**Fix** in Qwen25 training scripts: resolve the local path **before** passing to the trainer, via `snapshot_download(local_files_only=True)`:

```python
def _local_model_path(model_id: str) -> str:
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(model_id, local_files_only=True)
    except Exception:
        return model_id  # network fallback

trainer = LoRATrainer(base_model=_local_model_path("Qwen/Qwen2.5-3B-Instruct"), ...)
```

Do not set `HF_HUB_OFFLINE=1` in Qwen25 scripts — only keep `TRANSFORMERS_OFFLINE=1` (which does not interfere with `huggingface_hub.snapshot_download`).

### 11. Training / inference format mismatch — cause of catastrophic results

**Symptom**: LoRA fine-tuned on a new base model (e.g., Qwen2.5-3B-Instruct instead of Phi-3.5-mini) — verification rate close to 0%, all functions predicted incorrectly.

**Cause**: `format_single_example_to_text()` in `lora_trainer.py` was hardcoded for the Phi-3 prompt format (`<|system|>`, `<|user|>`, `<|assistant|>`, `<|endoftext|>`). The verification script uses `tokenizer.apply_chat_template()` which produces the model's native format (for Qwen2.5: `<|im_start|>system`, `<|im_end|>`, etc.). The LoRA learns one format, and sees a different format at inference.

**Fix** (2026-03-15): `format_single_example_to_text()` now uses `self.tokenizer.apply_chat_template()` — the training format is automatically matched to the base model's chat template. `tool_calls` (custom format) are converted to a JSON string in the assistant's `content` before calling the template.

**Rule**: always check the consistency of training ↔ inference format when changing the base model. A quick first test: display a formatted example before `trainer.train()` and compare it to the prompt produced by `build_prompt()` in the verification script.

### 9. Arrow schema inference — JSONL with heterogeneous `tool_calls.arguments`

`load_dataset("json", data_files=...)` infers the Arrow schema from the first N examples.
OPNsense datasets contain `tool_calls.arguments` with different structures depending on the function
(`firewall_rule` ≠ `nat_rule` ≠ `alias`) → Arrow raises `TypeError: Couldn't cast array of type struct<...>`
when loading the next batch.

**Fix**: in `trainers/lora_trainer.py`, `_load_jsonl()` serializes `messages` into a JSON string before creating
the `HFDataset` → flat schema `{"_msgs": string}`, homogeneous, no struct inference:

```python
def _load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            ex = json.loads(line.strip())
            rows.append({"_msgs": json.dumps(ex["messages"])})
    return HFDataset.from_list(rows)
```

`process_sample()` deserializes with `json.loads(example["_msgs"])`.
Never revert to `load_dataset("json", ...)` for OPNsense datasets.

---

## Multi-LoRA Inference (Phase 4)

### `ToolAgent` Class Attributes

Each tool agent inherits from `ToolAgent` (`agents/base.py`) and declares three class attributes:

| Attribute | Role | Current Value |
|---|---|---|
| `agent_role` | Short description (fallback if `system_prompt` is empty) | `"OPNsense firewall agent"` etc. |
| `system_prompt` | Exact system prompt for inference — **must match the training dataset** | CAP v1 FR specific to each agent |
| `chat_format` | Prompt template: `"qwen"` or `"phi3"` | `"qwen"` since Qwen2.5 migration |

`_infer_with_vllm()` in `base.py` builds the formatted prompt using `self.system_prompt` + `self.chat_format`. Changing the base model → update both attributes.

### Adapter Discovery — `_discover_lora_adapters()` (`server.py`)

Scans `loras/`, filters by `base_model_name_or_path` in `adapter_config.json` and **normalizes the adapter name** to match the agent's `tool_name`:

```
opnsense_lora/         → agent_name "opnsense"
opnsense_qwen25_lora/  → agent_name "opnsense"  ← _qwen25 suffix removed
wireguard_qwen25_lora/ → agent_name "wireguard"
```

Normalized suffixes: `_qwen25`, `_qwen3`, `_phi3`, `_phi35`.

`.env` configuration:
```bash
TOOL_AGENT_BASE_MODEL=Qwen/Qwen2.5-3B-Instruct   # base model common to all adapters
TOOL_AGENT_GPU_UTIL=0.45                           # GPU utilization for vLLM tool-agent
```

When `server.py` starts, only adapters whose `base_model_name_or_path == TOOL_AGENT_BASE_MODEL` are loaded into the vLLM engine. Other agents run in Ollama / simulation fallback.

---

## Agent Catalog

| Agent | `tool_name` | Domain | # Functions |
| --- | --- | --- | --- |
| `opnsense` | `opnsense` | OPNsense Firewall / NAT / VPN | 102 |
| `wireguard` | `wireguard` | WireGuard Tunnels & Peers | 11 |
| `crowdsec` | `crowdsec` | IDPS — bans, decisions, alerts | 15 |
| `anony` | `anony` | Anonymization of logs & documents | 5 |

### `anony` Agent — Anonymization (`agents/anony/`)

Orchestrates `anonyfiles_core` (fork of `/srv/anonyfiles`) to anonymize logs and documents.
Uses **AnonyNER** (custom spaCy model) for cybersecurity entity detection.

**Exposed functions:**
- `anonymize_text(text)` — anonymizes text, returns `{anonymized_text, mapping}`
- `anonymize_batch(texts, reset_session)` — consistent batch (same entity → same token)
- `deanonymize_text(anonymized_text)` — reversibility via session mapping
- `get_session_mapping()` — current mapping `{original: token}`
- `reset_session()` — starts a new blank session

**NER Model — resolution priority:**
1. Installed package `fr_anonyner` → `pip install dist/fr_anonyner-*.tar.gz`
2. Local directory `models/anonyner_model/model-best` → after `python scripts/train_anonyner.py`
3. Fallback `fr_core_news_md` → cyber entities not detected (warning at startup)

**Regenerate and install the `fr_anonyner` package:**
```bash
# From /srv/cyber-agent-engine
python -m spacy package \
  models/anonyner_model/model-best dist/ \
  --name anonyner --version 2.0.0 --build sdist --force
pip install dist/fr_anonyner-2.0.0/dist/fr_anonyner-2.0.0.tar.gz
```

**Labels detected by AnonyNER v2 (F1=88.6%):**
`IP_ADDRESS`, `IP_SUBNET`, `HOSTNAME`, `DOMAIN`, `CVE`, `MAC_ADDRESS`,
`SERVICE_ACCOUNT`, `FIREWALL_RULE`, `INTERFACE`, `PORT_NUMBER`, `VPN_USER`, `PROTOCOL`

**Complementary regex rules:** `agents/anony/config/custom_rules_security.json`
(RFC1918 IPs, CVE, FQDN, MAC, hex tokens — detection before NER pass)

---

## Adding a Capability

1. **Low-level client**: `factory/clients/<tool>_client.py` — `await self._request(...)` method
2. **Agent method**: add in the appropriate mixin (or create a new one), decorate with `@safety_snapshot` if it's a write operation
3. **Documentation**: apply the checklist from the "Function Documentation" section:
   - Annotate `Literal[...]` on all parameters with discrete values
   - Add `:param name:` in the docstring for each parameter
4. **Registration**: add to `_register_functions()` of the relevant mixin
5. **Classifier**: check / enrich keywords in `agents/classifier.py`
6. **Server init**: if a new agent, instantiate it in the lifespan block of `server.py`
7. **Validation**:
   - Test with a command that *omits* an argument → must return `error_code: MISSING_ARG`
   - Test the inverse intent (e.g., "delete" vs "create") → must refuse, not execute the opposite
   - Check that `GET /capabilities` returns the new function with its `enum` and `description`

---

---

## Coordinator Agent (`coordinator/`)

Separate service (port **3001**) that receives high-level requests, breaks them down into sub-tasks, and delegates to the tool-agent-server (port 3000).

### Internal Architecture

```text
coordinator/
├── server.py               FastAPI port 3001 + checkpoint watchdog
├── pilot.py                PilotAgent — plan / execute / synthesize / judge
├── state.py                Task, PlanState (checkpoint_at), CheckpointStore
├── judge.py                CAPValidator — schema validation before execution
├── clients/
│   └── tool_agent_client.py   HTTP to port 3000 (retry + capabilities cache)
├── llm/
│   └── coordinator_llm.py     Wrapper for Qwen2.5-3B vLLM or Ollama
└── prompts/
    ├── system.yaml         Network context (opnsense/wireguard/crowdsec)
    ├── planning.yaml       Decomposition into JSON tasks
    ├── routing.yaml        Selection of the next agent
    └── synthesis.yaml      Final Markdown report
```

#### `coordinator/judge.py` — CAPValidator

Deterministic validation of CAPs (Coordinator-Agent Packets) **before** sending to the tool-agent. No LLM — pure schema logic.

```python
@dataclass
class JudgeVerdict:
    passed: bool
    reason: str
    missing_args: list[str]   # missing mandatory args
    invalid_enums: dict        # param → provided_value vs valid_values
```

`CAPValidator.validate(cap, agent_name)` returns a `JudgeVerdict`. It checks:
1. The directive exists in the agent's capabilities registry
2. All mandatory arguments are present
3. The values of `Literal[...]` parameters are in the declared enum

`CAPValidator.update(capabilities)` is called in `pilot.py` after each `_fetch_capabilities()` to keep the index up to date.

Graceful degradation: if the index is empty (capabilities not yet loaded), `passed=True` to not block startup.

#### `pilot.py` — improvements (2026-03-15)

- **`_judge_cap(cap, agent_name)`**: calls `CAPValidator.validate()` before each `execute_cap()`. If verdict is `passed=False`, logs the error and returns a failure `ToolResult` without a network call.
- **`_auto_list` — retry x3 with backoff**: if `list_capabilities()` fails, retries at 2s, 4s, then fails definitively. Avoids panics at startup if the tool-agent is slow.
- **`_summarize_capabilities`**: now includes `fn_desc` (function description) in mutation lines — the coordinator LLM sees the context of each destructive action.
- **`state.checkpoint_at`**: `float` timestamp set on each transition to `CHECKPOINT_WAIT`. Used by the watchdog.

#### `server.py` — checkpoint watchdog (2026-03-15)

`_checkpoint_watchdog()`: an asyncio task started in the lifespan. Every 30s, it iterates through plans in `CHECKPOINT_WAIT` and auto-rejects those whose `checkpoint_at` exceeds `CHECKPOINT_TIMEOUT` (default: 300s, configurable via `CHECKPOINT_TIMEOUT` env var). Avoids orphan plans that block resources indefinitely.

### Plan State Machine

```text
PLANNING → EXECUTING → SYNTHESIZING → DONE
                ↓
         CHECKPOINT_WAIT ──approve──→ EXECUTING
                ↓
              reject
                ↓
            ABORTED
```

### Coordinator API

| Method | Route | Description |
| --- | --- | --- |
| `POST` | `/coordinator/execute` | Starts a plan (body: `{"query": "..."}`) |
| `GET` | `/coordinator/status/{run_id}` | Full status of a plan |
| `GET` | `/coordinator/checkpoint/{run_id}` | Tasks awaiting approval |
| `POST` | `/coordinator/checkpoint/{run_id}/approve` | Approve and resume |
| `POST` | `/coordinator/checkpoint/{run_id}/reject` | Abort the plan |
| `GET` | `/coordinator/capabilities` | Proxy to `/capabilities` on port 3000 |

### Human Checkpoints

Actions detected as destructive (containing `delete`, `remove`, `ban`, `block`, `disable`, `supprim`, `efface`, `désactiv`) are marked `requires_approval=True` by the LLM.
The plan pauses with `status: checkpoint_wait` — the operator reviews the pending tasks and approves or rejects before execution resumes.

### Coordinator Auth

`X-API-Key` header required on all routes except `/coordinator/health`.

- Environment variable: `COORDINATOR_API_KEY`
- Not configured → dev mode, warning at startup, free access
- Wrong key → HTTP 401 `{"error": "UNAUTHORIZED"}`

Any new coordinator route **must** include `dependencies=[Depends(verify_api_key)]`:

```python
@app.post("/coordinator/new_route", dependencies=[Depends(verify_api_key)])
async def new_route(...):
    ...
```

### Environment Variables

```bash
TOOL_AGENT_URL=http://localhost:3000       # URL of the tool-agent-server
TOOL_AGENT_KEY=                            # same value as AGENT_API_KEY
COORDINATOR_API_KEY=changeme-strong-key    # key to protect the coordinator
COORDINATOR_BACKEND=vllm                   # "vllm" or "ollama"
COORDINATOR_MODEL=Qwen/Qwen2.5-3B-Instruct
COORDINATOR_GPU_UTIL=0.89                  # see VRAM budget above
VLLM_MAX_MODEL_LEN=8192                    # coordinator context size
COORDINATOR_OLLAMA_MODEL=qwen2.5:3b        # if BACKEND=ollama
CHECKPOINT_TIMEOUT=300                     # seconds before auto-rejecting a checkpoint (default 300)
```

### Startup

```bash
# Tool agents (port 3000)
python server.py

# Coordinator (port 3001)
python -m coordinator.server
# or
uvicorn coordinator.server:app --host 0.0.0.0 --port 3001
```

---

*Document version: 3.0 — Phase 4: Multi-LoRA Qwen2.5 inference (chat_format, system_prompt, _discover_lora_adapters normalization)*
*Target: AI Coordinator Agents & Advanced Developers.*