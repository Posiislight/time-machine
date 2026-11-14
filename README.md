# Time Machine — local first build

A working foundation for agent checkpoint recovery. Runs on Python 3.11+ with no third-party packages. No hosting, Docker, database service or cloud storage required.

## Windows

1. Extract the `time-machine` folder to `C:\Users\Adele\time-machine`.
2. Install Python 3.11+ if needed.
3. Double-click `start.bat`. Your browser opens http://127.0.0.1:8765.
4. Click **Load sample**. Select **Supplier data imported**, then **Branch from checkpoint**. Inspect the restored supplier.csv. Click **Run offline recovery** to generate the corrected catalogue without an API call. Select a checkpoint and click **Compare with workspace** to inspect changes. This performs real filesystem/context restoration, without a model key.
5. For live GLM execution, enter your OpenRouter key in `.env` (created by the launcher) and restart. Click **Run with GLM** in the branch. The model can read and write text/CSV/JSON/Markdown files. Requests incur your provider's API charges.

Linux/macOS: copy `.env.example` to `.env`, then `python3 server.py`.

## Current scope

- Local dashboard, task creation, text-file entry and file inspection.
- SQLite persistence and immutable checkpoint directories.
- Branches restore file bytes and conversation/tool history, leaving originals unchanged.
- SHA-256 file verification before restore.
- OpenRouter tool-calling loop configured for GLM 5.3 Flash, capped at 12 model calls per execution and 2,000 requested output tokens per call. This is a turn bound, not a monetary budget guarantee.
- Sample catalogue with deliberately incorrect fixture prices; clearly labelled and never represented as live AI output.
- Loopback-only server, per-session mutation token, workspace path restrictions; no shell tools.

## Not implemented yet

Verified live Maritime execution and restore (the sandbox snapshot adapter below exists but has only been tested against an in-memory fake of the documented API), Playwright/browser operation, screenshots, PDF/image extraction, external app writes, full VM snapshots, automated error detection, cost accounting, authentication for shared use and incremental storage. The first model integration is a file agent, not yet a browser operator. Live OpenRouter access requires your key and has not been validated with a paid request in this build.

The read-only Maritime integration requires MARITIME_API_KEY only when you use Connect Maritime. It lists agents, browses root files, and imports up to 20 explicitly selected UTF-8 files (2 MB each) into a new local run. File reads can wake a remote agent and incur compute charges. It does not import remote conversation history or reverse remote actions. Do not publish this development server or bind it to a public network.

## Architecture

Browser (HTML/CSS/JS) → Python HTTP API → SQLite metadata + local `data/checkpoints/` files.
Python agent loop → OpenRouter GLM → allowlisted file tools → checkpoint after each complete tool-call batch.

The backend is intentionally dependency-free for this first local build. A future frontend can use the same API; the earlier Next.js/Fastify/AWS proposal is not required to run this version.

## Verification

`python -m unittest discover -s tests -v`

All runtime data is under `data/`. Checkpoints contain conversations and file contents, so treat that folder as private. The server loads `.env` on startup only. Environment variables already defined in your shell take precedence.

A checkpoint captures logical agent context and files, not RAM or open browser sessions. Each restore creates a new run. Concurrent execution is prevented per run. Interrupted runs are marked on restart; restore a completed checkpoint to recover.


## Chrome / Edge extension

1. Open `chrome://extensions` or `edge://extensions` and enable Developer mode.
2. Choose **Load unpacked** and select `C:\Users\adele\time-machine\extension`.
3. Start the app using `start.bat`. On Maritime pages a **Time Machine** launcher opens the local dashboard. The toolbar popup works on other pages too.
4. Choose **Connect Maritime** in the dashboard to capture selected remote files. Put your Maritime key in `.env` first and restart.

The extension is a launcher integration, not a modification of Maritime's own source. It collects no page content, cookies or credentials and makes no remote API calls. Remote access happens only through the local Python backend. No browser automation or VM snapshot restoration is implemented.

## Demo you can show a founder

Load sample → select **Supplier data imported** → branch with the corrected instruction → **Run offline recovery** → inspect `catalogue.csv` → select the restored checkpoint → **Compare with workspace**. The original incorrect run remains available in the sidebar. This is a deterministic demonstration, clearly marked in the activity log; **Run with GLM** is the separate live model path.

## Verification limits

The suite covers local persistence, corruption rejection, path boundaries, tool execution, offline recovery, checkpoint diffs, a simulated Maritime transport, and full HTTP request parsing through the Python handler. This managed session blocks outbound networking and loopback client connections, so HTTP tests use an in-memory connection. Browser rendering, extension installation, live Maritime access, and paid OpenRouter calls have not been verified here. The requested `z-ai/glm-5.3-flash` ID is preserved as a configurable value and has not been confirmed against the provider catalogue. Change `OPENROUTER_MODEL` if your account reports it unavailable.


## General session recovery (new)

Use **Shopping recovery demo** in the sidebar, select **Rewind: Before checkout**,
review the consequences, acknowledge them and create a recovered branch.
The **Uncertain payment demo** blocks recovery until you record a verified outcome
and evidence. These are explicit simulations: they do not charge money, send mail,
operate a real phone, or reclaim an IP. Reconciliation evidence in this demo is
operator supplied, not independently checked against a payment provider.

The new `sessions.py` engine stores logical resource snapshots, immutable checkpoint
rows, append-only events, and a lineage-wide external-action ledger in SQLite.
Browser/agent logical state enters a recovered branch. Unsupported phone/network
observations are retained as historical evidence, never presented as restored live state.
Warnings are generated deterministically from ledger records and adapter capabilities;
no LLM key is needed. The GLM file agent remains a separate existing feature.

Rewind previews include a receipt covering the checkpoint, resources, external effects
and lineage event revision. The commit rechecks this inside a SQLite write transaction.
A new action or reconciliation makes older previews stale. Pending/unknown actions
block recovery. Completed payments/messages remain visible in all descendant branches.
Unique operation keys prevent dispatching a recorded external operation twice through
this engine. They cannot prevent writes made outside the instrumented runner.

### Integrating an agent tool loop

`session_runner.SessionRunner` wraps caller-provided resource adapters. An adapter
implements `capture()` returning `{recovery: "logical" | "unavailable", state: ...}`,
`execute(action, operation_key=...)`, and `verify(result)` for external effects.
Verification returns `{status: "completed" | "not_completed", evidence: "..."}`.
Anything unverified remains pending and blocks recovery. Persist an operation key
before executing an external action, including a click that submits an order.
Adapters must pass idempotency keys to external services where those services support them.
Call the runner serially at tool-dispatch boundaries; it is not a multi-machine
atomic snapshot protocol. Live restore adapters, a general computer-use model loop,
provider-verified reconciliation and VM snapshots remain integration work.

### Local API

All POST routes require the existing `X-Local-Token` from `/api/state`.

- `GET /api/sessions`, `GET /api/session?id=...`
- `POST /api/session/create` with `title`, `resources`
- `POST /api/session/update` with `session`, `resources`
- `POST /api/session/checkpoint` with `session`, `label`
- `POST /api/session/effect` with `session`, `key`, `kind`, `status`, `detail`
- `POST /api/session/reconcile` with `session`, `effect`, `status`, `evidence`
- `GET /api/rewind-preview?session=...&checkpoint=...`
- `POST /api/session/rewind` with `session`, `checkpoint`, `receipt`, `acknowledge: true`

Store only the resource state needed for recovery. The local database is not encrypted;
do not capture passwords, payment credentials or authentication cookies into demo resources.


## Maritime sandbox adapter (snapshot restore)

`sandboxes.py` wraps Maritime's sandbox API, and `SandboxAdapter` plugs it into
`SessionRunner`. A checkpoint saves a real snapshot of the running sandbox
(`POST /v1/sandboxes/{id}/save`). `session_runner.rewind_and_restore` commits the rewind
first, then starts a NEW sandbox from the checkpoint's snapshot. The original sandbox is
left running and billing until you end it. Resources use the capability `snapshot`.

Safety behaviour, covered by `tests/test_sandboxes.py`:

- A side effect only unblocks rewind when a `verifier` you supply confirms the real
  outcome. With no verifier, effects stay pending and rewind is blocked.
- Only an error the provider marks `execution_started: false` is recorded as not
  completed (safe to retry). Timeouts and lost responses stay pending.
- Stale receipts and unreconciled effects create no machine, because the rewind commits first.
- Sandbox secrets live in client memory only. They are never written to the session database.
- Names and IDs are validated, and the data-plane address must be `https` on `*.mtm.sh`
  before the sandbox token is sent to it.

Not verified against real Maritime (checked only against the public docs):
the `/v1/sandboxes` base URL on `api.maritime.sh`, the response shape of `save`, whether `save`
needs a running sandbox, whether a restored sandbox resumes memory or only disk, snapshot
name rules, and whether the data plane accepts `{"cmd": ...}` with `X-Maritime-Token` exactly
as documented. Every checkpoint stores a snapshot; `Sandboxes.delete_snapshot` exists but
nothing calls it, so snapshots accumulate and may be billed. `operation_key` is ledger-only
for commands because Maritime documents no idempotency key for them.
