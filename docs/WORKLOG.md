# Chaukas work log

What has been built, how it works, and what is left. A new entry is added at the end of
every piece of work, so this file is always current. The design spec is
[Chaukas_BLUEPRINT.md](../Chaukas_BLUEPRINT.md); this log says how far the code has got.
Architecture: [ARCHITECTURE.md](ARCHITECTURE.md). Data model and file schemas:
[DATA_MODEL.md](DATA_MODEL.md).

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
                                   ui/  dashboard + alert windows (PySide6 / QML)
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

**`ui/` - the window (built this session).** A PySide6 / Qt Quick dashboard in the style of
the reference design, following the product flow: *background protection → detect → assess
→ interrupt → explain why → let the user decide*.

- **Home:** a headline that changes with the level ("You're protected." → "Pause before
  continuing."), a *Risk right now* card (level, what the caller seems to want, risk bar),
  action tiles (Pause, End session, Trusted contact, Helpline 1930, Privacy), the *Live call*
  panel (caller and user lines, tactic tags, the strongest current tactics as rings, and a
  box to type a line as the caller or as yourself), and a summary: pressure vs risk arcs,
  risk over time, and the attack pattern drawn as a route.
- **Interrupt:** three always-on-top windows that escalate: a corner notice, a side warning
  panel, and a full-screen critical card. On the critical card, "Continue anyway" unlocks
  only after "I understand this warning" is ticked. Nothing is ever blocked.
- **Why:** every reason with the moment it happened and what was said, the fact line
  ("There is no such thing as a digital arrest...") and the safe next steps.
- **Privacy:** where each kind of data is processed, the listening indicator with Pause, and
  End session (wipes everything). **Settings:** language (English / हिन्दी), trusted contact
  (saved only on this PC), hide alerts from screen sharing.

How it is put together: `live.py` (the session on a real clock, pure Python) →
`presenter.py` (engine state → plain text and numbers, both languages, pure Python) →
`bridge.py` (Qt properties and slots, ticks 4x a second) → `qml/` (the views; every colour,
size and timing lives in `Theme.qml`). Icons are Lucide SVGs recoloured on the fly by
`icons.py`; fonts are bundled so it looks the same on every PC.

### 1.4 Quality bar

Every change is written test-first. Current state: **556 tests, 97% coverage, `ruff` lint
and format clean, `mypy --strict` clean.** Everything that touches Windows goes through thin
wrappers so the logic is tested without the OS, and the wrappers themselves are tested for
real on this PC.

---

## 2. Running it

```powershell
uv sync --extra context --extra ui      # dev tools + context monitor + the window
uv run pytest                           # all tests
uv run chaukas replay eval/cases/DA01.yaml --ablation D   # one case, alert timeline
uv run chaukas eval eval/cases --ablation D               # score every case
uv run chaukas ablate eval/cases                          # configurations A-E side by side
uv run chaukas ui --demo eval/cases/DA01.yaml             # the window, playing a scam call
uv run chaukas ui                                         # the window, type lines yourself
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

Built so far: core, signals, engine, evaluation, LLM layer, context monitor, the window.

| Still to build (in order) | Notes |
|---|---|
| Mock bank site (`mockbank/`) | Four local pages titled "DemoBank (MOCK) - ..." |
| Real-LLM smoke test | A small model is downloaded to `models/llm/` (git-ignored) |
| Privacy session (`privacy/`) | 5-minute transcript buffer, wipe on "End session" or 30 min idle |
| Audio (`audio/`) | Two-stream capture, speech detection (Silero VAD), segmenter, playback and echo guards, file replay |
| Speech-to-text (`asr/`) | Whisper on CPU now (`faster-whisper-small` is cached on this PC); NPU backend behind the same interface |
| UI leftovers | System tray icon ("LOCAL MODE"), spoken alert clips (`assets/audio/`), onboarding consent screen |
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

### 2026-09-23 - M7: The window (`ui/`)

Built to the reference design the user supplied (soft grey panels, dark pill sidebar, one
copper accent), mapped onto the product flow the user gave: background protection →
detect → assess → interrupt → explain why → let the user decide.

Files: `live.py`, `presenter.py`, `copy.py` (every on-screen word in English and Hindi),
`settings.py`, `bridge.py`, `icons.py`, `capture_exclusion.py`, `app.py`, and 25 QML files
in `qml/`. Command: `chaukas ui [--demo CASE] [--speed N] [--screenshot PNG --at SECONDS]`.

Decisions:
- **Qt Quick (QML), not classic widgets**, because only QML can do this soft, layered look.
- **Shadows without GPU shaders** (stacked translucent layers), so it looks the same with the
  software renderer on VMs and Device Cloud, and headless screenshots match.
- **Fonts bundled**: Plus Jakarta Sans, and Noto Sans Devanagari for Hindi, which a VM may not
  have. Text switches font by language (and by content for Hindi typed in English mode).
- **Level is never colour alone**: always an icon and a word too; muted text keeps at least
  4.5:1 contrast; every control works from the keyboard with a visible focus ring; click
  targets are at least 44 px.
- **The critical card never blocks**: no countdown; "Continue anyway" needs one tick.
- **"Type what the caller said"** lets a judge try Chaukas with no microphone.
- **Engine addition**: `RiskState.evidence` now reports each tactic's current strength (for
  the rings). `Session.evaluate(t)` evaluates at an exact time (the screen shows "now", not
  the last whole second).

How it was checked: every QML file loads with zero Qt warnings in tests; each page and each
alert window was rendered to PNG and inspected, which found and fixed two collapsed layouts
(Why, Settings), an overflowing warning panel and clipped shadows; one render with the real
Windows renderer confirmed the text spacing; capture exclusion was tested on a real Windows
window. Tests: 556 (was 483).

Needs a person: a native Hindi speaker to review `copy.py` and `strings.py`.

### 2026-09-23 - Documentation: README, architecture, data model

The repo had no architecture document, ERD or schema reference; the blueprint's pipeline
sketch (2.1) and data contracts (5) predate the code. Written from the code as it is now:

- **[README.md](../README.md)**, rewritten for judges and developers: pitch, a 5-minute
  demo with no microphone, the problem, the "suspicious combinations" idea, how it works,
  what the user sees, an honest *What works today* table, privacy, all commands (including
  using a real LLM), development, related work, limitations, roadmap, credits and licences.
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: system diagram (built vs planned), components and
  dependency direction (verified against the imports), how one sentence becomes an alert
  (sequence diagram), the risk engine and alert-level state machine, the LLM's trigger and
  evidence guard, threads and time, evaluation, what runs where, design decisions, known gaps.
- **[DATA_MODEL.md](DATA_MODEL.md)**: why there is no database, an entity-relationship
  diagram of the in-memory model, every entity's fields, the enumerations, a storage map
  (what is shipped, written by developers, written at run time, and never written), and the
  schema of every file: config (every key and default), lexicon, templates, context rules,
  case scripts, replay events, the LLM reply, the LLM cache and `settings.json`.
- **Diagrams**: five Mermaid sources in `docs/diagrams/`, rendered to PNG in `docs/images/`
  so they show everywhere (GitHub, VS Code, PDFs). Rendering doubles as a syntax check; each
  image was inspected and two were redrawn for legibility.

Found while documenting (recorded as known gaps, not yet fixed):
- The config sections `audio`, `privacy` and `ui` are not read by any code yet.
- The window keeps the current call's transcript until "End session"; the blueprint's
  5-minute horizon arrives with the `privacy/` module.
- The window does not call the LLM or start the desktop monitor yet (both work in replay).

Correction: the demo's first notice arrives at about 8 s in the window (configuration E),
not 15 s as said earlier in this session; the README has the measured timings.

### 2026-09-23 - M8: Live protection (`audio/`, `asr/`, `ui/services.py`)

Chaukas now listens to real calls on this PC: `chaukas run` (or `run.bat`).

- `audio/capture.py`: WASAPI capture via PyAudioWPatch. Caller = loopback of the default
  output device; user = default microphone.
- `audio/convert.py`, `vad.py`, `segmenter.py`: 48 kHz stereo -> 16 kHz mono (soxr), Silero
  VAD v6 (the copy bundled with faster-whisper), segments closed after 0.6 s of silence or
  cut at the quietest moment before 12 s; gaps when loopback goes silent are handled.
- `audio/guards.py`, `pipeline.py`: one worker thread per stream, one transcription worker;
  echo guard (text) plus echo skip (mic speech inside the caller's speech is not
  transcribed); user lines wait until the caller's audio up to that moment is processed.
- `asr/whisper_cpu.py`: faster-whisper on the CPU, models loaded from disk only (no network
  during a call); drops Whisper's "Thank you." hallucinations; re-runs "Urdu" as Hindi.
- `ui/services.py`, bridge: audio and the desktop monitor feed the window from their own
  threads through queued signals; the window shows "Listening: caller = ... · you = ...".
  Pause drops audio before any processing. 5-minute transcript horizon and 30-minute idle
  session end are now enforced.
- CLI: `chaukas run`, `chaukas setup` (the only command that downloads), `chaukas devices`.

Measured on this PC (Intel i7-1360P, CPU only):
- Whisper small, 6.5 s of speech: 4.1 s with language auto-detection, 2.2 s with the
  language fixed; base: 1.1 s / 0.6 s. Whisper pays a fixed cost per call, so each
  speaker's language is detected once and reused, and a backlog is merged into one call.
- Live end-to-end (synthetic English scam call played through the speakers): all four
  sentences transcribed and tagged; notice 12 s, warning 14 s, **critical 35 s after
  playback started, about 17 s after "tell me the OTP"**. The mic's echo doubled the
  transcription load; the echo skip was added after this run and has not been re-measured.
- Hotwords ("OTP, AnyDesk, ..."), 24 synthetic scam + 24 innocent clips: key word heard
  22/24 vs 20/24 without, 0 invented either way. Every miss was "AnyDesk" written as
  "any desk", so the lexicon now has those spellings and hotwords stay off.

Bugs found by live testing and fixed:
- The Why panel dropped "claimed to be an official" / "threatened you" within seconds
  (reasons used faded evidence, and strong keywords start exactly at the bar).
- A threat keyword stopped counting as coercion within seconds of speech, so warnings
  needed isolation; coercion now lasts about 5 minutes of speech (`coercion_floor`).
- A timing-dependent echo test: the release rule now works in stream time.

Not yet: speech-to-text on Windows ARM64 / the NPU; Hinglish accuracy (only English
synthetic speech has been tested); real-model LLM in live mode.

### 2026-09-23 - Review fixes, part 1: prompt injection, Windows on ARM64, live timing

Working through the risk review in order.

**Prompt injection (commit f2e8882).** A caller could steer the LLM into "this speech is
not addressed to the user" (for example by saying "this is a recorded announcement"), and
that verdict used to switch the OTP rule off. Now it can only lower the alert to a warning,
and a critical alert already raised stays held.

**Windows on ARM64 (Snapdragon).** Checked PyPI for Windows ARM64 wheels of every
dependency. soxr, PyAudioWPatch, watchdog, ctranslate2 (faster-whisper) and
llama-cpp-python have none; numpy, onnxruntime (+ onnxruntime-qnn), PySide6, psutil,
cffi, tokenizers and av do. Replaced the first three:
- `audio/convert.py`: resampling in plain numpy (Kaiser-windowed low-pass, then linear
  interpolation; filter state carried between chunks, so no clicks at chunk boundaries).
- `context/downloads.py`: `DownloadPoller` lists the Downloads folder once a second as part
  of the context monitor's poll, instead of a filesystem-events library.
- `audio/capture.py`: SoundCard (pure Python over WASAPI through cffi) instead of
  PyAudioWPatch. Windows delivers 16 kHz mono directly; the loopback delivers silence
  while nothing plays, so the stream clock never stalls. `pyproject.toml` `audio` extra
  now installs `soundcard`.
Still x64-only: faster-whisper (ctranslate2). Next step: a speech-to-text backend on ONNX
Runtime, which has ARM64 wheels and the QNN (NPU) provider.

**Measured: loopback level vs the Windows volume slider** (speakers muted throughout, so
nothing was audible). On this laptop the loopback copy of the caller follows the volume
slider, but not mute. Voice detection still works at 2 % volume (peak -44 dBFS, VAD 0.99);
only at 0 % (-54 dBFS) does it miss, and then the user cannot hear the caller either. No
gain control needed. Muted + 100 % volume gives full-level loopback with no sound, which
is now how live tests run without disturbing anyone.

**Bugs found by live testing and fixed (test first, each seen failing):**
- *A user line could jump ahead of the caller.* A held user segment was released once the
  caller's audio was processed past its end, even while the caller was mid-sentence in
  speech that had begun before the user stopped. Room speech on the mic (12 s, 13.5 s to
  transcribe) then went to Whisper before the caller's "tell me the OTP", and the echo
  check ran without that caller sentence. The stream worker now publishes the start of
  speech in progress (`speech_start`), and a user segment waits for it.
- *Stream clock pushed ahead after sleep.* After the PC slept for 30 minutes mid-test,
  SoundCard handed over the whole gap as zeros at once (18,516 blocks). Counted as audio,
  that pushes the stream clock (and every later line) up to a minute ahead of the session
  clock. Digital silence arriving while the stream is already ahead is now dropped; real
  audio is never exactly zero, so no speech can be lost. (This was also the "hang" seen
  earlier: the machine suspended, not a deadlock.)

**Live end-to-end, re-measured** (synthetic English scam call, 14.6 s, full app path:
capture, VAD, Whisper small on CPU, engine, window; times from launching the player, which
takes about 1.5 s to start): all four caller sentences heard and tagged (Authority, Threat,
Isolation, OTP ask); **notice 12.6 s, warning 15.1 s, critical 22.2 s**, about 6 s after
the OTP sentence ends. The earlier "critical 35 s" was partly a measurement error: the
script sampled the level only once, 20 s after playback ended.

Gates: ruff, ruff format, mypy strict, 630 tests passing.

### 2026-09-23 - Review fixes, part 2: speech-to-text on ONNX Runtime (runs on ARM64)

The last x64-only piece of live protection was faster-whisper (CTranslate2 has no Windows
ARM64 build). Whisper now also runs on ONNX Runtime, which has ARM64 wheels and the QNN
provider for the Snapdragon NPU, and that backend is the default.

- `asr/features.py`: Whisper's log-mel input (80 bands x 3000 frames) in plain numpy; matches
  the reference implementation to within 0.001.
- `asr/whisper_onnx.py`: `WhisperOnnx`, the Hugging Face ONNX export of Whisper
  (`onnx-community/whisper-small`, int8 encoder 92 MB + decoder 157 MB) with a key/value
  cache; greedy decoding. The first decoder step gives both the language and the
  no-speech probability, so detecting the language costs nothing extra. Guards: special
  tokens and non-speech symbols never produced, at most 8 tokens per second of audio,
  repetitive output (compression ratio > 2.4) dropped, "Urdu" re-run as Hindi.
- `asr/loader.py`: `asr.backend: onnx | ctranslate2` (default `onnx`) picks the engine for
  live mode and `chaukas setup`; `--asr-backend` on `run` and `setup`. Asking for
  ctranslate2 where faster-whisper is missing says to use onnx.
- Voice detection no longer depends on faster-whisper: `chaukas setup` downloads the Silero
  VAD model into `%LOCALAPPDATA%\Chaukas\models` (or `CHAUKAS_MODELS`) from a pinned
  release tag and refuses it unless the SHA-256 matches. Model files are still never
  committed.
- `pyproject.toml`: the `asr` extra is onnxruntime + tokenizers + huggingface_hub (all have
  ARM64 wheels), with faster-whisper kept as the optional second backend on x64.

**Measured, same 48 synthetic clips (4 voices/speeds, 24 scam + 24 innocent, 143 s),
Whisper small int8, greedy, 8 threads, i7-1360P:**

| Backend | Language | Key word heard | Invented | WER | Per clip |
|---|---|---|---|---|---|
| faster-whisper | detected | 24/24 | 0/24 | 1.4 % | 4578 ms |
| faster-whisper | hinted | 24/24 | 0/24 | 1.4 % | 2242 ms |
| ONNX Runtime | detected | 24/24 | 0/24 | 1.4 % | 2060 ms |
| ONNX Runtime | hinted | 24/24 | 0/24 | 1.4 % | 2117 ms |

Same accuracy; with language detection ONNX is 2.2x faster.

**Live end-to-end on the ONNX backend** (same synthetic call, silent loopback method):
all four caller sentences heard and tagged; notice 10.1 s, warning 13.4 s, **critical
16.9 s**, about 1 s after the OTP sentence ends (faster-whisper run earlier today: 12.6 /
15.1 / 22.2 s; that run also had room speech on the mic, this one had none, so not all of
the difference is the backend).

Not measured yet: the ONNX backend on an actual Snapdragon laptop (CPU or NPU), and
Hinglish accuracy.

Gates: ruff, ruff format, mypy strict, 650 tests passing, none skipped on this PC.
