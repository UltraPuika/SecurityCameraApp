"""Every code/field the backend can emit must be translated in both UI languages."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.providers import ACCOUNT_PROVIDERS, PROVIDERS

ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "frontend" / "src" / "i18n" / "locales"
CODE_RE = re.compile(
    r"""["']((?:net|rtsp|onvif|stream|codec|imou|provider|validation|camera|account|bitvision|auth|go2rtc)"""
    r"""\.[a-z][a-z0-9_]*)["']"""
)
STATUSES = ("unknown", "online", "sleeping", "offline", "needs_setup", "unsupported", "quota")


def _lookup(tree: dict[str, Any], dotted: str) -> Any:
    node: Any = tree
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _backend_codes() -> set[str]:
    codes: set[str] = set()
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        codes |= set(CODE_RE.findall(path.read_text(encoding="utf-8")))
    return codes


@pytest.mark.parametrize("lang", ["en", "lv"])
def test_all_backend_codes_translated(lang: str) -> None:
    catalogue = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
    codes = _backend_codes()
    assert len(codes) > 40
    missing = sorted(c for c in codes if not isinstance(_lookup(catalogue["errors"], c), str))
    assert missing == []


@pytest.mark.parametrize("lang", ["en", "lv"])
def test_provider_fields_and_statuses_translated(lang: str) -> None:
    catalogue = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
    specs = [*(p.fields for p in PROVIDERS.values()), *(p.fields for p in ACCOUNT_PROVIDERS.values())]
    names = {f.name for fields in specs for f in fields}
    assert sorted(n for n in names if n not in catalogue["fields"]) == []
    assert sorted(p for p in PROVIDERS if p not in catalogue["providers"]) == []
    assert sorted(s for s in STATUSES if s not in catalogue["status"]) == []
