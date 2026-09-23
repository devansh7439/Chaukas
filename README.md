# Chaukas

An on-device AI guardian against social engineering on Windows PCs. Free and open source (Apache-2.0).

> **Status:** under active development for the Snapdragon® AI Lab Build & Present Challenge.
> The design spec is [Chaukas_BLUEPRINT.md](Chaukas_BLUEPRINT.md). The full README arrives with the first end-to-end demo.

## Development setup

Requires [uv](https://docs.astral.sh/uv/). The project pins Python 3.12 (`.python-version`).

```powershell
uv sync                      # create .venv and install dev tools
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # strict type check
uv run chaukas check-config  # validate the default configuration
uv run chaukas ablate eval/cases  # replay the sample cases under ablations A-E
```

## The window

![Chaukas dashboard during a simulated digital-arrest call](docs/images/dashboard.png)

```powershell
uv sync --extra ui --extra context                          # PySide6 and the context monitor
uv run chaukas ui --demo eval/cases/DA01.yaml               # play a simulated scam call in real time
uv run chaukas ui --demo eval/cases/DA01.yaml --speed 3     # ...three times faster
uv run chaukas ui                                           # empty session: type lines as the caller
uv run chaukas ui --demo eval/cases/DA01.yaml --screenshot shots/home.png --at 35   # headless PNGs
```

Alerts escalate from a corner notice to a side panel to a full-screen pause card. Nothing is
blocked: the user can verify independently, call a trusted contact or the 1930 helpline, or
tick "I understand" and continue. English and Hindi (Settings).

If `uv run pytest` fails with "uv trampoline failed to canonicalize script path", the
virtual environment's launchers are stale: run `uv sync --reinstall`.
