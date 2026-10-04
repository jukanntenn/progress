"""Unit tests for ``TestNotificationEvent`` rendering (feature 6).

The HTTP endpoint and locale middleware are covered in
``tests/component/test_config_notifications.py`` and
``tests/unit/test_locale_middleware.py``, but the event itself, its dedicated
``test/{html,plain_text,card_json}.j2`` templates, and the
``_derive_title`` / ``_fallback_text`` branches in the renderer are not. These
tests render each content type via ``JinjaRenderer`` and assert the i18n test
message survives the template round-trip (in both English and Chinese, which
also guards the catalog compilation).
"""

from __future__ import annotations

import json

from progress.cli.notifications.base import ContentType
from progress.cli.notifications.events import TestNotificationEvent
from progress.cli.notifications.renderer import JinjaRenderer, _derive_title, _fallback_text
from progress.utils.i18n import override

TestNotificationEvent.__test__ = False  # ty: ignore[unresolved-attribute]

_BODY_MSGID = "This is a test notification from Progress."
_CONFIRM_MSGID = "Your notification channel is working correctly."


class TestEventDefaults:
    def test_kind_is_test(self) -> None:
        assert TestNotificationEvent().kind == "test"

    def test_takes_no_business_data(self) -> None:
        event = TestNotificationEvent()
        public_attrs = {a for a in dir(event) if not a.startswith("_")}
        assert public_attrs == {"kind"}


class TestDeriveTitle:
    def test_english_title(self) -> None:
        with override("en"):
            assert _derive_title(TestNotificationEvent()) == "Test Notification"

    def test_chinese_title(self) -> None:
        with override("zh-hans"):
            assert _derive_title(TestNotificationEvent()) == "测试通知"


class TestFallbackText:
    def test_english_fallback(self) -> None:
        with override("en"):
            assert _fallback_text(TestNotificationEvent()) == "✅ Test Notification from Progress"

    def test_chinese_fallback(self) -> None:
        with override("zh-hans"):
            assert _fallback_text(TestNotificationEvent()) == "✅ Progress 测试通知"


class TestHtmlTemplate:
    def test_renders_simplified_test_message_in_english(self) -> None:
        with override("en"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.HTML)
        assert payload.content_type is ContentType.HTML
        assert _BODY_MSGID in payload.body
        assert _CONFIRM_MSGID in payload.body
        assert "<br>" not in payload.body
        assert "no reply needed" not in payload.body.lower()
        assert payload.title == "Test Notification"

    def test_renders_translated_message_in_chinese(self) -> None:
        with override("zh-hans"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.HTML)
        assert "这是一条来自 Progress 的测试通知。" in payload.body
        assert "你的通知渠道已配置正常。" in payload.body
        assert payload.title == "测试通知"


class TestPlainTextTemplate:
    def test_english_plain_text(self) -> None:
        with override("en"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.PLAIN_TEXT)
        assert payload.content_type is ContentType.PLAIN_TEXT
        assert _BODY_MSGID in payload.body
        assert _CONFIRM_MSGID in payload.body

    def test_chinese_plain_text(self) -> None:
        with override("zh-hans"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.PLAIN_TEXT)
        assert "这是一条来自 Progress 的测试通知。" in payload.body
        assert "你的通知渠道已配置正常。" in payload.body


class TestCardJsonTemplate:
    def test_card_is_v2_with_green_header_and_concise_body(self) -> None:
        with override("en"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.CARD_JSON)
        assert payload.content_type is ContentType.CARD_JSON
        card = json.loads(payload.body)
        assert card["schema"] == "2.0"
        assert card["config"]["width_mode"] == "fill"
        assert card["header"]["template"] == "green"
        assert card["header"]["title"]["content"] == "Test Notification"
        assert card["header"]["icon"]["token"] == "check-circle-outlined"
        tag = card["header"]["text_tag_list"][0]
        assert tag["text"]["content"] == "TEST"
        tags = [e["tag"] for e in card["body"]["elements"]]
        assert tags[0] == "markdown"
        assert "button" not in tags
        all_content = " ".join(e.get("content", "") for e in card["body"]["elements"] if e.get("tag") == "markdown")
        assert _BODY_MSGID in all_content
        assert _CONFIRM_MSGID in all_content
        assert "<br>" not in all_content

    def test_card_translates_body_in_chinese(self) -> None:
        with override("zh-hans"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.CARD_JSON)
        card = json.loads(payload.body)
        assert card["header"]["title"]["content"] == "测试通知"
        all_content = " ".join(e.get("content", "") for e in card["body"]["elements"] if e.get("tag") == "markdown")
        assert "这是一条来自 Progress 的测试通知。" in all_content
        assert "你的通知渠道已配置正常。" in all_content
