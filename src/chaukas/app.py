"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from chaukas import __version__
from chaukas.core.config import ChaukasConfig, load_config
from chaukas.core.errors import ChaukasError
from chaukas.evaluation.ablation import ABLATIONS, config_for
from chaukas.evaluation.cases import Case, Split, load_case, load_cases
from chaukas.evaluation.metrics import CaseOutcome, Summary, score_case, summarise
from chaukas.evaluation.report import (
    format_ablation,
    format_outcomes,
    format_run,
    format_scripted_llm_note,
)
from chaukas.evaluation.runner import run_case
from chaukas.llm.cache import CachedChat
from chaukas.llm.client import Chat, ChatClient
from chaukas.llm.reasoner import Reasoner
from chaukas.signals.lexicon import Lexicon

EXIT_OK = 0
EXIT_ERROR = 2

# Until the LLM layer exists, E (everything except the LLM) is the honest default. The LLM
# configurations only see verdicts a case scripts; without one, the pre-LLM cap keeps them
# quiet until llm.failure_grace_s passes, after which they behave as if the LLM had failed.
DEFAULT_ABLATION = "E"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chaukas",
        description="On-device AI guardian against social engineering.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser(
        "check-config", help="validate the configuration and print the merged result"
    )
    _add_config_option(check)

    replay = commands.add_parser(
        "replay", help="replay one case script through signals and the risk engine"
    )
    replay.add_argument("case", type=Path, help="case script (YAML)")
    _add_config_option(replay)
    _add_ablation_option(replay)
    _add_llm_options(replay)
    replay.add_argument("--tick", type=float, default=1.0, metavar="SECONDS")

    evaluate = commands.add_parser("eval", help="score every case in a directory")
    evaluate.add_argument("cases", type=Path, help="directory of case scripts")
    _add_config_option(evaluate)
    _add_ablation_option(evaluate)
    _add_llm_options(evaluate)
    evaluate.add_argument("--split", choices=[split.value for split in Split])

    ablate = commands.add_parser("ablate", help="run every ablation configuration and compare")
    ablate.add_argument("cases", type=Path, help="directory of case scripts")
    _add_config_option(ablate)
    _add_llm_options(ablate)
    ablate.add_argument("--split", choices=[split.value for split in Split])

    ui = commands.add_parser("ui", help="open the Chaukas window (needs the 'ui' extra)")
    ui.add_argument("--demo", type=Path, metavar="CASE", help="play a case script in real time")
    ui.add_argument("--speed", type=float, default=1.0, help="demo playback speed (default 1)")
    _add_config_option(ui)
    _add_ablation_option(ui)
    ui.add_argument("--screenshot", type=Path, metavar="PNG",
                    help="render headless to PNG files and exit")  # fmt: skip
    ui.add_argument("--at", type=float, default=0.0, metavar="SECONDS",
                    help="with --screenshot: the moment of the demo to render")  # fmt: skip
    ui.add_argument("--page", type=int, choices=range(4), default=0,
                    help="0 home, 1 why, 2 privacy, 3 settings")  # fmt: skip
    ui.add_argument("--size", type=_size, default=(1440, 920), metavar="WxH")

    run = commands.add_parser("run", help="live protection: listen to calls on this PC")
    _add_config_option(run)
    _add_ablation_option(run)
    run.add_argument("--no-audio", action="store_true", help="don't listen (screen only)")
    run.add_argument("--no-screen", action="store_true", help="don't watch apps and pages")
    run.add_argument("--asr-model", metavar="SIZE", help="Whisper size: tiny, base, small")
    run.add_argument("--asr-backend", choices=["onnx", "ctranslate2"], help="speech-to-text engine")
    run.add_argument("--language", choices=["auto", "en", "hi"], help="speech language")

    setup = commands.add_parser("setup", help="download the speech model (one time)")
    _add_config_option(setup)
    setup.add_argument("--asr-model", metavar="SIZE", help="Whisper size to download")
    setup.add_argument("--asr-backend", choices=["onnx", "ctranslate2"], help="for which engine")

    commands.add_parser("devices", help="list the audio devices Chaukas would use")

    return parser


def _size(text: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, got {text!r}") from None
    return width, height


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "llm_offline", False) and args.llm_cache is None:
        parser.error("--llm-offline needs --llm-cache")
    if getattr(args, "llm_cache", None) is not None and not args.llm:
        parser.error("--llm-cache needs --llm")
    try:
        if args.command == "check-config":
            print(load_config(*args.config).model_dump_json(indent=2))
        elif args.command == "replay":
            print(_replay(args))
        elif args.command == "eval":
            print(_evaluate(args))
        elif args.command == "ablate":
            print(_ablate(args))
        elif args.command == "ui":
            return _ui(args)
        elif args.command == "run":
            return _run(args)
        elif args.command == "setup":
            _setup(args)
        elif args.command == "devices":
            _devices()
        else:  # pragma: no cover - argparse rejects anything else
            raise AssertionError(f"unhandled command {args.command!r}")
    except ChaukasError as exc:
        print(exc, file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _add_config_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        action="append",
        default=[],
        metavar="PATH",
        help="YAML override applied on top of the defaults (repeatable, applied in order)",
    )


def _add_ablation_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ablation",
        choices=sorted(ABLATIONS),
        default=DEFAULT_ABLATION,
        help=f"ablation configuration (default {DEFAULT_ABLATION})",
    )


def _add_llm_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("LLM")
    group.add_argument(
        "--llm",
        action="store_true",
        help="call the model at llm.base_url instead of using the cases' scripted verdicts",
    )
    group.add_argument(
        "--llm-cache",
        type=Path,
        metavar="DIR",
        help="record every answer (with its latency) here and reuse it on later runs",
    )
    group.add_argument(
        "--llm-offline",
        action="store_true",
        help="answer only from --llm-cache; never call the model",
    )


def _reasoner(args: argparse.Namespace, config: ChaukasConfig) -> Reasoner | None:
    if not args.llm:
        return None
    chat: Chat = ChatClient.from_config(config.llm)
    if args.llm_cache is not None:
        chat = CachedChat(chat, args.llm_cache, model=config.llm.model, offline=args.llm_offline)
    return Reasoner(chat, config)


def _replay(args: argparse.Namespace) -> str:
    config = config_for(args.ablation, *args.config)
    run = run_case(
        load_case(args.case),
        config=config,
        lexicon=Lexicon.load(),
        tick_s=args.tick,
        reasoner=_reasoner(args, config),
    )
    return format_run(run)


def _evaluate(args: argparse.Namespace) -> str:
    config = config_for(args.ablation, *args.config)
    cases = _load_cases(args)
    outcomes = _score_all(cases, config, _reasoner(args, config))
    llm_configs = [args.ablation] if config.ablation.use_llm and not args.llm else []
    return _with_llm_note(format_outcomes(outcomes, summarise(outcomes)), cases, llm_configs)


def _ablate(args: argparse.Namespace) -> str:
    cases = _load_cases(args)
    summaries: dict[str, Summary] = {}
    llm_configs: list[str] = []
    for name in sorted(ABLATIONS):
        config = config_for(name, *args.config)
        summaries[name] = summarise(_score_all(cases, config, _reasoner(args, config)))
        if config.ablation.use_llm and not args.llm:
            llm_configs.append(name)
    return _with_llm_note(format_ablation(summaries), cases, llm_configs)


def _ui(args: argparse.Namespace) -> int:
    try:
        from chaukas.ui.app import run
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ChaukasError(f"the window needs PySide6: uv sync --extra ui ({exc})") from exc
    return run(
        case=args.demo,
        ablation=args.ablation,
        config_paths=args.config,
        speed=args.speed,
        screenshot=args.screenshot,
        at=args.at,
        page=args.page,
        size=args.size,
    )


def _run(args: argparse.Namespace) -> int:
    try:
        from chaukas.ui.app import run_live
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ChaukasError(f"the window needs PySide6: uv sync --extra ui ({exc})") from exc
    asr: dict[str, str] = {}
    if args.asr_model:
        asr["model"] = args.asr_model
    if args.asr_backend:
        asr["backend"] = args.asr_backend
    if args.language:
        asr["language"] = args.language
    return run_live(
        ablation=args.ablation,
        config_paths=args.config,
        config_overrides=[{"asr": asr}] if asr else [],
        audio=not args.no_audio,
        screen=not args.no_screen,
    )


def _setup(args: argparse.Namespace) -> None:
    """Download what live protection needs. The only command that uses the network."""
    try:
        from chaukas.asr.loader import download, model_ready
        from chaukas.audio.vad import MODEL_NAME, download_vad_model
        from chaukas.core.paths import models_dir
    except ImportError as exc:
        raise ChaukasError(
            f"speech recognition is not installed: uv sync --extra audio --extra asr ({exc})"
        ) from exc
    config = load_config(*args.config)
    asr = config.asr.model_copy(
        update={
            "model": args.asr_model or config.asr.model,
            "backend": args.asr_backend or config.asr.backend,
        }
    )
    name = f"Whisper {asr.model} ({asr.backend})"
    if model_ready(asr):
        print(f"{name}: already on this PC")
    else:
        print(f"{name}: downloading (one time)...")
        print(f"  saved to {download(asr)}")
    if (models_dir() / MODEL_NAME).is_file():
        print("Voice detection model: already on this PC")
    else:
        print("Voice detection model: downloading (one time, checked by SHA-256)...")
        print(f"  saved to {download_vad_model()}")
    _devices()


def _devices() -> None:
    try:
        from chaukas.audio.capture import AudioSystem
    except ImportError as exc:
        raise ChaukasError(
            f"audio capture is not installed: uv sync --extra audio ({exc})"
        ) from exc
    system = AudioSystem()
    try:
        loopback, microphone = system.default_loopback(), system.default_microphone()
        print(f"Caller (what this PC plays): {loopback or 'not found'}")
        print(f"You (microphone):            {microphone or 'not found'}")
    finally:
        system.close()


def _load_cases(args: argparse.Namespace) -> tuple[Case, ...]:
    return load_cases(args.cases, split=Split(args.split) if args.split else None)


def _score_all(
    cases: Sequence[Case], config: ChaukasConfig, reasoner: Reasoner | None
) -> list[CaseOutcome]:
    lexicon = Lexicon.load()
    return [
        score_case(run_case(case, config=config, lexicon=lexicon, reasoner=reasoner))
        for case in cases
    ]


def _with_llm_note(text: str, cases: Sequence[Case], llm_configs: Sequence[str]) -> str:
    """Append a caveat when LLM configurations were scored on scripted verdicts."""
    scripted = [case.case_id for case in cases if case.assessments]
    if not scripted or not llm_configs:
        return text
    return f"{text}\n\n{format_scripted_llm_note(scripted, len(cases), llm_configs)}"
