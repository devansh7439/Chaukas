# Chaukas work log

What has been built, how it works, and what is left. A new entry is added at the end of
every piece of work, so this file is always current. The design spec is
[Chaukas_BLUEPRINT.md](../Chaukas_BLUEPRINT.md); this log says how far the code has got.

- [1. How Chaukas works today](#1-how-chaukas-works-today)
- [2. Running it](#2-running-it)
- [3. What is left](#3-what-is-left)
- [4. Log entries](#4-log-entries)

---

## 1. How Chaukas works today

### 1.1 The idea in one paragraph

Chaukas listens to a call on a Windows PC and watches what happens on the screen. It does
not flag single suspicious words ("CBI", "arrest") or single suspicious actions (installing
AnyDesk). It flags **combinations**: someone claiming authority, applying pressure, and
steering the user towards an action (sending money, installing a remote-access tool,
reading out an OTP), usually in that order. The more of that pattern it sees, the higher
the alert: quiet → notice → warning → critical.

### 1.2 The pipeline

```
 call audio ──► [audio + ASR: NOT BUILT YET] ──► transcript segments (who said what, when)
                                                        │
                                                        ▼
                                          signals/  keyword extraction  ─────────┐
                                                        │                        │
                                                        ▼                        ▼
                     context/  desktop monitor ──► engine/  risk engine ◄── llm/  reasoning
                     (apps, bank pages,                 │
                      downloads)                        ▼
                                                  RiskState: level, objective, reasons
                                                        │
                                                        ▼
                                          [UI: NOT BUILT YET]  today: printed by the CLI
```

Until audio and speech-to-text exist, transcripts come from **case scripts**
(`eval/cases/*.yaml`): lines of dialogue with times, plus screen events. Replay feeds them
through exactly the code the live app will use.

### 1.3 The parts, one by one

**`core/` - shared foundation.** The data types every layer passes around (`Segment` = one
stretch of speech; `Signal` = one piece of evidence; `ContextEvent` = something seen on
screen; `RiskState` = the engine's verdict), an event bus, clocks (a real one, and a virtual
one for replay), and config loading. Every tunable number lives in
`resources/default.yaml`; nothing is hard-coded.

**`signals/` - keyword evidence, instant, on CPU.** Each caller segment is normalised
(lowercase, Hindi digits → ASCII, "don't" → "do not", "ek do teen char" → "1234") and
scanned in one pass (Aho-Corasick) for lexicon terms in English, romanised Hindi and
Devanagari. Terms have tiers: *weak* 0.3 ("officer", "urgent"), *strong* 0.5 ("CBI",
"arrest"), *phrase* 0.6 ("kisi ko mat batana"), *fast path* 0.75 (a request verb near a
request object: "OTP batao", "download AnyDesk"). Protective advice is suppressed ("we will
never ask for your OTP"), as are postal "pin codes" and **Chaukas's own alert sentences**
(so an alert heard back through the speakers is never counted as the caller speaking). On
the user's side, reading out 4-8 digits soon after a caller asked for a code is a
`user_digits_spoken` signal.

**`engine/` - the risk engine.** Combines evidence into a score and a level:

```
P = pressure    noisy-OR of all tactic evidence, which fades with a 10-minute half-life
                of *speech* time (a silent "stay on camera" hold doesn't erase it)
G = addressed   0.3 if the LLM says the speech isn't aimed at the user (e.g. news)
A = action      0.70 no relevant screen activity, 1.0 if it matches the suspected attack
S = sequence    0.6 + 0.4 x how far the best-matching attack chain has progressed
R = P x G x A x S      (every gate <= 1, so R never exceeds P)
```

Three attack chains are tracked in parallel (`resources/templates.yaml`): digital arrest
(authority → threat → isolation/surveillance → money → bank page), remote access
(authority → fear → install request → remote app/download), credential theft
(authority → urgency → OTP request → OTP field). Levels: notice at R ≥ 0.20; warning at
R ≥ 0.45 *and* a coercive tactic (threat, isolation or surveillance); critical at R ≥ 0.70
*and* every required chain step *and* matching screen activity. Special rules: a caller
asking for an OTP after claiming authority goes **critical immediately**, before the user
answers, and **stays critical until the call ends**; if the user then reads out digits,
it becomes the recovery alert. Alerts don't flicker (30 s hysteresis) and can be dismissed
for 3 minutes unless something new happens. The blueprint's 16 worked examples are unit
tests.

**`llm/` - AI reasoning (built this session).** A local LLM answers one question: "what is
the caller trying to make the user do?" It is called sparingly (it costs NPU time): right
after a strong keyword, on a screen event while an alert is showing, or on a 45 s heartbeat
if there has been enough new caller speech, at most once per 8 s and one at a time. The
prompt shows the last 90 s of transcript as `[L12 t=63.2][CALLER] ...` lines. The model
returns JSON: tactics and requested actions, each with a line number and a short quote.
**The evidence guard only keeps an item if its quote really appears in the caller line it
cites**, so an invented claim is thrown away. Kept items become signals timed at the line
where they were said, so a slow answer can never scramble the attack order. The LLM also
says whether speech was addressed to the user, which is what keeps a news bulletin about
scams quiet. It talks to any OpenAI-compatible server (GenieX on Snapdragon; llama.cpp,
Ollama or LM Studio on a dev PC).

**`context/` - the desktop monitor (built this session).** Once a second it checks:
new processes (AnyDesk, TeamViewer, Quick Assist and others, also when renamed, via the
file's version info); the foreground window title (bank page, transfer page, OTP page, e.g.
"DemoBank (MOCK) - Transfer Funds"; "WeTransfer" doesn't count); and executables arriving
in Downloads (including the browser's rename from `.crdownload`). Tools already running
before the call are ignored.

**`evaluation/` - replay and scoring.** Replays a case through signals, the engine and
(optionally) a real LLM on a virtual clock, then scores it: detection, **critical before
harm** (the headline metric), false alarms, warning latency, objective accuracy, LLM JSON
validity, LLM evidence rejected, and LLM calls per minute, all with 95% confidence
intervals. `ablate` runs configurations A-E (keywords only → full Chaukas → full minus
LLM) to show what each layer adds.

**`ui/strings.py`** - the alert text in English and Hindi (the rest of the UI is not built).

### 1.4 Quality bar

Every change is written test-first. Current state: **483 tests, 97% coverage, `ruff` lint
and format clean, `mypy --strict` clean.** Everything that touches Windows goes through thin
wrappers so the logic is tested without the OS, and the wrappers themselves are tested for
real on this PC.

---

## 2. Running it

```powershell
uv sync --extra context                 # dev tools + the context monitor's packages
uv run pytest                           # all tests
uv run chaukas replay eval/cases/DA01.yaml --ablation D   # one case, alert timeline
uv run chaukas eval eval/cases --ablation D               # score every case
uv run chaukas ablate eval/cases                          # configurations A-E side by side
```

With a real LLM (any OpenAI-compatible server; point `llm.base_url` at it in a YAML file
passed with `--config`):

```powershell
uv run chaukas eval eval/cases --ablation D --llm --llm-cache eval/cache/qwen
uv run chaukas eval eval/cases --ablation D --llm --llm-cache eval/cache/qwen --llm-offline
```

The first run calls the model and records every answer with its latency; `--llm-offline`
replays those answers exactly, with no model running.

---

## 3. What is left

Built so far: core, signals, engine, evaluation, LLM layer, context monitor, alert text.

| Still to build (in order) | Notes |
|---|---|
| Mock bank site (`mockbank/`) | Four local pages titled "DemoBank (MOCK) - ..." |
| Real-LLM smoke test | A small model is downloaded to `models/llm/` (git-ignored) |
| Privacy session (`privacy/`) | 5-minute transcript buffer, wipe on "End session" or 30 min idle |
| Audio (`audio/`) | Two-stream capture, speech detection (Silero VAD), segmenter, playback and echo guards, file replay |
| Speech-to-text (`asr/`) | Whisper on CPU now (`faster-whisper-small` is cached on this PC); NPU backend behind the same interface |
| UI (`ui/`) | Tray, notice / warning / critical cards, Why panel, privacy panel, capture exclusion |
| Live app + `run.bat` | Wires threads together; one-command start |
| Tooling | `tools/download_models.py`, `bench/`, `eval/assemble.py`, `labels.csv`, more cases |
| Docs | Full README, architecture diagram |

**Only you can do these:** Device Cloud sessions on a real Snapdragon laptop (NPU runs and
benchmarks, blueprint 7.2), recording voices for the 60-case dataset, blind scripts from
friends for the test split, a native speaker's review of the Hindi alerts, and reading the
competition's submission form and rules.

---

## 4. Log entries

### 2026-09-23 - Review of the codebase

Read every file and ran every check. Found: core, signals, engine and evaluation complete
and well tested (309 tests, 98% coverage); nothing yet for audio, ASR, LLM, context, UI,
privacy or tooling; no Snapdragon work; 6 commits never pushed.

### 2026-09-23 - Fixes from the review (4 commits, pushed)

- **OTP alert faded while the scammer stalled** (`engine/risk.py`). The rule compared
  fading evidence against 0.7, so a 0.75 "OTP batao" dropped below after ~60 s of speech
  and the critical alert fell to notice before the user had said anything. Now a critical
  or recovery alert raised by the OTP rules holds until the session ends; warnings still
  fade; if a different attack later reaches the same level, its objective is shown.
  Recorded in the blueprint (6.7).
- **Chaukas could hear itself** (`ui/strings.py`, `signals/lexicon.py`). Added the alert
  text (8 alerts, English and Hindi) and made every sentence of it a suppression phrase;
  before, 8 of those sentences would have counted as a scammer's words.
- **Honest ablation output** (`app.py`, `evaluation/report.py`). `eval` and `ablate` now say
  when LLM configurations were scored on hand-written verdicts. Fixed a wrong comment and
  a wrong docstring.
- **Tooling.** `uv run pytest` failed with a uv launcher error; fixed with
  `uv sync --reinstall` and documented in the README.
- Pushed all commits to `github.com/devansh7439/Chaukas`.

### 2026-09-23 - M5: LLM reasoning (`llm/`, commit f3d3ea0)

Files: `trigger.py` (when to call), `prompts.py` (what to send), `client.py` (HTTP call,
validate, retry once), `schema.py` (parse the JSON leniently, validate each item),
`evidence.py` (the quote check), `cache.py` (record answers for reproducible evaluation),
`reasoner.py` (ties them together in three steps so the slow call can run on its own
thread).

Decisions:
- **No `openai` package.** The client is ~60 lines of standard library. The package's
  native dependency might not install on Windows ARM64 (the Snapdragon machine), and one
  JSON POST doesn't need it. Recorded in the blueprint (section 3).
- **Small models are messy**, so parsing finds the JSON inside chatter or code fences,
  accepts "0.7" and "true" as strings, and drops bad items one by one instead of losing
  the whole answer.
- **A timed-out call still costs time** in replay (the error carries how long it took).

Also changed:
- Replay became a single event loop, and **a transcript line now appears when it ends**
  (when speech recognition would deliver it), not when it starts. Before, anything
  happening during a long line was applied late. Existing results didn't change.
- `replay`, `eval` and `ablate` gained `--llm`, `--llm-cache DIR` and `--llm-offline`.
- Metrics gained LLM JSON validity, evidence rejected, and calls per minute on benign
  cases.

Tests: 63 new LLM tests, including a real local HTTP server rather than mocks.

### 2026-09-23 - M6: Context monitor (`context/`, commit b504e4b)

Files: `resources/context.yaml` (the rules: bank names, transfer and OTP words,
remote-tool names, executable extensions, OCR keywords), `rules.py` (pure
classification), `processes.py`, `windows.py`, `downloads.py` (the three watchers),
`win32.py` (Windows API via `ctypes`), `monitor.py` (the 1 Hz background thread),
`replay_events.py` (read and write `eval/events/<case>.jsonl`).

Decisions:
- **`ctypes` instead of `pywin32`**, again to avoid an ARM64 install risk; removed from
  `pyproject.toml`.
- **Tools already open when the call starts are ignored**; only new ones count.
- **Renamed installers are still caught** through the executable's CompanyName /
  ProductName, read only for new processes so each poll stays cheap.
- **A title must name a bank** before "Transfer" counts, so WeTransfer and "transfer
  learning" videos don't.
- A reader that fails (access denied, window closing) is logged and skipped; the
  monitor keeps running.

Tests: 58 new, including real Windows calls on this PC (foreground window, Downloads
folder, version info of `python.exe`) and a real folder watcher catching a browser-style
`.crdownload` → `.exe` rename.
