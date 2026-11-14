# Time Machine for Maritime

**Rewind an AI agent's work safely. Undo what can be undone, keep what can't, and never repeat an action that already happened.**

Agents don't just think, they act: they archive emails, send messages, move meetings. When one fails halfway, "just restore a snapshot" is not enough. A snapshot can bring back a machine, but it cannot unsend an email. Time Machine records every step an agent takes on a Maritime computer, shows exactly what a rewind would change *before* you do it, and keeps a ledger of everything that reached the outside world.

▶ **Demo:** a 73-second video, shared separately. It shows both scenarios below on a real Maritime computer.

## What it does

1. **Snapshots every step.** Each step an agent takes on a Maritime computer or sandbox becomes a checkpoint.
2. **Previews a rewind.** Pick a moment on the timeline and see *Comes back* and *Stays as it is* before committing.
3. **Rewinds what can be undone.** Archived emails return to the inbox, calendar events are removed.
4. **Keeps what can't be undone.** Sent emails stay sent. They stay on the record in every later branch, and re-running the same operation is refused, so nothing is sent twice.
5. **Refuses to guess.** If an action's outcome is uncertain (the call timed out, the response was lost), rewinding is blocked until it is reconciled with evidence.
6. **Leaves a receipt.** After a rewind you get a new, recovered branch showing each action as *undone* or *done (kept)*.

## Demonstrated on real apps

Both ran on a Maritime computer (remote desktop) with a real Google account, with results checked independently of the screen recording:

- **Gmail:** the agent archives 10 promotional emails and sends 2 follow-ups, then fails. Rewind returns all 10 to the inbox; the 2 sent follow-ups stay in Sent and are not re-sent.
- **Google Calendar:** the agent books 3 meetings and emails a notification. Rewind removes all 3 meetings; the notification stays sent.

The failure in the Gmail scenario is staged, and is labelled as such in the video.

## Run it

No third-party packages. Python 3.11+.

```bash
cp .env.example .env     # add MARITIME_API_KEY for live Maritime sessions
python server.py         # http://127.0.0.1:8765   (Windows: double-click start.bat)
python -m unittest discover -s tests -v
```

`OPENROUTER_API_KEY` is only needed for the older GLM file-agent demo. Everything about sessions, the ledger and rewind works without a model key.

To reproduce the Gmail and Calendar scenarios on your own Maritime computer, set `TM_COMPUTER` (computer id) and `TM_EMAIL` (the Google account signed in on it) and see `scripts/film.py`. Test emails go only to that account.

## How it works

```
agent / script ──► SessionRunner ──► resource adapters (Maritime computer, sandbox, logical state)
                       │
                       ▼
         SQLite: immutable checkpoints · append-only events · lineage-wide action ledger
                       │
                       ▼
       rewind preview + receipt ──► new recovered branch (originals untouched)
```

- `sessions.py`: checkpoints, event log, external-action ledger (pending / unknown / completed / not completed / undone), rewind preview and receipt, acknowledgement, blocking on uncertain effects.
- `session_runner.py`: wraps caller-provided adapters; an action is written to the ledger *before* it is attempted, with a unique operation key.
- `workspace.py`: records undo recipes for reversible actions on a Maritime computer and replays them on rewind (in short batches, because long ones can time out).
- `sandboxes.py`: Maritime sandbox adapter; a checkpoint saves a real snapshot and a rewind starts a new sandbox from it.
- `static/`: the dashboard (timeline, rewind preview, receipt). `extension/`: a small Chrome/Edge launcher.
- `video/` and `scripts/film.py`: how the demo video was filmed and cut.

## Honest limits

- **Reversible effects on a computer are undone by replaying recorded screen actions**, so they depend on the page layout and on screen coordinates. It works, but it is the fragile part. A native snapshot/restore of a whole computer from Maritime would remove most of that fragility.
- Unverified: whether a restored sandbox resumes memory or only disk, snapshot limits and rate limits. Snapshots accumulate and may be billed until removed.
- Reconciling an uncertain action uses evidence the user supplies; it is not independently verified against the provider.
- The server is built for one person on one computer (loopback only, per-run token, one shared SQLite file). The local database is not encrypted; don't capture passwords or payment credentials into session state. Do not expose it on a public network.
- 43 tests cover persistence, corruption rejection, path boundaries, the ledger, rewind rules and the HTTP layer, mostly against simulated transports. Live behaviour was verified by hand on a real Maritime computer and sandbox in November 2026. The browser extension has not been tested in Chrome.

## Proposal

Make "rewind with a ledger" a first-class Maritime feature: native computer snapshot/restore, an action ledger that agents write to before acting, and a rewind preview and receipt in the product. This repository is a working prototype of the part that matters: the recovery engine, which keeps its guarantees regardless of how restoration is done.

### If this were hosted

It would need real sign-in and per-user data, per-user Maritime keys stored encrypted instead of in `.env`, proper sessions instead of the loopback check and local token, snapshot clean-up and cost limits, and rate limiting. None of that changes the recovery engine.
