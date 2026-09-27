# Chaukas (चौकस)

**An on-device AI guardian against social engineering on Windows PCs.**

> Chaukas doesn't ask whether a word, website or app is dangerous. It asks whether someone
> is manipulating you into using it dangerously.

Chaukas (Hindi for "alert, watchful") listens to a call on your PC and watches what happens
on screen. When a caller claiming to be the police, the CBI, your bank or tech support
starts pressuring you towards sending money, installing remote-access software or reading
out an OTP, Chaukas interrupts, explains why, and lets you decide. Speech recognition and
everything else run on the PC. Free and open source (Apache-2.0), built for the
Snapdragon® AI Lab Build & Present Challenge.

![The Chaukas window during a simulated digital-arrest call](docs/images/dashboard.png)

> **Status (28 September 2026).** Live protection works end to end on a Windows PC: it
> hears a call (what the PC plays, and your microphone), transcribes it on the device with
> Whisper, watches the screen, and raises the alert. On 16 held-out test calls it caught
> 7 of 8 scams with no false alarm on 8 look-alike innocent calls; see [Results](#results)
> for exactly what that number does and doesn't mean. Every dependency installs on
> Windows on ARM64 (Snapdragon), but **Chaukas has not yet been run on a Snapdragon
> laptop**; see [Snapdragon](#snapdragon).

## Contents

- [Run it](#run-it)
- [The problem](#the-problem)
- [The idea: suspicious combinations](#the-idea-suspicious-combinations)
- [How it works](#how-it-works)
- [What you see](#what-you-see)
- [Results](#results)
- [Snapdragon](#snapdragon)
- [What works today](#what-works-today)
- [Privacy](#privacy)
- [Commands](#commands)
- [Development](#development)
- [Related work](#related-work)
- [Limitations](#limitations)
- [How this was built](#how-this-was-built)
- [Credits and licences](#credits-and-licences)

## Run it

You need Windows 10 or 11 and [uv](https://docs.astral.sh/uv/getting-started/installation/)
(it installs the right Python for you).

**A demo in 5 minutes** (no microphone, no call, no model downloads):

```powershell
git clone https://github.com/devansh7439/Chaukas.git
cd Chaukas
uv sync --extra ui --extra context
uv run chaukas ui --demo eval/cases/DA01.yaml
```

The window plays a simulated "digital arrest" call in real time:

| Time | What happens |
|---|---|
| 0-8 s | The caller claims to be from the CBI and mentions a money-laundering case |
| ~8 s | **Notice**: someone may be pressuring you |
| ~20 s | **Warning** after "kisi ko mat batana" (don't tell anyone): a side panel with the evidence |
| ~29 s | **Critical** when a (mock) bank transfer page opens: a full-screen pause card |

On the critical card, tick **I understand this warning** to unlock **Continue anyway**.
Nothing is ever blocked. `uv run chaukas ui` opens an empty session where you type lines
yourself: try `SBI bank se bol raha hoon, OTP batao`, then switch the speaker to **You**
and type `4 5 6 7`.

**Live protection on your own calls:**

```powershell
run.bat setup    # once: installs everything, downloads Whisper small (~250 MB) and the
                 # voice-detection model (1.2 MB), SHA-256 checked, and lists your devices
run.bat          # start protecting; leave it running during calls
```

Chaukas listens to what the PC plays (the other person in WhatsApp, Zoom, Teams, Meet,
etc.) and to your default microphone. Headphones give the cleanest result. `run.bat`
passes options through, e.g. `run.bat --language hi`.

## The problem

Social engineering doesn't hack the computer; it hacks the decision. A caller poses as an
official, frightens the victim ("your Aadhaar is linked to a money-laundering case"),
isolates them ("don't tell your family, stay on camera"), and steers them into doing the
harmful thing themselves: transferring money, installing AnyDesk, or reading out an OTP.
Antivirus sees nothing wrong, because every action is one the user chose to take.

## The idea: suspicious combinations

Chaukas doesn't flag suspicious words or suspicious actions. It flags **suspicious
combinations**.

| What Chaukas sees | Could be | Verdict |
|---|---|---|
| "CBI" + "arrest" | A news report | Not enough |
| Installing AnyDesk | Real IT support you asked for | Not enough |
| "CBI officer" + "don't tell anyone" + "install AnyDesk" | Social engineering | **Warn** |

It tracks three attack patterns, each a sequence of steps:

| Attack | Typical chain | What the attacker wants |
|---|---|---|
| Digital arrest | Fake authority → threat → isolation / surveillance → money request → bank page | Money |
| Remote access | Fake support → fear or a "refund" → install a remote tool → tool starts → bank opens | Control of the computer |
| Credential theft | Fake bank / authority → urgency → OTP / code request → the user reads it out | Account access |

## How it works

![Architecture](docs/images/architecture.png)

1. **Hear.** Two audio streams through WASAPI: what the PC plays (the caller) and the
   microphone (you). Silero voice detection cuts speech into sentences; the microphone's
   copy of the caller's voice (laptop speakers) is skipped before transcription.
2. **Transcribe.** Whisper small (int8) on ONNX Runtime, on the device. Each speaker's
   language is detected once and reused; a backlog is transcribed in one call.
3. **Detect.** Each line is normalised and scanned for tactics (authority, threat,
   urgency, isolation, surveillance, money / remote-access / credential requests) in
   English, romanised Hindi and Devanagari. Spoken numbers ("char saat do nau") count as
   digits. Protective advice ("we will never ask for your OTP") doesn't count.
4. **Watch the screen.** Remote-access tools starting, banking and transfer pages (by
   window title), and executables arriving in Downloads.
5. **Assess.** Evidence (which fades over minutes of speech, not silence) combines into a
   risk score, held back unless the screen and the attack pattern agree:
   `R = pressure × addressed-to-you × matching-action × attack-sequence`.
   Critical needs a coercive tactic, every required step of the attack, and matching screen
   activity; a caller asking for an OTP after claiming authority is critical immediately,
   before you answer.
6. **Interrupt, explain, let you decide.** Alerts escalate, every reason is shown with the
   moment it happened, and you choose what to do.

An optional **local LLM** (Qwen2.5-1.5B via llama.cpp) can be asked "what is the caller
trying to make the user do?"; every claim must quote the caller's actual words. It is
**off by default**, because on our tests it added false alarms (see [Results](#results)).

Details: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** (components, runtime flow, risk
engine, threads, design decisions) and **[docs/DATA_MODEL.md](docs/DATA_MODEL.md)**
(entity-relationship diagram, every data type and file schema). The design spec is
[Chaukas_BLUEPRINT.md](Chaukas_BLUEPRINT.md); every step, measurement and decision is in
[docs/WORKLOG.md](docs/WORKLOG.md).

## What you see

| Level | When | What Chaukas shows |
|---|---|---|
| Protected | Nothing suspicious | Dashboard: "You're protected." and a listening indicator |
| Notice | Some pressure | A small card in the corner |
| Warning | Pressure plus coercion (threat, isolation, surveillance), or a remote-control session followed by banking after an organisation claim | A side panel: what the caller seems to want, the evidence, safe next steps |
| Critical | The whole attack pattern, matched on screen | A full-screen pause card; "Continue anyway" unlocks after "I understand" |
| Act now | You read out a code after an OTP warning | Recovery card: call your bank on the number printed on your card |

The warning panel, the critical card and the Why page offer **Verify independently** (hang
up, call a number you found yourself), your **trusted contact** (shown large; Chaukas never
places calls) and the **cybercrime helpline 1930**.

## Results

All numbers below were measured on one Intel Core i7-1360P laptop (CPU only). All call
scripts are synthetic (written for this project, no real victims).

**Detection** (configuration E, the default: keywords + engine + screen, no LLM):

| | Held-out test, 16 cases, first run | Held-out, second run (after fixes) | Dev, 16 cases |
|---|---|---|---|
| Scams detected (warning or higher) | 3/8 | **7/8** | 9/9 |
| Critical before the harm happened | 0/8 | **5/8** | 8/9 |
| False alarms on innocent calls | 0/8 | **0/8** | 0/7 |

How to read this, honestly:
- The 16 held-out cases (8 scams, 8 look-alike innocent calls such as a delivery agent
  asking for the order OTP, a real bank fraud alert, family asking for rent money, a work
  screen share, film dialogue) were committed before their first run. The first run
  exposed three general gaps; the fixes were developed on **separate** dev cases only,
  then the held-out set was run once more. It has now been seen twice, so the second
  number is optimistic; a fresh set is needed for a clean claim.
- The samples are small: 7/8 has a 95 % confidence interval of 53-98 %.
- Remaining misses: a refund scam where "Amazon customer support" isn't recognised as an
  organisation claim (notice only), and two scams that reach warning but not critical.
- These are transcripts replayed through the engine. Live audio adds speech-recognition
  errors, measured only on synthetic English speech so far (below).

**Speech recognition** (Whisper small int8, greedy, 8 threads; 48 synthetic English clips
from 4 voices, 143 s):

| Backend | Key scam word heard | Key word invented | Word error rate | Time per clip, language auto-detected |
|---|---|---|---|---|
| ONNX Runtime (default; runs on ARM64) | 24/24 | 0/24 | 1.4 % | 2.1 s |
| faster-whisper (x64 only) | 24/24 | 0/24 | 1.4 % | 4.6 s |

**Live, end to end** (a synthetic English scam call, 14.6 s long, played through the
laptop and heard through the loopback): all four sentences transcribed and tagged;
notice 10 s, warning 13 s, **critical 17 s** after playback started, about 1 s after the
caller finished asking for the OTP.

**Local LLM** (Qwen2.5-1.5B-Instruct, 4-bit, llama.cpp on the CPU; 4 dev cases):
schema-constrained output made every reply valid JSON (12/12, was 7/15 without the
schema), median 7.1 s per call. But the 1.5B model mislabels innocent calls (a TV news
report about scams became "threat, money transfer"), giving **2/2 false alarms**, so the
LLM stays off by default. A larger model is the next thing to try.

## Snapdragon

Chaukas is built to run on Snapdragon-powered Windows on ARM64 PCs:

- Every Python dependency of live protection has a Windows ARM64 build or is pure Python:
  ONNX Runtime (with the QNN provider for the Snapdragon NPU), numpy, PySide6, psutil,
  tokenizers, SoundCard (WASAPI through cffi). x64-only libraries were replaced during the
  project: CTranslate2 → ONNX Runtime Whisper, soxr → a numpy resampler, PyAudioWPatch →
  SoundCard, watchdog → polling.
- The optional LLM server has an official llama.cpp Windows ARM64 build, which
  `chaukas setup --llm` downloads on ARM64 PCs.
- **Not yet done:** running Chaukas on a Snapdragon laptop, and running Whisper on the
  Snapdragon NPU (ONNX Runtime QNN / Qualcomm AI Hub). No Snapdragon measurement exists;
  none is claimed.

## What works today

| Part | Status |
|---|---|
| Live audio: two-stream WASAPI capture, voice detection, echo skip, sleep/wake handling | Built, tested, measured live |
| Speech-to-text: Whisper on ONNX Runtime (default) or faster-whisper, fully offline | Built, tested, measured |
| Keyword and request detection (English, romanised Hindi, Devanagari) | Built, tested |
| Risk engine: attack chains, gates, levels, OTP rules, remote-banking rule | Built, tested |
| Desktop monitor: remote tools, bank / transfer / OTP pages, downloads | Built, tested (real Windows calls) |
| The window: dashboard, alerts, Why / Privacy / Settings, English and Hindi | Built, tested |
| Evaluation: 32 cases (16 dev, 16 held-out), replay, metrics with confidence intervals, ablations A-E | Built |
| Optional local LLM (llama.cpp, managed by Chaukas; evidence guard; schema-constrained) | Built, measured; off by default, not wired into live mode |
| Running on a Snapdragon laptop; Whisper on the NPU | **Not done** |
| Tray icon, spoken alerts, onboarding | **Not built** |

Quality: 687 automated tests, 95 % line coverage, `ruff` and `mypy --strict` clean.

## Privacy

- **Nothing about the call is saved.** Audio, transcripts, evidence and risk states live in
  memory for the current session only: transcript lines older than 5 minutes are dropped,
  and the session ends after 30 minutes without speech or when you press End session.
  Chaukas has no database. See [docs/DATA_MODEL.md](docs/DATA_MODEL.md#storage).
- **Nothing is uploaded.** Speech-to-text runs on the PC and loads models from disk only.
  The optional LLM server is started by Chaukas and only ever listens on 127.0.0.1.
  By design, **only `chaukas setup` uses the network**, to download models (each checked
  by SHA-256).
- **Files written:** `%APPDATA%\Chaukas\settings.json` (language, trusted contact, one
  switch) and the downloaded models in `%LOCALAPPDATA%\Chaukas\models`.
- **You can see and control it.** A listening indicator is always visible, with Pause and
  End session one click away. Pause drops audio before any processing.
- **Optional:** hide Chaukas's alerts from screen sharing, so a remote "support agent"
  can't see the warning (off by default: it also hides them from your own recordings).
- Not yet verified: a firewall test proving Chaukas works with all network access blocked.
  Until it has been run, we don't claim "makes no network calls".

## Commands

```powershell
uv run chaukas run [--language hi] [--asr-model base]    # live protection
uv run chaukas setup [--llm]                             # download models (the only network use)
uv run chaukas devices                                   # which speaker / microphone it would use
uv run chaukas ui [--demo CASE] [--speed N]              # the window with a demo script
uv run chaukas replay eval/cases/DA01.yaml               # one case's alert timeline
uv run chaukas eval eval/cases --split test              # score the held-out cases
uv run chaukas ablate eval/cases                         # configurations A-E side by side
uv run chaukas check-config                              # print the merged configuration
```

Every command accepts `--config FILE.yaml` (repeatable) to override
[default.yaml](src/chaukas/resources/default.yaml). Ablations: **A** keywords only,
**B** + LLM, **C** + action gate, **D** full Chaukas with the LLM, **E** full without the
LLM (the default). Live mode refuses B-D until the LLM is wired into it.

**With the local LLM:** `uv run chaukas setup --llm` downloads llama.cpp (pinned build for
x64 or ARM64) and Qwen2.5-1.5B (1.1 GB); then add `--llm`:

```powershell
uv run chaukas eval eval/cases --ablation D --llm --llm-cache eval/cache/qwen
uv run chaukas eval eval/cases --ablation D --llm --llm-cache eval/cache/qwen --llm-offline
```

Chaukas starts the server, evaluates, and stops it. The first run records every answer
with its measured latency; `--llm-offline` replays them exactly with no model running. To
use a server you run yourself (e.g. GenieX on Snapdragon), set `llm.server: external` and
`llm.base_url`.

## Development

```powershell
uv sync --extra ui --extra context --extra audio --extra asr
uv run pytest                        # tests (headless: the window renders offscreen)
uv run ruff check .                  # lint
uv run ruff format --check .         # formatting
uv run mypy                          # strict type check
```

Python 3.12 (3.11 also supported). If `uv run pytest` fails with "uv trampoline failed to
canonicalize script path", run `uv sync --reinstall`.

```
src/chaukas/
  core/          data types, clocks, time windows, config, model paths
  audio/         WASAPI capture, resampler, voice detection, segmenter, echo guards, pipeline
  asr/           Whisper on ONNX Runtime (log-mel, decoding), faster-whisper, backend loader
  signals/       normaliser, Aho-Corasick lexicon, request fast path, digit rule
  engine/        evidence decay, attack chains, gates, levels, special rules
  llm/           trigger policy, prompt, client, reply schema, evidence guard, cache, server
  context/       process / window / Downloads watchers, Windows API readers
  evaluation/    case scripts, session pipeline, replay, metrics, ablations
  ui/            window: live session, services, presenter, Qt bridge, QML views
  resources/     default.yaml, lexicon.yaml, templates.yaml, context.yaml
eval/cases/      case scripts (YAML): dev and held-out test splits
docs/            ARCHITECTURE.md, DATA_MODEL.md, WORKLOG.md, diagrams, images
tests/           one folder per package
```

## Related work

| Product | What it does | How Chaukas differs |
|---|---|---|
| Google Scam Detection (Pixel; Samsung's Phone app) | On-device scam-pattern detection in phone calls | Phones only. Chaukas runs on the PC, understands Hindi / Hinglish, and links what is said to what happens on screen |
| Android screen-sharing warning (India) | Warns when an unknown caller shares the screen and a payment app opens | Action only, phone only. Chaukas combines the action with the conversation |
| Microsoft Edge scareware blocker | Detects full-screen tech-support scam web pages | Detects pages, not conversations. A scam that is all talk plus AnyDesk never shows a scam page |

## Limitations

- **Calls taken on a phone are not covered.** Chaukas hears the PC's audio and microphone.
- **It hears everything the PC plays.** A video about scams can raise a notice (film and
  news dialogue stayed at notice in our tests). It follows the default speaker and
  microphone chosen at start; switching devices mid-call needs a restart.
- **Volume:** detection works down to 2 % speaker volume on our laptop, not at 0 %.
- **Money sent from a phone** instead of the PC reaches warning at most, because the
  transfer never appears on screen.
- **Friction, not a wall.** Someone with remote control of the PC can close Chaukas, and a
  frightened person can click through warnings.
- **Coverage is keyword-based by default.** Scams phrased in ways the lexicon doesn't know
  are missed (see [Results](#results)); the LLM that would help is not good enough yet at
  1.5B parameters.
- **Languages:** English, Hindi and Hinglish. Speech recognition has been measured on
  synthetic English speech only; real Hinglish accuracy is unmeasured. The Hindi text
  still needs a native speaker's review.
- **Not yet run on Snapdragon** (see [Snapdragon](#snapdragon)).

## How this was built

Chaukas was written by its author ([@devansh7439](https://github.com/devansh7439)) with
extensive help from an AI coding assistant (Claude), which wrote much of the code, tests
and documentation under the author's direction and review. The evaluation cases are synthetic and were also written with AI assistance;
measurements were taken on the author's laptop and are reproducible with the commands
above. The full development log is in [docs/WORKLOG.md](docs/WORKLOG.md).

## Credits and licences

- Chaukas: [Apache License 2.0](LICENSE).
- Libraries: [PySide6](https://doc.qt.io/qtforpython/) (LGPL-3.0), ONNX Runtime (MIT),
  numpy (BSD-3-Clause), tokenizers and huggingface_hub (Apache-2.0), SoundCard
  (BSD-3-Clause), pydantic (MIT), PyYAML (MIT), psutil (BSD-3-Clause), mss (MIT);
  optional faster-whisper (MIT).
- Models (downloaded by `chaukas setup`, never committed): Whisper small by OpenAI (MIT),
  ONNX export by onnx-community; Silero VAD v6 (MIT); optional Qwen2.5-1.5B-Instruct
  (Apache-2.0) run with llama.cpp (MIT).
- Bundled assets: [Plus Jakarta Sans](https://github.com/tokotype/PlusJakartaSans) and
  [Noto Sans Devanagari](https://github.com/notofonts/devanagari) (SIL Open Font License
  1.1; licence files in `src/chaukas/ui/assets/fonts/`), [Lucide](https://lucide.dev)
  icons (ISC; licence in `src/chaukas/ui/assets/icons/`).
- "DemoBank (MOCK)" is fictional. Demo calls are scripted; no real victim audio and no real
  bank names are used.
