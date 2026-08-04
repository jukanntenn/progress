"""Unit tests for the bandit → SARIF converter (feature 1).

``scripts/bandit_to_sarif.py`` is a stdlib-only converter that turns bandit's
JSON output into a SARIF v2.1.0 document for the GitHub Security tab. The
bandit prek hook + the CI ``security.yml`` workflow are config/infra and are
not unit-testable, but the pure ``convert()`` function and the ``main()`` CLI
entry point are. These tests guard the level mapping (HIGH/MEDIUM/LOW →
error/warning/note), rule deduplication, and the SARIF top-level shape so a
regression doesn't silently break the Security tab upload.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from scripts.bandit_to_sarif import BANDIT_GUID, LEVEL_MAP, convert, main

if TYPE_CHECKING:
    from pathlib import Path


def _bandit_result(
    *,
    test_id: str = "B101",
    test_name: str = "assert_used",
    issue_text: str = "Use of assert detected.",
    severity: str = "LOW",
    confidence: str = "HIGH",
    filename: str = "src/app/views.py",
    line_number: int = 42,
    more_info: str = "https://bandit.readthedocs.io/en/latest/plugins/b101_assert_used.html",
) -> dict[str, Any]:
    return {
        "test_id": test_id,
        "test_name": test_name,
        "issue_text": issue_text,
        "issue_severity": severity,
        "issue_confidence": confidence,
        "filename": filename,
        "line_number": line_number,
        "more_info": more_info,
    }


class TestConvertStructure:
    def test_empty_results_produces_valid_sarif_skeleton(self) -> None:
        sarif = convert({"results": [], "version": "1.7.1"})
        assert sarif["$schema"].startswith("https://docs.oasis-open.org/sarif/")
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        run = sarif["runs"][0]
        assert run["tool"]["driver"]["name"] == "Bandit"
        assert run["tool"]["driver"]["informationUri"] == "https://github.com/PyCQA/bandit"
        assert run["tool"]["driver"]["guid"] == BANDIT_GUID
        assert run["tool"]["driver"]["version"] == "1.7.1"
        assert run["tool"]["driver"]["rules"] == []
        assert run["results"] == []

    def test_missing_version_key_falls_back_to_unknown(self) -> None:
        sarif = convert({"results": []})
        assert sarif["runs"][0]["tool"]["driver"]["version"] == "unknown"

    def test_missing_results_key_treated_as_empty(self) -> None:
        sarif = convert({})
        assert sarif["runs"][0]["results"] == []


class TestConvertLevelMapping:
    @pytest.mark.parametrize(
        ("severity", "expected_level"),
        [(sev, lvl) for sev, lvl in LEVEL_MAP.items()],
    )
    def test_each_severity_maps_to_expected_level(self, severity: str, expected_level: str) -> None:
        sarif = convert({"results": [_bandit_result(severity=severity)]})
        result = sarif["runs"][0]["results"][0]
        assert result["level"] == expected_level

    def test_unknown_severity_falls_back_to_note(self) -> None:
        sarif = convert({"results": [_bandit_result(severity="CRITICAL")]})
        assert sarif["runs"][0]["results"][0]["level"] == "note"

    def test_rule_default_configuration_uses_severity_level(self) -> None:
        sarif = convert({"results": [_bandit_result(severity="HIGH")]})
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["defaultConfiguration"]["level"] == "error"


class TestConvertResults:
    def test_single_result_emits_one_rule_and_one_result(self) -> None:
        sarif = convert({"results": [_bandit_result()]})
        run = sarif["runs"][0]
        assert len(run["tool"]["driver"]["rules"]) == 1
        assert len(run["results"]) == 1

        rule = run["tool"]["driver"]["rules"][0]
        assert rule["id"] == "B101"
        assert rule["name"] == "B101"
        assert rule["shortDescription"]["text"] == "assert_used"
        assert rule["fullDescription"]["text"] == "Use of assert detected."
        assert rule["helpUri"].startswith("https://")

        result = run["results"][0]
        assert result["ruleId"] == "B101"
        assert result["ruleIndex"] == 0
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "src/app/views.py"
        assert loc["region"]["startLine"] == 42
        assert result["message"]["text"] == "Use of assert detected."

    def test_rule_tags_include_security_and_confidence(self) -> None:
        sarif = convert({"results": [_bandit_result(confidence="MEDIUM")]})
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert "security" in rule["properties"]["tags"]
        assert "confidence:MEDIUM" in rule["properties"]["tags"]

    def test_two_results_same_test_id_dedupe_to_one_rule(self) -> None:
        results = [
            _bandit_result(filename="a.py", line_number=1),
            _bandit_result(filename="b.py", line_number=2),
        ]
        sarif = convert({"results": results})
        run = sarif["runs"][0]
        assert len(run["tool"]["driver"]["rules"]) == 1
        assert len(run["results"]) == 2
        # both results point at the single deduped rule (index 0)
        assert all(r["ruleIndex"] == 0 for r in run["results"])
        # distinct locations preserved per result
        uris = [r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in run["results"]]
        assert uris == ["a.py", "b.py"]

    def test_distinct_test_ids_get_distinct_rule_indices(self) -> None:
        results = [
            _bandit_result(test_id="B101", filename="a.py"),
            _bandit_result(test_id="B102", test_name="hardcoded_bind", filename="b.py"),
            _bandit_result(test_id="B101", filename="c.py"),
        ]
        sarif = convert({"results": results})
        run = sarif["runs"][0]
        # two distinct rules
        assert [r["id"] for r in run["tool"]["driver"]["rules"]] == ["B101", "B102"]
        # indices reference the first-seen order
        indices = [r["ruleIndex"] for r in run["results"]]
        assert indices == [0, 1, 0]

    def test_missing_line_number_defaults_to_1(self) -> None:
        raw = _bandit_result()
        del raw["line_number"]
        sarif = convert({"results": [raw]})
        loc = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        assert loc["region"]["startLine"] == 1

    def test_non_numeric_line_number_coerced_to_int(self) -> None:
        raw = _bandit_result()
        raw["line_number"] = "77"
        sarif = convert({"results": [raw]})
        loc = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        assert loc["region"]["startLine"] == 77

    def test_missing_more_info_falls_back_to_bandit_docs(self) -> None:
        raw = _bandit_result()
        del raw["more_info"]
        sarif = convert({"results": [raw]})
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["helpUri"] == "https://bandit.readthedocs.io/"

    def test_partial_fingerprint_is_stable(self) -> None:
        sarif = convert({"results": [_bandit_result(filename="x.py", line_number=9, test_id="B101")]})
        result = sarif["runs"][0]["results"][0]
        assert result["partialFingerprints"]["primaryLocationLineHash"] == "x.py:9:B101"


class TestMain:
    def test_round_trip_file_to_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bandit_json = tmp_path / "bandit.json"
        sarif_path = tmp_path / "bandit.sarif"
        bandit_json.write_text(
            json.dumps(
                {
                    "version": "1.7.1",
                    "results": [_bandit_result(severity="HIGH", filename="src/x.py", line_number=10)],
                }
            ),
            encoding="utf-8",
        )
        # main() reads argv via argparse; drive it by setting sys.argv.
        monkeypatch.setattr("sys.argv", ["bandit_to_sarif", str(bandit_json), str(sarif_path)])
        rc = main()
        assert rc == 0
        sarif = json.loads(sarif_path.read_text(encoding="utf-8"))
        assert sarif["runs"][0]["results"][0]["level"] == "error"

    def test_stdin_to_stdout_round_trip(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "sys.stdin",
            type("S", (), {"read": lambda self: json.dumps({"results": [_bandit_result()]})})(),
        )
        monkeypatch.setattr("sys.argv", ["bandit_to_sarif", "-", "-"])
        rc = main()
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert len(out["runs"][0]["results"]) == 1
