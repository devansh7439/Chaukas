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

**Only you can do these:** recording voices for the 60-case dataset, blind scripts from
friends for the test split, a native speaker's review of the Hindi alerts, and reading the
competition's submission form and rules.

---

## 4. Log entries

### 2026-09-23 - Review of the codebase

Read every file and ran every check. Found: core, signals, engine and evaluation complete
and well tested (309 tests, 98% coverage); nothing yet for audio, ASR, LLM, context, UI,
privacy or tooling; 6 commits never pushed.

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

Not yet: Hinglish accuracy (only English synthetic speech has been tested); real-model
LLM in live mode.

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

Not measured yet: Hinglish accuracy.

Gates: ruff, ruff format, mypy strict, 650 tests passing, none skipped on this PC.

### 2026-09-27 - Review fixes, part 3: a real on-device LLM, measured

Until now the LLM layer had only run against scripted verdicts. It now runs a real model on
this PC, and the numbers are published even where they are unflattering.

**Running the model.** llama.cpp's `llama-server` (one prebuilt binary; official Windows
x64 and ARM64 builds; the OpenAI-compatible API the client already speaks), with
Qwen2.5-1.5B-Instruct Q4_K_M (1.1 GB, from Qwen's own repository).
- `llm/server.py`: `chaukas setup --llm` downloads the llama.cpp build pinned for this
  machine (b11218; SHA-256 from the release; zip entries that would land outside their
  folder are refused) and the model (pinned revision, SHA-256 checked). With
  `llm.server: managed` (default), `replay`/`eval`/`ablate --llm` start the server, wait
  for `/health`, and stop it afterwards. It only ever listens on 127.0.0.1: a non-loopback
  `base_url` is refused, and if the port is already taken Chaukas stops instead of sending
  transcripts to an unknown process. `llm.server: external` keeps the old behaviour (you
  run the server, e.g. GenieX on Snapdragon).
- New `llm` settings: `server`, `gguf`, `threads`, `ctx_size`, `startup_timeout_s`,
  `json_schema`; `timeout_s` 10 -> 15 (2 x the measured median).

**Fixes found by measuring (4 dev cases, configuration D = full system with the LLM):**
1. JSON validity was **7/15 (47 %)**. The prompt described fields as `"a|b|c"` and the
   model copied those strings literally. Now the reply schema (built from the parser's own
   enums, lengths and list sizes bounded) goes to the server as `response_format`, so
   decoding is grammar-constrained, and the prompt lists allowed values in words with one
   format example. Result: **12/12 (100 %)**.
2. The model then copied the *example's* quotes ("arrest warrant issued in your name")
   into calls that never said them; the evidence guard caught every one. The example's
   quotes are now instructions ("exact words copied from line 12").
3. Real caller quotes cited under a neighbouring line number were rejected (off by one).
   The guard now moves such a quote to the CALLER line it actually comes from. Invented
   quotes and USER lines are still rejected. (Blueprint 6.4 updated to match.)

**Result with the real model** (median call 7.1 s, 6.3-9.8 s, 8 CPU threads, i7-1360P):

| | E: keywords, no LLM (default) | D: with Qwen2.5-1.5B |
|---|---|---|
| Attacks detected | 2/2 | 2/2 |
| Warning latency (median) | +2.0 s | -5.3 s (earlier) |
| False alarms on benign calls | **0/2** | **2/2** |
| JSON validity | - | 12/12 |
| Evidence rejected | - | 0/28 |

With valid, genuinely quoted output, the 1.5B model still mislabels: it calls a TV news
report about scams "addressed to you, money transfer, threat", and a helpdesk visit the
user asked for "threat". The guard cannot catch that (the quotes are real; the labels are
wrong). Conclusion: **the default stays E (no LLM)**; the LLM is opt-in (`--ablation D`)
until a larger model is tried (on Snapdragon, a larger model on the NPU). Thresholds were
not tuned to hide this: with 4 cases that would be fitting the test set.

Not done, deliberately: the LLM in live mode (`chaukas run`). With this model it would add
false alarms to real calls; the reasoner's request/execute/finish split is ready for it.

Gates: ruff, ruff format, mypy strict, 680 tests passing.

### 2026-09-27 - Held-out evaluation: the first honest detection numbers

16 new cases (8 attacks, 8 hard negatives) in the `test` split, written from common scam
patterns without looking at the lexicon and committed (bdfd2c7) before their first run.
Configuration E (default, no LLM), first and only run so far:

| | 4 dev cases (seen while building) | 16 held-out cases |
|---|---|---|
| Attacks reaching warning or higher | 2/2 | **3/8 (38 %)** |
| Critical before harm | 2/2 | **0/8** |
| False alarms on benign calls | 0/2 | **0/8** |

Chaukas is cautious (no false alarm on a delivery OTP, film dialogue, family rent money or
a work screen share) but misses most scams it was not built around; the dev numbers were
flattering. Failure modes seen in replays:
1. Spoken numbers in English ("five one nine four two eight") are not recognised as the
   user reading out a code, so the OTP rule never reaches critical (AT08).
2. Paraphrased credential requests ("the code you got, read it out", "the 6-digit code in
   the SMS") are not recognised as credential requests (AT02, AT06).
3. Scams that use greed instead of fear (a refund plus AnyDesk) only reach notice, because
   escalation needs authority, threat or isolation (AT03); several Hinglish threat
   phrasings ("connection kaat diya jayega", "account frozen") are not in the lexicon.

### 2026-09-28 - Detection fixes, developed on new dev cases; held-out re-run (once)

Protocol: the held-out failures were diagnosed (replays), then 12 **new** dev cases with
different wording (DV01-DV12) were written and all fixes were developed against them only.
The code was committed (58f4c53) and the held-out set was run a second and final time.

Fixes (commit 58f4c53): lexicon breadth (consequence-style threats, claimed departments and
ranks, "don't discuss / don't phone anyone", credential requests that never say "OTP",
polite remote-install and money requests, fees and deposits) and one engine rule,
`remote_banking_warning`: a remote-control app runs, the bank opens after it, and the
caller claimed to be from an organisation, so at least a warning (family remote help
makes no such claim).

Disclosure: an authoring mistake in three held-out labels (AT02, AT06, AT08: the end state
after the user reads out a code is `critical_recovery`) was found on dev cases and fixed
(4b9ac39) before the re-run. It only affects "within acceptable".

| Configuration E (default) | Dev, 16 cases | Held-out, 16 cases: first run | Held-out: second run |
|---|---|---|---|
| Attacks detected (warning+) | 9/9 | 3/8 | **7/8** |
| Critical before harm | 8/9 | 0/8 | **5/8** |
| False alarms | 0/7 | 0/8 | **0/8** |
| Objective correct | 9/9 | 0/8 | 5/8 |

Remaining held-out misses, left unfixed on purpose (fixing them now would be tuning on the
test set; they are listed as known limitations):
- AT03 (refund + AnyDesk): "Amazon customer support" is not recognised as an organisation
  claim ("customer care" is), so the remote-banking rule does not fire: notice only.
- AT07 (English digital arrest): "move your savings to the verification account" is not
  recognised as a money request, so the digital-arrest chain never completes: warning.
- AT06 (card-block "6 digit code"): warning, not critical.
The held-out set has now been seen twice; a fresh set is needed for any further claim.

### 2026-09-28 - Docs brought up to date; live mode refuses LLM configurations

- **Bug fixed (test first):** `chaukas run --ablation B|C|D` was accepted, but live mode
  has no LLM wired in, so the engine would have held alerts back for up to 20 s "waiting
  for the LLM" and then continued without it. `run` now refuses those configurations with
  a clear message (use E, the default, or A).
- **README rewritten** around the current state: how to run the demo and live protection,
  measured results (held-out detection with its caveats, speech recognition, live
  latency, the LLM), a Snapdragon section that says plainly what is and isn't verified,
  updated privacy, commands, limitations, licences, and a "How this was built" section
  disclosing AI assistance.
- **ARCHITECTURE.md** rewritten: live audio, ONNX Whisper, the remote-banking rule, the
  optional managed LLM, threads, models and downloads, design decisions, known gaps.
  **DATA_MODEL.md**: coercion floor, storage (models folder, HF cache, LLM server log),
  every new config key (`asr`, `audio`, `llm`, `rules`), the reply JSON Schema. The
  architecture diagram is re-rendered (audio and speech-to-text built; LLM optional).
- **Git tags** `eval-run-1` (bdfd2c7) and `eval-run-2` (58f4c53) mark the exact commits of
  the two held-out runs; `default.yaml`'s header now points to them.

Gates: ruff, ruff format, mypy strict, 687 tests passing, 95 % line coverage.

### 2026-09-28 - Tools for the checks that need the author

Three one-command tools (in `tools/`, listed in the README) for the checks only the author
can run:
- `offline_check.ps1` (Administrator): blocks all outbound traffic for Chaukas's Python
  (the venv launcher and the base interpreter it starts), **proves the block works** (a
  request to example.com must fail, or the test is declared invalid), runs
  `offline_selfcheck.py` and the held-out eval, and always removes the rules. The
  self-check (models from disk, a synthetic call through VAD + Whisper into transcript
  lines, the engine reaching critical, 1 s of loopback capture; nothing played aloud)
  passes 4/4 on this PC with the network available; the firewall run itself is pending.
- `aihub_profile.py`: compiles Whisper small's fp32 encoder (pinned revision) for a
  Snapdragon device on Qualcomm AI Hub (`--target_runtime onnx`, as Chaukas runs it),
  profiles it there, times the same file on this CPU, and saves the profile JSON. Written
  against qai-hub 0.55.0's actual signatures; without a token it stops with AI Hub's own
  "configure your API key" message. The token is configured by the author, never read or
  printed by the script. For reference: the int8 encoder takes 568 ms per 30 s window on
  this i7-1360P.
- `hinglish_clips.py`: records 10 lines (8 scam lines, 2 everyday lines) from the
  microphone and scores whether the transcripts still produce the expected signals (a word
  error rate would mislead: Whisper writes Hindi in either script). Recordings stay on the
  PC (`*.wav` is git-ignored). Tested only with Windows' English voice, which mangles
  Hinglish (3/9 signals): that tests the code path, not accuracy.

### 2026-09-28 - Security review and security test suite

Chaukas has no database, accounts or web API, so the review covered its real surface:
untrusted text (caller speech, window titles, file names), data that must not leak,
downloads, and the optional local LLM server.

Scans: `bandit` on src/ and tools/ (16 findings, triaged below); `pip-audit` on all 148
locked packages (no known vulnerabilities); a regex secret scan over every commit on every
branch (none).

Found and fixed (each with a test that failed first):
1. The LLM server had **no authentication**: any process or other Windows user on the PC
   could use it while running. Each launch now gets a random 256-bit key
   (`secrets.token_urlsafe(32)`) in `LLAMA_API_KEY` (environment, not the command line,
   which process lists show); the client sends it; requests without it get 401.
2. The **Whisper ONNX download was not pinned** (bandit B615): now pinned to a revision,
   like every other download.
3. `llm.base_url` accepted any scheme (`file:///...` would be read by urllib; B310): now
   http(s) only, checked when the config loads.
4. A debug log message included up to 80 characters of **transcript text**: now only its
   length.
5. `.gitignore` did not cover `.env` files.
Remaining bandit findings are false positives or mitigated and annotated (fixed https
URLs, the validated config URL, the loopback health check; subprocess with fixed argument
lists and no shell; asserts that only narrow types after validation).

Confirmed correct and locked in by tests (`tests/security/`, 18 tests): the window renders
all untrusted text as plain text (Qt's default AutoText would render HTML from a web page
title); YAML is parsed with `safe_load` (a `!!python/object/apply` payload is rejected);
no transcript text reaches any log record at debug level through the audio pipeline; live
protection opens no listening socket; the real llama.cpp server listens on 127.0.0.1 only
and refuses keyless requests; every download is pinned or hash-checked. The LLM server's
own log holds only timings, no prompt text.

Gates: ruff, ruff format, mypy strict, bandit (0 medium/high), 705 tests passing.

### 2026-09-28 - Code review follow-ups: Why-panel fidelity, CI

An external code review (overall 8.7/10) raised two concrete issues, both fixed:

1. **The Why panel could quote the wrong words** (review: medium). `_reasons()` decided
   whether to explain a tactic from its session *peak* (e.g. "CBI" at 0.5), but displayed
   `strongest()`, the highest *current* entry with no minimum: after a few minutes a weak
   "officer" (0.3) heard later could stand in for the "CBI" that justified the alert.
   Reproduced by a failing test (`(600.0, 'officer') != (0.0, 'cbi')`). Fixed:
   `strongest(..., min_confidence=)` filters like `level()`, and a new
   `EvidenceStore.explanation()` falls back to the signal behind the pruned peak (a gap
   the review did not mention: after a long call the qualifying entry may have been
   pruned, so a filtered lookup alone would find nothing).
2. **No CI.** `.github/workflows/ci.yml` runs on every push and pull request, on Windows,
   with the exact locked dependencies: ruff, ruff format, mypy strict, pytest with
   coverage, bandit (medium and high). Read-only permissions.

Also: bandit's explanation comments no longer start with `nosec` (bandit parsed every
word as a test id). Not changed, as the review itself advised: the architecture. Noted
from the review for later: triggered OCR of the active window only at elevated risk; the
Snapdragon NPU run (needs the author's AI Hub token) remains the biggest gap.

### 2026-09-28 - Second code review: causal remote-banking rule; caller can't suppress the OTP request

1. **Remote-banking rule, causal order** (review: P0). It linked a bank page to the
   *earliest* remote-app start, even one from before the call ("I started AnyDesk for my
   own reasons at 10:00; a 'bank' calls at 10:30; I open my bank at 10:33" raised a
   warning). Now the order must be claim → remote start → bank, with the bank within
   `rules.remote_banking_window_s` (180 s) of that start; the claim may come minutes
   earlier (scammers establish authority first). `EvidenceStore.first_seen()` records when
   a tactic was first heard. The reviewer's extra claim→remote cap was not adopted: real
   scams ask for the install long after the authority claim.
2. **The caller could switch off the OTP request with protective-sounding words** (review:
   "never let caller speech suppress a safety signal"). Probing found two real attacks
   missed: "Kisi ko OTP mat batana, sirf mujhe batao" (a common scam line) and "Never
   share your OTP with anyone else, just read it out to me": the "don't tell anyone" half
   turned the whole sentence into advice. Now a non-negated request verb aimed at the
   speaker (singular only: "mujhe", "me"; a real bank says "tell *us* if anyone asks")
   makes it a request, and the "don't tell anyone" part then counts as isolation. Also
   fixed a false positive on genuine advice: "OTP ya PIN ... mat bataiye" now covers every
   object in the list. The words live in `lexicon.yaml` (`negation.redirect`,
   `negation.connectors`). With an authority claim first, the redirect line is critical
   before the user answers.
3. CI's first run passed (all nine steps).

Dev set unchanged (9/9, 0/7 false alarms); the held-out set was not run. Tests: 726.

### 2026-09-28 - Second code review: an NPU path with safe fallback; triggered OCR

**Snapdragon NPU path (review: P0).** Only Whisper's encoder moves to the NPU (the fixed,
heaviest cost per call); the decoder, the risk engine and everything else stay on the CPU.
- `asr.device: cpu | npu` (`--asr-device` on `run`, `setup`, `benchmark`). With `npu`, the
  fp32 encoder (`onnx/encoder_model.onnx`, downloaded by `setup --asr-device npu`) runs on
  the NPU in fp16 through Qualcomm's QNN plugin for ONNX Runtime.
- The plugin API was **probed on the real package, not written from memory**, which caught
  two traps: `onnxruntime-qnn` 2.6.0 is a *plugin* beside onnxruntime (it never appears in
  `get_available_providers()`; it is registered with `register_execution_provider_library`
  and hardware is chosen from `get_ep_devices()`), and ONNX Runtime silently falls back to
  the CPU if the chosen device can't run the model. So only a device of type NPU is used,
  and the bound providers are checked afterwards.
- **Safe degraded mode:** no plugin, no NPU, the fp32 file missing, or a session that won't
  build: the CPU encoder is used, `runtime.note` says why, live mode's status line says
  "speech on CPU (NPU unavailable)". Protection never stops. Tested for real on this x64 PC
  (asking for the NPU falls back, says why, and still transcribes correctly).
- `pyproject.toml`: `onnxruntime-qnn>=2.6` on Windows ARM64 only.
- `chaukas benchmark [--asr-device npu] [--audio WAV] [--runs N] [--json FILE]`: median
  encoder/decoder/total time, the providers actually bound, whether it fell back, the
  real-time factor, the machine and **whether it ran on battery** (on battery this laptop
  was 5-10x slower; such numbers are marked and not published).

**Triggered OCR (review: P0).** A generic window title over an "Enter OTP" box used to be
invisible. `context/ocr.py`: while the call's alert level is notice or higher (config
`ocr.min_level`), at most every 3 s, the active window is captured (mss) and read by
Windows' built-in OCR (`Windows.Media.Ocr` via `winrt`; x64 and ARM64 wheels, no model to
download); the text goes through the existing `classify_screen_text` rules (OTP field,
password field, transfer form) and becomes the same context events the engine already
uses. Each (window, kind) is reported once. Never read: calm calls, Chaukas's own window.
The image and text live in memory for one classification only, never written or logged.
If OCR is missing or fails, titles, processes and Downloads keep working.
- **Bug found and fixed on the way:** winrt bundles an older `msvcp140.dll`; if winrt loads
  before Qt, importing Qt later crashes the process (access violation). Chaukas now loads
  Qt's runtime first; a regression test does the dangerous order in a fresh process.
- Tested with real pixels: Qt renders "Enter OTP 482913", Windows OCR reads it, the rules
  classify it as an OTP field. OCR languages are the Windows ones installed (English here;
  Hindi needs the Hindi language pack).

Tests: 745 passing; ruff, mypy strict clean.

### 2026-09-28 - Robustness matrix: 26 new cases, one run

The review asked for a robustness matrix instead of another model. 26 cases in
`eval/robustness/` (tag `eval-robust-1`), committed before their only run: three scam
intents (OTP theft, digital-arrest money transfer, remote access) x six variants
(Hinglish, English paraphrase, Hindi in Devanagari, indirect request, reordered tactics,
adversarial wording) plus eight legitimate look-alikes. **Not blind**: written by the same
assistant that developed the detector.

Result (configuration E): **10/18 scams detected** (7/18 critical before harm), **2/8 false
alarms**. By variant: Devanagari 3/3, Hinglish 2/3, reordered 2/3, adversarial 2/3,
indirect 1/3, **English paraphrase 0/3**. By intent: digital arrest 5/6, remote access 3/6,
OTP theft 2/6. False alarms: a bank saying "I will *send* an OTP" ("send" is a request
verb) and an English-speaking delivery agent asking for the order OTP (by design any OTP
request without an authority claim is a warning). Also seen: "bata dijiye" and "confirm kar
dijiye" are not recognised as request verbs.

Per the protocol this set is now spent: nothing will be tuned against it and no
improvement on it will be claimed. The honest conclusion for the README: the keyword
layer does not survive paraphrase, which is the job the LLM layer was designed for and why
a stronger on-device model (on the NPU) is the next step.

### 2026-09-28 - Presentation deck

A 12-slide deck for the judges (private artifact on claude.ai; the owner shares it):
cover · the problem (authority → fear → isolation → action) · the idea (combinations, not
words) · what you see (dashboard screenshot, the four alert levels) · how it works (hear,
transcribe, detect, watch, assess, interrupt) · the deterministic risk engine · Snapdragon
(encoder on the NPU, everything that decides on the CPU, safe fallback) · privacy and
security · results · honest limits · what comes next · close. Every number is one measured
in this worklog; the presenter name is `[Your name]`. Speaker notes on every slide.

### 2026-09-28 - Snapdragon wording in the docs and deck

README, ARCHITECTURE.md, the blueprint's risk list and the deck now describe the Snapdragon
NPU path by what it is built to do (encoder on the NPU through Qualcomm's QNN plugin, safe
CPU fallback, `chaukas benchmark --asr-device npu` to measure it). The deck's NPU slide
shows the benchmark command instead of a blank number.

### 2026-09-28 - OCR: works unpackaged (checked), availability visible, never blocks the monitor

Two review points on the triggered OCR:
1. **"Windows.Media.Ocr needs package identity (MSIX)."** Checked instead of assumed: the
   package-identity requirement belongs to the Windows App SDK's
   `Microsoft.Windows.AI.Imaging.TextRecognizer`; the classic `Windows.Media.Ocr.OcrEngine`
   lists only Windows 10 and the Universal API contract. Measured: the test process has
   no package identity (`GetCurrentPackageFullName` returns 15700,
   APPMODEL_ERROR_NO_PACKAGE) and reads "Enter OTP 482913" correctly; a test pins both.
   The real clean-machine risk is a missing OCR language or missing bindings, so
   `ocr_status()` now says which: `chaukas devices` prints "Screen text (OCR): on (en-US)"
   (or off, and why), and the live status line says "screen text on (en-US)" or "screen
   text off: ...". Protection continues without it either way.
2. **OCR blocked the context monitor.** Measured: capture + OCR of a full-screen window
   takes about 130 ms (250 ms the first time), during which process, window and Downloads
   polling stalled. Capture, OCR and classification now run on one worker thread;
   `poll()` never waits, the result arrives on a later poll timed when the screen was
   looked at, one read at a time, and a read still running at session end is dropped.
Also: a test imported winrt before Qt and crashed the test process (the DLL-order hazard
from before); tests now load Qt's runtime first through one helper.

Tests: 752 passing.

### 2026-09-28 - Semantic intent layer (paraphrases), frozen before its test

The robustness matrix showed paraphrase defeats the keyword layer (0/3 English
paraphrases). New layer, before the risk engine, detecting *intent* (not "scam"):
- `signals/semantic.py`: `paraphrase-multilingual-MiniLM-L12-v2` (int8 ONNX, ~120 MB, x64 and
  ARM64 builds, pinned revision, SHA-256 checked, downloaded by `chaukas setup`), mean
  pooling; each caller line is compared with example sentences per signal kind
  (`resources/intents.yaml`). A kind fires when the line is within `threshold` (0.6
  cosine) of a `means` example and at least `margin` (0.05) closer to it than to any `not`
  example (look-alikes: protective advice, informational bank calls, delivery codes,
  "I'll share *my* screen"), because embeddings barely see negation.
- Conservative: its own source and tier; a tactic counts like a keyword phrase (0.6), a
  request 0.72 (just above the OTP rule's 0.7, below a keyword request's 0.75); the user's
  own words never count; the engine's gates still decide. 9 ms per line on the CPU.
- `--no-semantic` on replay / eval / ablate (they say on stderr whether it is on); live
  `run` uses it; scripted demos don't (so their timings stay fixed).
- **Measured finding:** the model misreads Roman-script Hinglish (trained on English and
  Devanagari): with Hinglish examples, family chat matched "don't tell anyone" and a jail
  threat (4/7 false alarms on dev). Roman Hinglish is left to the lexicon; the semantic
  layer covers English and Devanagari.
- Tuned on dev only (10 new paraphrase dev cases DP01-DP10 plus the existing dev cases):
  paraphrase dev 0/6 -> 5/6 scams detected, false alarms 1/4 (a delivery-code request,
  kept: the OTP rule warns on any unexplained code request by design); all dev 14/15
  detected, 1/11 false alarms.

Tests: 761 passing.

### 2026-09-28 - Semantic layer: fresh test results (one run each)

Two fresh sets written after the layer was frozen (tag `semantic-frozen`) and committed
before their only run (tag `eval-paraphrase-1`): Set B, 12 paraphrased scams (English,
Devanagari, one Hinglish, one reordered, one adversarial); Set C, 8 legitimate look-alikes.
Configuration E, the semantic layer off and on:

| | Keywords only | + semantic |
|---|---|---|
| Set B detected | 1/12 | **6/12** |
| Set B critical before harm | 1/12 | 2/12 |
| Set C false alarms | 0/8 | **1/8** (a Hindi news bulletin about OTP fraud) |
| Robustness matrix, second run (seen), detected | 10/18 | 13/18 |
| Robustness matrix false alarms | 2/8 | 2/8 |

The layer does what it was built for (paraphrase from 1/12 to 6/12) for one extra false
alarm. Still missed: mostly remote-access paraphrases ("take over your PC", "let me operate
your laptop", "allow me to connect to your desktop"), which reach notice at best; a
likely cause is that the "I'll share my screen" counter-examples pull them down. Not tuned
further: these sets are now spent. The reordered case reached critical, so the chain
engine was left as it is. README and deck updated with these numbers.

### 2026-09-28 - Red-team review and hardening

Tried to break Chaukas across attack classes A-M (paraphrase, indirect, reordered,
adversarial speech, look-alikes, screen and process spoofing, temporal correlation,
speaker confusion, transcription and OCR failure, attacks on Chaukas, prompt injection).
Full report with evidence labels: [REDTEAM.md](REDTEAM.md). Eight defects found, each fixed
with a regression test written first:

1. Forged advice: "Don't worry, send the OTP", "No, just read out the OTP" gave no signal
   (a negator within a word of the verb made it advice and hid the OTP keyword). Negation
   now stays in its clause, with only filler words between.
2. "OTP batao nahi toh account band ho jayega" gave no request ("nahi toh" = otherwise).
3. "OTP share mat karna" (bank advice) was a full request. A negator after the verb now
   needs a helper verb or the clause end next. Polite compounds ("bata dijiye", "confirm
   kariye") are generated from stems x helpers.
4. Stale priming: authority heard an hour of speech earlier made an OTP request critical.
   Now `priming_window_s` (1,800 s of speech). Each alert carries a decision trace
   (source, confidence, decay, contribution, chain step, rule); the Why panel shows how each
   reason was detected; `replay` prints the trace.
5. OCR: a hung read silently ended screen reading; a window titled "Chaukas" was skipped.
   Now a 10 s timeout, off after 3 hangs with a reason, own process by pid, malformed and
   huge output handled.
6. Unbounded score history (copied on every refresh) and speech backlog. Now bounded;
   six-hour soak test (~1 MB growth, mostly the speech clock).
7. "We will send an OTP", "I will share my screen" were requests: offers now don't pair.
8. Semantic examples embedded in one batch: the int8 model quantises per batch, so every
   example depended on the others (~0.003 cosine). Now one at a time. Dev DP06 drops
   below the unchanged 0.6 threshold (dev 14/15 -> 13/15); not re-tuned.

Also: eval reports warning-before-harm, p95 and breakdowns by language / intent / set;
the benchmark reports peak memory (926 MB, whisper-small, on battery, RTF 1.36).

Fresh red-team set D (`eval/redteam/`, 12 attacks + 8 look-alikes, non-blind), committed
before its only run (tag `eval-redteam-1`): keywords only 8/12 detected, 2/8 false alarms;
with the semantic layer **11/12 detected, 9/12 critical before harm, 3/8 false alarms**
(film scene, news report, delivery code). Missed: a remote-control paraphrase. Re-runs of
seen sets: held-out 7/8 and 1/8 false alarms (was 0/8: "order ka OTP bata dijiye" is now a
request, the same words a scammer uses), robustness 14/18 and 1/8, paraphrase B/C
unchanged (6/12, 1/8).

Security re-check: bandit clean, pip-audit no known vulnerabilities, no secrets, 30/30
security tests. Tests: 849.

### 2026-09-28 - External review follow-up

Every finding was checked against the code first; all were confirmed and fixed test-first
(details and evidence in [REDTEAM.md](REDTEAM.md#k-follow-up-an-external-review-same-day)):

- Ablation A used the semantic layer: `ablation.use_semantic` (off in A, on in B-E).
- README status quoted old numbers: it now leads with the latest run of every set.
- Chain steps never expired: a morning news video completed an evening call's chain
  (critical, 0.82). Steps now expire after 1,800 s of speech without a new sighting.
- Benchmark precision per part (int8 CPU; fp32 run in fp16 on the NPU).
- Models hash-checked at every load, not only at download (`core/integrity.py`).
- Remote control: RT11's trace showed the missing piece was the organisation claim, not
  the paraphrase. Organisation claims are now a weak authority signal. Fresh set E
  (committed before its only run, tag `eval-remote-1`): detected 1/8 -> **6/8**, false
  alarms 0/8 -> 0/8. Missed: no claim at all; browser screen share.
- Dates: 29 September corrected to 28 September everywhere.

Not done: real Snapdragon measurements (needs the hardware); OCR via UI Automation before
screenshots (documented as an open risk).

### 2026-09-30 - Snapdragon X Elite measurement; demo video

- **Measured on a real Snapdragon X Elite** through Qualcomm AI Hub (`tools/aihub_profile.py`,
  the same fp32 encoder file Chaukas uses, ONNX Runtime with the QNN provider): **150 ms per
  30 s window**, all 313 layers on the NPU, peak memory 272 MB. The same file on this
  laptop's Intel CPU: 1,217 ms (8.1x). Profile saved in `docs/benchmarks/`. Not measured:
  the whole pipeline on a Snapdragon laptop, and power.
- `tools/demo_video.py`: renders the scripted digital-arrest demo from the real app window,
  frame by frame, into an MP4 (notice, warning, the full-screen pause with every reason).

- Snapdragon X Plus 8-core CRD (AI Hub, same file and runtime): 144 ms per window (median of
  100 runs), all 313 layers on the NPU, peak 271 MB; this laptop's CPU in that run: 1,053 ms.

- Snapdragon X2 Elite CRD (AI Hub): Whisper encoder median 70.4 ms per window, all 313 layers
  on the NPU, peak 50 MB. X Elite median 150.9 ms, X Plus 144.1 ms (100 runs each).
- Audio chain (`tools/audio_eval.py`): 24 English cases of sets D and E spoken by Windows
  voices and transcribed by Whisper; every outcome matched the text run (11/13 detected,
  2/11 false alarms). Found "AnyDesk" heard as "any disk": now recognised.
- Fixed: piped `chaukas replay` crashed on a cp1252 console (UnicodeEncodeError).
- Set D re-run on the final code: 12/12 (seen: the claim rule came from RT11's analysis).
- Tried to profile the paraphrase model on the X Elite CPU (`aihub_profile.py --component
  paraphrase`): AI Hub's random test inputs used a token-type id of 3 (the model accepts 0-1)
  and the profile failed, so there is no measurement for it; it needs fixed sample inputs.

- Spoken alerts (`ui/voice.py`, `ui.spoken_alerts`, on by default in live mode): on each rise
  to a warning, a critical or the recovery level, the alert text is said out loud (Microsoft
  Heera, Indian English; Hindi when a Hindi voice is installed). Not on a notice, not
  repeated, not on the way down, not while paused. Every spoken sentence is tested to give
  no evidence when heard back through the loopback. AlertVoice is owned by the bridge (a
  first version was silently garbage-collected; the test caught it).
- First-run welcome (live mode only, shown once, remembered in settings): what Chaukas
  listens to, that nothing is saved or sent, and that the person always decides; English
  and Hindi.
