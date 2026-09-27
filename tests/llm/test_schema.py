"""Parsing the LLM's reply (blueprint 5.1): lenient about wrapping, strict about content."""

from __future__ import annotations

import json
from typing import Any

import pytest

from chaukas.core.errors import LLMReplyError
from chaukas.core.models import Objective
from chaukas.llm.schema import parse_reply


def reply(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "addressed_to_user": True,
        "claimed_identity": "cbi",
        "tactics": [
            {"name": "threat", "line": 3, "evidence": "arrest warrant hai", "confidence": 0.8}
        ],
        "requested_actions": [
            {"action": "money_transfer", "line": 5, "evidence": "amount transfer karo",
             "confidence": 0.9}
        ],
        "user_compliance": "unclear",
        "suspected_objective": "money_transfer",
        "benign_explanation": "",
    }  # fmt: skip
    data.update(overrides)
    return data


def test_parses_a_valid_reply() -> None:
    parsed = parse_reply(json.dumps(reply()))
    assert parsed.addressed_to_user is True
    assert parsed.claimed_identity == "cbi"
    assert [t.name for t in parsed.tactics] == ["threat"]
    assert parsed.requested_actions[0].action == "money_transfer"
    assert parsed.suspected_objective is Objective.MONEY_TRANSFER
    assert parsed.dropped_items == 0


@pytest.mark.parametrize(
    "wrap",
    [
        "```json\n{}\n```",
        "Here is the analysis:\n{}\nHope this helps.",
        "```\n{}\n```",
    ],
)
def test_finds_the_object_inside_chatter_and_code_fences(wrap: str) -> None:
    parsed = parse_reply(wrap.replace("{}", json.dumps(reply())))
    assert parsed.suspected_objective is Objective.MONEY_TRANSFER


def test_braces_inside_strings_do_not_confuse_extraction() -> None:
    text = "note {not json} " + json.dumps(reply(benign_explanation="a {curly} reply"))
    assert parse_reply(text).benign_explanation == "a {curly} reply"


def test_invalid_items_are_dropped_and_counted() -> None:
    parsed = parse_reply(
        json.dumps(
            reply(
                tactics=[
                    {"name": "threat", "line": 3, "evidence": "arrest", "confidence": 0.8},
                    {"name": "flattery", "line": 3, "evidence": "sir", "confidence": 0.5},
                    {"name": "urgency", "line": 3, "evidence": "abhi", "confidence": 80},
                    "not an object",
                ]
            )
        )
    )
    assert [t.name for t in parsed.tactics] == ["threat"]
    assert parsed.dropped_items == 3


def test_unknown_identity_becomes_other_and_missing_lists_are_empty() -> None:
    data = reply(claimed_identity="interpol")
    del data["tactics"], data["requested_actions"]
    parsed = parse_reply(json.dumps(data))
    assert parsed.claimed_identity == "other"
    assert parsed.tactics == ()
    assert parsed.requested_actions == ()


def test_lax_types_from_small_models_are_accepted() -> None:
    parsed = parse_reply(
        json.dumps(
            reply(
                addressed_to_user="true",
                tactics=[{"name": "THREAT", "line": "3", "evidence": "x", "confidence": "0.7"}],
            )
        )
    )
    assert parsed.addressed_to_user is True
    assert parsed.tactics[0].line == 3
    assert parsed.tactics[0].confidence == pytest.approx(0.7)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "no json here",
        "[1, 2, 3]",
        '{"addressed_to_user": true',
        json.dumps({"tactics": []}),  # required fields missing
        json.dumps(reply(suspected_objective="world_domination")),
    ],
)
def test_unusable_replies_raise(text: str) -> None:
    with pytest.raises(LLMReplyError):
        parse_reply(text)


class TestReplyJsonSchema:
    """The schema sent to servers that constrain output (llama.cpp): same enums as the parser."""

    def test_enums_come_from_the_parsers_own_types(self) -> None:
        from typing import get_args

        from chaukas.llm.schema import IDENTITIES, ActionName, TacticName, reply_json_schema

        props = reply_json_schema()["properties"]
        tactic = props["tactics"]["items"]["properties"]["name"]["enum"]
        action = props["requested_actions"]["items"]["properties"]["action"]["enum"]
        assert set(tactic) == set(get_args(TacticName))
        assert set(action) == set(get_args(ActionName))
        assert set(props["claimed_identity"]["enum"]) == IDENTITIES
        assert set(props["suspected_objective"]["enum"]) == {o.value for o in Objective}

    def test_every_field_is_required_and_output_is_bounded(self) -> None:
        from chaukas.llm.schema import reply_json_schema

        schema = reply_json_schema()
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False
        for name in ("tactics", "requested_actions"):
            assert schema["properties"][name]["maxItems"] <= 5
            item = schema["properties"][name]["items"]
            assert item["properties"]["evidence"]["maxLength"] <= 120
        assert schema["properties"]["benign_explanation"]["maxLength"] <= 150

    def test_an_object_following_the_schema_parses(self) -> None:
        assert parse_reply(json.dumps(reply())).suspected_objective is Objective.MONEY_TRANSFER


class TestPrompt:
    def test_the_prompt_has_no_pipe_placeholders_a_model_could_copy(self) -> None:
        from chaukas.llm.prompts import SYSTEM_PROMPT

        assert "|" not in SYSTEM_PROMPT

    def test_the_example_in_the_prompt_is_itself_a_valid_reply(self) -> None:
        from chaukas.llm.prompts import EXAMPLE

        parse_reply(EXAMPLE)
