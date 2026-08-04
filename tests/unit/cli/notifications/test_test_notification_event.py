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

# ``TestNotificationEvent`` is a production dataclass whose name starts with
# ``Test``, so pytest tries (and fails) to collect it as a test class. Mark it
# non-collectable so the suite stays warning-free.
TestNotificationEvent.__test__ = False  # ty: ignore[unresolved-attribute]

_BODY_MSGID = "This is a test notification. If you received this, the notification channel is configured correctly."
_CONSOLE_MSGID = "Sent from Progress config console."


class TestEventDefaults:
    def test_kind_is_test(self) -> None:
        assert TestNotificationEvent().kind == "test"

    def test_takes_no_business_data(self) -> None:
        # The event carries nothing business-specific; attribute access to other
        # fields must not exist.
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
    def test_renders_branded_test_message_in_english(self) -> None:
        with override("en"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.HTML)
        assert payload.content_type is ContentType.HTML
        assert "✅ Test Notification from Progress" in payload.body
        assert _BODY_MSGID in payload.body
        assert _CONSOLE_MSGID in payload.body
        # title comes from _derive_title (i18n)
        assert payload.title == "Test Notification"

    def test_renders_translated_message_in_chinese(self) -> None:
        with override("zh-hans"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.HTML)
        assert "✅ Progress 测试通知" in payload.body
        assert "这是一条测试通知。如果你收到了这条消息，说明通知通道已正确配置。" in payload.body
        assert "由 Progress 配置控制台发送。" in payload.body
        assert payload.title == "测试通知"


class TestPlainTextTemplate:
    def test_english_plain_text(self) -> None:
        with override("en"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.PLAIN_TEXT)
        assert payload.content_type is ContentType.PLAIN_TEXT
        lines = payload.body.split("\n")
        assert lines[0] == "✅ Test Notification from Progress"
        assert _BODY_MSGID in payload.body
        assert _CONSOLE_MSGID in payload.body

    def test_chinese_plain_text(self) -> None:
        with override("zh-hans"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.PLAIN_TEXT)
        assert "✅ Progress 测试通知" in payload.body
        assert "这是一条测试通知。如果你收到了这条消息，说明通知通道已正确配置。" in payload.body
        assert "由 Progress 配置控制台发送。" in payload.body


class TestCardJsonTemplate:
    def test_card_is_v2_with_green_header_and_confirmation_body(self) -> None:
        with override("en"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.CARD_JSON)
        assert payload.content_type is ContentType.CARD_JSON
        card = json.loads(payload.body)
        # v2 invariants
        assert card["schema"] == "2.0"
        assert card["config"]["width_mode"] == "fill"
        # success-state green header with TEST badge + check icon
        assert card["header"]["template"] == "green"
        assert card["header"]["title"]["content"] == "Test Notification"
        assert card["header"]["icon"]["token"] == "check-circle-outlined"
        tag = card["header"]["text_tag_list"][0]
        assert tag["text"]["content"] == "TEST"
        # body.elements (not top-level elements); a centered confirmation + CTA
        tags = [e["tag"] for e in card["body"]["elements"]]
        assert tags[0] == "markdown"
        assert "button" in tags

    def test_card_translates_header_in_chinese(self) -> None:
        with override("zh-hans"):
            payload = JinjaRenderer().render(TestNotificationEvent(), ContentType.CARD_JSON)
        card = json.loads(payload.body)
        assert card["header"]["title"]["content"] == "测试通知"
        # the confirmation body line is localized
        first_md = card["body"]["elements"][0]["content"]
        assert "通知渠道配置正确" in first_md
