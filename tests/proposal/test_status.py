from progress.contrib.proposal.status import (
    get_analysis_template,
    normalize,
    should_notify,
)
from progress.contrib.proposal.types import ProposalKind, ProposalStatus


class TestNormalize:
    def test_eip_draft(self):
        assert normalize(ProposalKind.EIP, "Draft") == ProposalStatus.DRAFT

    def test_eip_last_call(self):
        assert normalize(ProposalKind.EIP, "Last Call") == ProposalStatus.REVIEW

    def test_eip_moved(self):
        assert normalize(ProposalKind.EIP, "Moved") == ProposalStatus.MOVED

    def test_eip_stagnant(self):
        assert normalize(ProposalKind.EIP, "Stagnant") == ProposalStatus.STAGNANT

    def test_erc_same_as_eip(self):
        assert normalize(ProposalKind.ERC, "Draft") == ProposalStatus.DRAFT
        assert normalize(ProposalKind.ERC, "Final") == ProposalStatus.FINAL

    def test_pep_april_fool(self):
        assert normalize(ProposalKind.PEP, "April Fool!") == ProposalStatus.REJECTED

    def test_pep_provisional(self):
        assert normalize(ProposalKind.PEP, "Provisional") == ProposalStatus.ACCEPTED

    def test_rfc_always_accepted(self):
        assert normalize(ProposalKind.RFC, "") == ProposalStatus.ACCEPTED
        assert normalize(ProposalKind.RFC, "anything") == ProposalStatus.ACCEPTED

    def test_dep_superseded(self):
        assert normalize(ProposalKind.DEP, "Superseded") == ProposalStatus.SUPERSEDED

    def test_unknown_status(self):
        assert normalize(ProposalKind.EIP, "NonExistent") == ProposalStatus.UNKNOWN
        assert normalize(ProposalKind.PEP, "Banana") == ProposalStatus.UNKNOWN

    def test_pep_deferred(self):
        assert normalize(ProposalKind.PEP, "Deferred") == ProposalStatus.DEFERRED


class TestShouldNotify:
    def test_new_proposal(self):
        assert should_notify(None, ProposalStatus.DRAFT) is True

    def test_same_status_no_notify(self):
        assert should_notify(ProposalStatus.DRAFT, ProposalStatus.DRAFT) is False

    def test_draft_to_final(self):
        assert should_notify(ProposalStatus.DRAFT, ProposalStatus.FINAL) is True

    def test_draft_to_withdrawn(self):
        assert should_notify(ProposalStatus.DRAFT, ProposalStatus.WITHDRAWN) is True

    def test_draft_to_review_no_notify(self):
        assert should_notify(ProposalStatus.DRAFT, ProposalStatus.REVIEW) is False

    def test_review_to_stagnant_no_notify(self):
        assert should_notify(ProposalStatus.REVIEW, ProposalStatus.STAGNANT) is False

    def test_stagnant_to_final(self):
        assert should_notify(ProposalStatus.STAGNANT, ProposalStatus.FINAL) is True

    def test_draft_to_accepted(self):
        assert should_notify(ProposalStatus.DRAFT, ProposalStatus.ACCEPTED) is True

    def test_draft_to_rejected(self):
        assert should_notify(ProposalStatus.DRAFT, ProposalStatus.REJECTED) is True

    def test_terminal_to_terminal_no_notify(self):
        assert should_notify(ProposalStatus.FINAL, ProposalStatus.FINAL) is False


class TestGetAnalysisTemplate:
    def test_new_proposal(self):
        assert (
            get_analysis_template(None, ProposalStatus.DRAFT)
            == "proposal_new_prompt.j2"
        )

    def test_content_modified(self):
        assert (
            get_analysis_template(ProposalStatus.DRAFT, ProposalStatus.DRAFT)
            == "proposal_content_modified_prompt.j2"
        )

    def test_accepted(self):
        assert (
            get_analysis_template(ProposalStatus.DRAFT, ProposalStatus.FINAL)
            == "proposal_accepted_prompt.j2"
        )

    def test_active(self):
        assert (
            get_analysis_template(ProposalStatus.DRAFT, ProposalStatus.ACTIVE)
            == "proposal_accepted_prompt.j2"
        )

    def test_rejected(self):
        assert (
            get_analysis_template(ProposalStatus.REVIEW, ProposalStatus.REJECTED)
            == "proposal_rejected_prompt.j2"
        )

    def test_withdrawn(self):
        assert (
            get_analysis_template(ProposalStatus.DRAFT, ProposalStatus.WITHDRAWN)
            == "proposal_withdrawn_prompt.j2"
        )

    def test_generic_status_change(self):
        assert (
            get_analysis_template(ProposalStatus.DRAFT, ProposalStatus.STAGNANT)
            == "proposal_status_change_prompt.j2"
        )

    def test_deferred_uses_generic(self):
        assert (
            get_analysis_template(ProposalStatus.DRAFT, ProposalStatus.DEFERRED)
            == "proposal_status_change_prompt.j2"
        )
