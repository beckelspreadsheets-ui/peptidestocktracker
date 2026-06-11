import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "check_language", ROOT / "tools" / "check_language.py"
)
check_language = importlib.util.module_from_spec(spec)
sys.modules["check_language"] = check_language
spec.loader.exec_module(check_language)

PATTERNS = check_language.load_patterns()
ALLOWED = check_language.load_allowed()


def _violations(source: str) -> list[str]:
    return check_language.find_violations(source, "sample.py", PATTERNS, ALLOWED)


def test_recommendation_phrase_in_alert_string_fails() -> None:
    source = 'MESSAGE = "We recommend buying this stock today."\n'
    found = _violations(source)
    assert len(found) == 1
    assert "recommend" in found[0]


def test_same_phrase_in_a_comment_passes() -> None:
    source = "# we recommend nothing, this is a comment\nVALUE = 1\n"
    assert _violations(source) == []


def test_allowlisted_disclaimer_passes() -> None:
    source = 'MESSAGE = "Possible market relevance only; this is not a buy/sell recommendation."\n'
    assert _violations(source) == []


def test_lang_ok_escape_hatch_passes() -> None:
    source = 'HELP = "This tool never gives advice."  # lang-ok: states the rule itself\n'
    assert _violations(source) == []


def test_advice_outside_escape_fails() -> None:
    source = 'HELP = "Here is some advice for you."\n'
    assert len(_violations(source)) == 1


def test_repo_user_facing_strings_pass_the_gate() -> None:
    assert check_language.main([]) == 0
