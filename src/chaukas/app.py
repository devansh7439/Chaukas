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

    return parser


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
