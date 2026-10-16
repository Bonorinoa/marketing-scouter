# SE architecture plan — 2026-10-16 (Systems Engineer)
Read-only pass. No code, pins, or live data changed. Builds on docs/AUDIT-2026-10-16.md (mapping and the Hermes comparison are not repeated here).

## (a) Where I disagree with the audit
1. **Langfuse Cloud for LLM spans.** LLM spans carry the post text in the prompt, so this breaks "post text not exported". Default: **no off-box export**. If Augusto wants a viewer, use **Arize Phoenix self-hosted** (`pip install arize-phoenix`, one process, SQLite, about 0.5–1 GB RAM; the box has about 6 GB free and no docker). It ingests the same OTLP. Langfuse self-host v3 is too heavy for this VM. Langfuse Cloud only with Augusto's OK, and only with prompt and completion bodies redacted.
2. **"Single discover() used by both CLI and API."** The only CLI caller of `pipeline.py` is the Streamlit `app.py`, along with `seed.py`, `theme.py` and `adapters/stubs`. That is a dead second UI. Archive it (move it to `legacy/`, don't delete) and make the API's path the only discovery path, instead of keeping two callers in sync.
3. **The hash chain over all events in the merged table.** Keep the **Wins chain separate and unchanged**: it is the O-1A evidence, and its pins must not move. The new events table gets its own chain. Old jsonl files are frozen and read through a union view (agreed).
4. **OTel span file and events table are not two systems of record.** The events table is the record. Spans are derived telemetry for latency, flow and cost, and they can be rotated or discarded. Every span carries `event_id`s so the two can be joined.
5. Small: put `code_sha` and `prompt_sha`/`style_sha` on **every** event, not just as card-level provenance. Cards get re-graded and re-drafted under different builds.

## (b) Local OTel span file
- **Library:** `opentelemetry-sdk` with a custom `SpanExporter` that writes JSON lines (one span per line, OTLP-JSON field names) to `<data_dir>/traces/spans-YYYYMMDD.jsonl`. Append-only, rotated daily, local only, per-server `data_dir` so `:8713` never writes to live's file. Phoenix or Langfuse can replay these files later via OTLP.
- **trace_id per card:** derived deterministically, `trace_id = sha256("card:"+card_id)[:32]`. Discovery runs before the card exists, so the discovery span is keyed by `x_status_id`, and the card trace links to it with a span **link** (`run_id` trace → card trace). Later human actions (queue view, copy, dismiss, Win days later) start a new span with the same derived trace_id, so the whole life of a card is one trace even across days and processes.
- **Spans:** `discovery.run` (root per run: lane, query_id) → `intake.post` → `fit.grade` (one per asset) → `score` → `draft` (`xbrief.run` child, `echo.perspective` child) → `queue.enqueue` → `human.action` (view|copy|dismiss|later) → `win.log`.
- **Attributes (allowlist; anything not listed is dropped by the exporter):**
  - ids: `ms.card_id, ms.run_id, ms.x_status_id, ms.candidate_id, ms.event_ids[]`
  - provenance: `ms.query_id, ms.lane, ms.source_tag, ms.adapter, ms.source_url_sha` (hash of the URL, not the URL), `ms.fetched_at, ms.raw_sha`
  - model: `gen_ai.system, gen_ai.request.model` (e.g. deepseek/deepseek-v4-flash, echo), `gen_ai.usage.input_tokens/output_tokens, ms.cost_usd`
  - versions: `ms.prompt_sha, ms.style_sha, ms.rubric_sha, ms.claims_sha, ms.code_sha` (git rev at server start, from build_info), `ms.pin`
  - outcome: `ms.api_status, ms.fit_level, ms.S, ms.decline` (bool only), `ms.is_test` (from server config only)
- **Never exported:** post text, draft text, decline reason text, Augusto's notes, handles, full URLs. This is enforced by the allowlist exporter plus a pinned test that sends a span containing post text and asserts it isn't in the file.
- **Flow view:** a ~60-line `/telemetry/flow` endpoint reads today's span file and returns counts, p50/p95 per stage and drop-off per stage. TracePanel adds a timing strip. No new service.
- **Size:** about 3h (SDK, exporter, 8 instrumentation points, 3 pinned tests). Adversarial Tester reviews the allowlist and the is_test path before deploy.

## (c) codebase-memory-mcp (NOT installed)
- **What it is:** DeusData/codebase-memory-mcp, MIT license, about 46.7k stars, created Feb 2026, latest v0.12.0 (Oct 15). A single static C binary that runs an MCP server over stdio. It indexes a repo into a local code graph (functions, imports, calls, HTTP routes; 162 languages, LSP-assisted for Python and TS) for agent queries with fewer tokens. It also has an optional "CBM Lens" web UI on loopback (`--ui=true`). No API key, local indexing.
- **Risks for AT to vet:**
  1. The recommended install is `curl … install.sh | bash`. It downloads the latest release binary and **auto-edits agent configs** unless run with `--skip-config`, and it installs a self-updater to `~/.local/bin`. Prefer a pinned release tag with checksum verification, `--skip-config`, and no auto-update.
  2. v0.12.0 is one day old, with 231 merged PRs, so pin the previous stable release or build from source at a tag.
  3. The Lens UI includes a "browser-local assistant": confirm it makes no outbound calls, and keep the UI off.
  4. The index stores code (and any secrets in the repo, e.g. `data/db/.handoff_secret`) on disk: exclude `data/`, `.venv`, `logs/`.
  5. The MCP server can read whatever paths it is given, so limit it to the repo.
- **Rating:** dev-only and useful for core.py navigation. Low value once core.py is split.

## (d) Echo by Fulcrum
- **What it is:** a writing model trained for style imitation, with an OpenAI-compatible API at `https://echo.fulcrum.inc/api/v1` (`/chat/completions`, `/responses`, `/models`). The only model is `echo`. A **`persona` parameter is required on every request** (400 without it). It works with widely published writers (Feynman qualifies) **or writing samples placed in the message**, which is the way to calibrate on Augusto's voice. There is no stored voice profile, and the API is stateless. `reasoning_effort` is low|medium|high|max (higher can take over a minute), and reasoning comes back separately as `reasoning_content`.
- **Auth/pricing:** `Authorization: Bearer $ECHO_API_KEY` from echo.fulcrum.inc/keys. Usage is billed in credits: 2.5 credits per 1k input tokens and 10 per 1k output tokens (reasoning included); about 50 replies per 1k credits. Plans are $30/mo for 3k credits (about 150 replies), $100/mo for 11k, or $300/mo for 36k, plus credit packs. The playground is free. The model is "planned to be open-sourced". **Echo is not a free model and not on the approved list (deepseek-v4-flash or free models only), so Augusto must approve it explicitly.**
- **Needs Augusto:** an Echo account sign-in, an API key (or a plan purchase), and approval of the spend. The key goes in the server env (never in the repo, never logged). He also has to choose which samples to calibrate on, since they are sent to Fulcrum.
- **Integration point:** a new `src/api/echo_bridge.py` (~120 lines, same shape as `xbrief_bridge`: timeout, sanitize, provenance). It is called in core's draft step **after** the xbrief/deepseek draft succeeds and the claim and caveat gates pass. It never replaces the main draft and never feeds the copy button.
  - Request: `persona="Richard Feynman"`, input = the post text plus the claim (the post goes to Fulcrum, which is acceptable because it is public), `reasoning_effort=low`, `max_tokens≈600`.
  - Output: `card.perspective = {text, persona, model:"echo", prompt_sha, credits_est}`, shown as a collapsed "A second angle (Feynman)" panel. Its text goes through `sanitize_reason`-style cleaning and the voice/claim gate before display.
  - Optional mode: persona = "Augusto Bonorino" with 3–5 of his posts in the message, as "rewrite in my voice" chips.
  - Budget guard: a daily credit cap in config (e.g. 20 calls/day ≈ 400 credits), and the request is generated only when Augusto clicks "Second angle", not on every card. This keeps the $30 plan sufficient.
- **Size:** about 3h once there is a key; it can be built and tested now against a stub. AT should review the prompt-injection path (post text → Echo → UI) before deploy.

## Today (proposal)
1. OTel span file plus `/telemetry/flow` (3h, AT review).
2. Echo bridge behind a feature flag with a stub, plus UI panel (3h; live calls only after Augusto provides a key).
3. Archive the Streamlit `app.py` path to `legacy/` (1h, tests stay green).
Events table and core split: next week, as the audit says.
