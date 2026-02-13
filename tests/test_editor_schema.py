"""Editor schema module unit tests"""

import pytest

from progress.editor_schema import FieldSchema, SectionSchema, EditorSchema
from pydantic import ValidationError


def test_field_schema_with_required_fields():
    field = FieldSchema(type="text", path="repos.0.url", label="Repository URL")

    assert field.type == "text"
    assert field.path == "repos.0.url"
    assert field.label == "Repository URL"
    assert field.help_text is None
    assert field.required is False
    assert field.default is None
    assert field.options == []
    assert field.validation == {}


def test_field_schema_with_all_fields():
    field = FieldSchema(
        type="select",
        path="github.fetch_depth",
        label="Fetch Depth",
        help_text="Git fetch depth for cloning",
        required=True,
        default="shallow",
        options=["shallow", "full"],
        validation={"min": 1, "max": 100},
    )

    assert field.type == "select"
    assert field.path == "github.fetch_depth"
    assert field.label == "Fetch Depth"
    assert field.help_text == "Git fetch depth for cloning"
    assert field.required is True
    assert field.default == "shallow"
    assert field.options == ["shallow", "full"]
    assert field.validation == {"min": 1, "max": 100}


def test_field_schema_with_list_type():
    field = FieldSchema(
        type="list",
        path="repos",
        label="Repositories",
        help_text="List of repositories to track",
        required=True,
    )

    assert field.type == "list"
    assert field.path == "repos"
    assert field.label == "Repositories"


def test_section_schema_with_required_fields():
    section = SectionSchema(
        id="repositories",
        title="Repository Configuration",
        fields=[FieldSchema(type="text", path="repos.0.url", label="Repository URL")],
    )

    assert section.id == "repositories"
    assert section.title == "Repository Configuration"
    assert section.description == ""
    assert len(section.fields) == 1
    assert section.fields[0].label == "Repository URL"


def test_section_schema_with_all_fields():
    section = SectionSchema(
        id="github",
        title="GitHub Settings",
        description="Configure GitHub CLI integration",
        fields=[
            FieldSchema(
                type="text", path="github.gh_token", label="GitHub Token", required=True
            ),
            FieldSchema(
                type="select",
                path="github.fetch_depth",
                label="Fetch Depth",
                options=["shallow", "full"],
            ),
        ],
    )

    assert section.id == "github"
    assert section.title == "GitHub Settings"
    assert section.description == "Configure GitHub CLI integration"
    assert len(section.fields) == 2


def test_editor_schema_with_sections():
    editor_schema = EditorSchema(
        sections=[
            SectionSchema(
                id="repositories",
                title="Repository Configuration",
                fields=[
                    FieldSchema(type="text", path="repos.0.url", label="Repository URL")
                ],
            ),
            SectionSchema(
                id="github",
                title="GitHub Settings",
                fields=[
                    FieldSchema(
                        type="text",
                        path="github.gh_token",
                        label="GitHub Token",
                        required=True,
                    )
                ],
            ),
        ]
    )

    assert len(editor_schema.sections) == 2
    assert editor_schema.sections[0].id == "repositories"
    assert editor_schema.sections[1].id == "github"


def test_field_schema_missing_required_field():
    with pytest.raises(ValidationError) as exc_info:
        FieldSchema(path="repos.0.url", label="Repository URL")

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("type",) for error in errors)


def test_section_schema_missing_required_field():
    with pytest.raises(ValidationError) as exc_info:
        SectionSchema(id="repositories", fields=[])

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("title",) for error in errors)


def test_field_schema_serialization():
    field = FieldSchema(
        type="select",
        path="github.fetch_depth",
        label="Fetch Depth",
        help_text="Git fetch depth",
        required=True,
        default="shallow",
        options=["shallow", "full"],
        validation={"min": 1},
    )

    field_dict = field.model_dump()

    assert field_dict["type"] == "select"
    assert field_dict["path"] == "github.fetch_depth"
    assert field_dict["label"] == "Fetch Depth"
    assert field_dict["help_text"] == "Git fetch depth"
    assert field_dict["required"] is True
    assert field_dict["default"] == "shallow"
    assert field_dict["options"] == ["shallow", "full"]
    assert field_dict["validation"] == {"min": 1}


def test_section_schema_serialization():
    section = SectionSchema(
        id="github",
        title="GitHub Settings",
        description="Configure GitHub",
        fields=[FieldSchema(type="text", path="github.gh_token", label="GitHub Token")],
    )

    section_dict = section.model_dump()

    assert section_dict["id"] == "github"
    assert section_dict["title"] == "GitHub Settings"
    assert section_dict["description"] == "Configure GitHub"
    assert len(section_dict["fields"]) == 1
    assert section_dict["fields"][0]["label"] == "GitHub Token"


def test_editor_schema_serialization():
    editor_schema = EditorSchema(
        sections=[
            SectionSchema(
                id="github",
                title="GitHub Settings",
                fields=[
                    FieldSchema(
                        type="text", path="github.gh_token", label="GitHub Token"
                    )
                ],
            )
        ]
    )

    schema_dict = editor_schema.model_dump()

    assert "sections" in schema_dict
    assert len(schema_dict["sections"]) == 1
    assert schema_dict["sections"][0]["id"] == "github"


def test_field_schema_with_timezone_type():
    field = FieldSchema(
        type="timezone",
        path="notification.timezone",
        label="Timezone",
        help_text="Notification timezone",
        default="UTC",
    )

    assert field.type == "timezone"
    assert field.default == "UTC"


def test_field_schema_with_boolean_type():
    field = FieldSchema(
        type="boolean", path="github.verify_ssl", label="Verify SSL", default=True
    )

    assert field.type == "boolean"
    assert field.default is True
