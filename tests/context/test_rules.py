"""What counts as action context: remote tools, bank and transfer pages, executables."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaukas.context.rules import ContextRules
from chaukas.core.errors import ConfigError
from chaukas.core.models import ContextKind

C = ContextKind


@pytest.fixture(scope="module")
def rules() -> ContextRules:
    return ContextRules.load()


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("DemoBank (MOCK) - Login", C.BANK_PAGE),
        ("DemoBank (MOCK) - Transfer Funds", C.TRANSFER_PAGE),
        ("DemoBank (MOCK) - Add Beneficiary - Google Chrome", C.TRANSFER_PAGE),
        ("DemoBank (MOCK) - Enter OTP", C.OTP_FIELD_VISIBLE),
        ("DemoBank (MOCK) - Transfer Successful", C.TRANSFER_PAGE),
        ("HDFC Bank NetBanking - Microsoft Edge", C.BANK_PAGE),
        ("SBI Online - IMPS Fund Transfer", C.TRANSFER_PAGE),
        ("WeTransfer - Send Large Files", None),  # "transfer" alone is not a bank
        ("Transfer learning explained - YouTube", None),
        ("Inbox - Gmail", None),
        ("", None),
    ],
)
def test_window_titles(rules: ContextRules, title: str, expected: ContextKind | None) -> None:
    assert rules.classify_title(title) is expected


@pytest.mark.parametrize(
    ("name", "company", "product", "expected"),
    [
        ("AnyDesk.exe", "", "", True),
        ("anydesk.exe", "", "", True),
        ("TeamViewer.exe", "", "", True),
        ("QuickAssist.exe", "", "", True),
        ("remoting_host.exe", "", "", True),
        ("setup_v2.exe", "philandro Software GmbH", "AnyDesk", True),  # renamed download
        ("support.exe", "", "TeamViewer", True),
        ("chrome.exe", "Google LLC", "Google Chrome", False),
        ("notepad.exe", "Microsoft Corporation", "Microsoft Windows Operating System", False),
    ],
)
def test_remote_tools(
    rules: ContextRules, name: str, company: str, product: str, expected: bool
) -> None:
    assert rules.is_remote_tool(name, company=company, product=product) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:/Users/a/Downloads/AnyDesk.exe", True),
        ("C:/Users/a/Downloads/setup.MSI", True),
        ("C:/Users/a/Downloads/app.apk", True),
        ("C:/Users/a/Downloads/run.ps1", True),
        ("C:/Users/a/Downloads/AnyDesk.exe.crdownload", False),  # still downloading
        ("C:/Users/a/Downloads/AnyDesk.exe.part", False),
        ("C:/Users/a/Downloads/report.pdf", False),
    ],
)
def test_executables(rules: ContextRules, path: str, expected: bool) -> None:
    assert rules.is_executable(Path(path)) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Enter the One Time Password sent to your mobile", C.OTP_FIELD_VISIBLE),
        ("कृपया ओटीपी दर्ज करें", C.OTP_FIELD_VISIBLE),
        ("Password: ********  Forgot password?", C.PASSWORD_FIELD_VISIBLE),
        ("Beneficiary name  Amount ₹ 50,000  Transfer", C.TRANSFER_PAGE),
        ("Weather today: sunny", None),
    ],
)
def test_screen_text(rules: ContextRules, text: str, expected: ContextKind | None) -> None:
    assert rules.classify_screen_text(text) is expected


def test_invalid_rules_are_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "context.yaml"
    bad.write_text("version: 1\nbanks: []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid context rules"):
        ContextRules.load(bad)
