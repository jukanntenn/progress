"""Unit tests for ``progress.integrations.proposal.statuses`` (spec proposal §10)."""

from __future__ import annotations

from progress.integrations.proposal.statuses import (
    NOTIFY_STATUSES,
    TERMINAL_STATUSES,
    ProposalStatus,
    normalize,
    select_template,
    should_notify,
)


class TestNormalize:
    def test_eip_draft(self) -> None:
        assert normalize("Draft", "eip") == "draft"

    def test_eip_last_call_to_review(self) -> None:
        assert normalize("Last Call", "eip") == "review"

    def test_eip_living_to_active(self) -> None:
        assert normalize("Living", "eip") == "active"

    def test_eip_moved(self) -> None:
        assert normalize("Moved", "eip") == "moved"

    def test_erc_uses_eip_map(self) -> None:
        assert normalize("Draft", "erc") == "draft"
        assert normalize("Last Call", "erc") == "review"

    def test_pep_april_fool_to_rejected(self) -> None:
        assert normalize("April Fool!", "pep") == "rejected"

    def test_pep_provisional_to_accepted(self) -> None:
        assert normalize("Provisional", "pep") == "accepted"

    def test_pep_superseded(self) -> None:
        assert normalize("Superseded", "pep") == "superseded"

    def test_rfc_always_accepted(self) -> None:
        assert normalize("", "rfc") == "accepted"
        assert normalize("Random", "rfc") == "accepted"

    def test_dep_draft(self) -> None:
        assert normalize("Draft", "dep") == "draft"

    def test_unknown_status_to_unknown(self) -> None:
        assert normalize("UnknownStatus", "eip") == "unknown"

    def test_case_sensitive_lookup(self) -> None:
        assert normalize("draft", "eip") == "unknown"
        assert normalize("DRAFT", "eip") == "unknown"

    def test_space_sensitive_lookup(self) -> None:
        assert normalize(" Last Call ", "eip") == "unknown"
        assert normalize("Last  Call", "eip") == "unknown"


class TestStatusSets:
    def test_terminal_includes_unknown(self) -> None:
        assert "unknown" in TERMINAL_STATUSES

    def test_terminal_excludes_draft(self) -> None:
        assert "draft" not in TERMINAL_STATUSES

    def test_terminal_excludes_review(self) -> None:
        assert "review" not in TERMINAL_STATUSES

    def test_notify_set_includes_accepted(self) -> None:
        assert "accepted" in NOTIFY_STATUSES

    def test_notify_set_excludes_review(self) -> None:
        assert "review" not in NOTIFY_STATUSES


class TestShouldNotify:
    def test_new_proposal_notifies(self) -> None:
        assert should_notify(None, "draft") is True
        assert should_notify(None, "final") is True

    def test_unchanged_status_does_not_notify(self) -> None:
        assert should_notify("draft", "draft") is False
        assert should_notify("final", "final") is False

    def test_notify_status_change_notifies(self) -> None:
        for status in ("final", "active", "accepted", "withdrawn", "rejected"):
            assert should_notify("draft", status) is True

    def test_non_notify_status_change_does_not_notify(self) -> None:
        for status in ("review", "stagnant", "deferred", "moved", "superseded", "unknown"):
            assert should_notify("draft", status) is False


class TestSelectTemplate:
    def test_new_proposal(self) -> None:
        assert select_template(None, "draft") == "proposal_new_prompt.j2"

    def test_content_modified(self) -> None:
        assert select_template("draft", "draft") == "proposal_content_modified_prompt.j2"

    def test_accepted_template_for_final(self) -> None:
        assert select_template("draft", "final") == "proposal_accepted_prompt.j2"

    def test_accepted_template_for_active(self) -> None:
        assert select_template("draft", "active") == "proposal_accepted_prompt.j2"

    def test_accepted_template_for_accepted(self) -> None:
        assert select_template("draft", "accepted") == "proposal_accepted_prompt.j2"

    def test_rejected_template(self) -> None:
        assert select_template("draft", "rejected") == "proposal_rejected_prompt.j2"

    def test_withdrawn_template(self) -> None:
        assert select_template("draft", "withdrawn") == "proposal_withdrawn_prompt.j2"

    def test_status_change_template_for_deferred(self) -> None:
        assert select_template("draft", "deferred") == "proposal_status_change_prompt.j2"

    def test_status_change_template_for_stagnant(self) -> None:
        assert select_template("draft", "stagnant") == "proposal_status_change_prompt.j2"

    def test_status_change_template_for_moved(self) -> None:
        assert select_template("draft", "moved") == "proposal_status_change_prompt.j2"

    def test_status_change_template_for_superseded(self) -> None:
        assert select_template("draft", "superseded") == "proposal_status_change_prompt.j2"

    def test_status_change_template_for_unknown(self) -> None:
        assert select_template("draft", "unknown") == "proposal_status_change_prompt.j2"

    def test_independent_of_should_notify(self) -> None:
        assert select_template("draft", "stagnant") == "proposal_status_change_prompt.j2"
        assert should_notify("draft", "stagnant") is False


class TestProposalStatusEnum:
    def test_twelve_statuses(self) -> None:
        expected = {
            "draft",
            "review",
            "accepted",
            "final",
            "active",
            "stagnant",
            "deferred",
            "withdrawn",
            "rejected",
            "superseded",
            "moved",
            "unknown",
        }
        actual = {s.value for s in ProposalStatus}
        assert actual == expected
