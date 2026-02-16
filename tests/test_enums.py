from progress.enums import ReportType


def test_report_type_enum_values():
    assert ReportType.REPO_UPDATE.value == "repo_update"
    assert ReportType.REPO_NEW.value == "repo_new"
    assert ReportType.PROPOSAL.value == "proposal"
    assert ReportType.CHANGELOG.value == "changelog"


def test_report_type_is_string_enum():
    assert isinstance(ReportType.REPO_UPDATE, str)
    assert ReportType.REPO_UPDATE == "repo_update"
