"""The LLM's reply (blueprint 5.1): found leniently, validated strictly.

Small on-device models wrap JSON in prose or code fences, quote numbers and booleans, and
invent enum values. Parsing therefore:

* extracts the first balanced JSON object from the text, ignoring braces inside strings;
* validates the top-level fields strictly (a reply without them is unusable);
* validates each tactic and requested action on its own, dropping and counting invalid
  items instead of discarding the whole reply, since one bad item shouldn't hide the rest;
* accepts lax scalar types ("0.7", "true") and case-insensitive enum values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from chaukas.core.errors import LLMReplyError
from chaukas.core.models import Objective

TacticName = Literal["authority", "threat", "urgency", "isolation", "surveillance"]
ActionName = Literal[
    "money_transfer",
    "install_remote_app",
    "share_screen",
    "download_file",
    "disclose_otp",
    "disclose_password",
    "open_bank_site",
]
Compliance = Literal["complied", "resisting", "unclear"]

IDENTITIES: Final = frozenset(
    {
        "police", "cbi", "ed", "trai", "rbi", "bank", "customs", "courier", "tech_support",
        "telecom", "government", "family", "none", "other",
    }
)  # fmt: skip


def _lower(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


Lower = BeforeValidator(_lower)


class _Item(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    line: int = Field(ge=0)
    evidence: str
    confidence: float = Field(ge=0.0, le=1.0)


M = TypeVar("M", bound=_Item)


class Tactic(_Item):
    name: Annotated[TacticName, Lower]


class RequestedAction(_Item):
    action: Annotated[ActionName, Lower]


class _Header(BaseModel):
    model_config = ConfigDict(extra="ignore")

    addressed_to_user: bool
    suspected_objective: Annotated[Objective, Lower]
    claimed_identity: Annotated[str, Lower] = "none"
    user_compliance: Annotated[Compliance, Lower] = "unclear"
    benign_explanation: str = ""


@dataclass(frozen=True, slots=True)
class LLMReply:
    addressed_to_user: bool
    claimed_identity: str
    tactics: tuple[Tactic, ...]
    requested_actions: tuple[RequestedAction, ...]
    user_compliance: Compliance
    suspected_objective: Objective
    benign_explanation: str  # logged for evaluation; never shown to the user
    dropped_items: int  # items that failed validation


def parse_reply(text: str) -> LLMReply:
    """Parse a raw completion. Raises LLMReplyError if no usable object is found."""
    data = extract_json_object(text)
    try:
        header = _Header.model_validate(data)
    except ValidationError as exc:
        raise LLMReplyError(f"reply is missing or has invalid required fields: {exc}") from exc
    tactics, dropped_tactics = _items(data.get("tactics"), Tactic)
    actions, dropped_actions = _items(data.get("requested_actions"), RequestedAction)
    identity = header.claimed_identity if header.claimed_identity in IDENTITIES else "other"
    return LLMReply(
        addressed_to_user=header.addressed_to_user,
        claimed_identity=identity,
        tactics=tactics,
        requested_actions=actions,
        user_compliance=header.user_compliance,
        suspected_objective=header.suspected_objective,
        benign_explanation=header.benign_explanation,
        dropped_items=dropped_tactics + dropped_actions,
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """The first balanced ``{...}`` in ``text`` that parses as a JSON object."""
    start = text.find("{")
    while start != -1:
        end = _matching_brace(text, start)
        if end is None:
            break
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    raise LLMReplyError("no JSON object found in the reply")


def _matching_brace(text: str, start: int) -> int | None:
    """Index of the brace closing the one at ``start``, skipping braces inside strings."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _items(raw: Any, model: type[M]) -> tuple[tuple[M, ...], int]:
    if raw is None:
        return (), 0
    if not isinstance(raw, list):
        return (), 1
    kept: list[M] = []
    dropped = 0
    for item in raw:
        try:
            kept.append(model.model_validate(item))
        except ValidationError:
            dropped += 1
    return tuple(kept), dropped
