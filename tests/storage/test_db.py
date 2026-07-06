from unittest.mock import AsyncMock, patch

from progress.storages.db import DBStorage


async def test_db_storage_creates_report_and_returns_id():
    mock_report = AsyncMock()
    mock_report.id = 123

    with patch("progress.db.models.Report") as report_model:
        report_model.create = AsyncMock(return_value=mock_report)

        storage = DBStorage()
        result = await storage.save("Title", ["Body 1", "Body 2"])

        assert result == ["123"]
        report_model.create.assert_called_once_with(
            title="Title", content="Body 1\n\nBody 2", commit_hash=""
        )


async def test_db_storage_joins_bodies():
    mock_report = AsyncMock()
    mock_report.id = 456

    with patch("progress.db.models.Report") as report_model:
        report_model.create = AsyncMock(return_value=mock_report)

        storage = DBStorage()
        await storage.save("Title", ["Part A", "Part B", "Part C"])

        call_kwargs = report_model.create.call_args.kwargs
        assert call_kwargs["content"] == "Part A\n\nPart B\n\nPart C"


async def test_db_storage_single_body():
    mock_report = AsyncMock()
    mock_report.id = 789

    with patch("progress.db.models.Report") as report_model:
        report_model.create = AsyncMock(return_value=mock_report)

        storage = DBStorage()
        result = await storage.save("Title", ["Only body"])

        assert result == ["789"]
        call_kwargs = report_model.create.call_args.kwargs
        assert call_kwargs["content"] == "Only body"
