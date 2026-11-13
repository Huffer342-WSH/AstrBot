import copy
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import dingtalk_stream
import pytest
from aiocqhttp import Event

import astrbot.api  # noqa: F401
from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext
from astrbot.core.config.default import DEFAULT_CONFIG
from astrbot.core.platform.astrbot_message import AstrBotMessage
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.platform.register import platform_registry
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot.core.platform.sources.dingtalk.dingtalk_adapter import (
    DingtalkPlatformAdapter,
)
from astrbot.core.platform.sources.lark.lark_adapter import LarkPlatformAdapter
from astrbot.core.platform.sources.slack.slack_adapter import SlackAdapter
from astrbot.core.platform.sources.telegram.tg_adapter import TelegramPlatformAdapter
from astrbot.core.utils.migra_helper import migrate_config_on_load
from tests.fixtures.helpers import create_mock_update


@pytest.mark.parametrize(
    "value,milliseconds,expected",
    [
        (1700000000, False, 1700000000),
        ("1700000000.125", False, 1700000000.125),
        ("1700000000125", True, 1700000000.125),
        (
            datetime.datetime(2023, 11, 14, 22, 13, 20, tzinfo=datetime.timezone.utc),
            False,
            1700000000,
        ),
        (datetime.datetime(2023, 11, 14, 22, 13, 20), False, None),
        (None, False, None),
        ("bad", False, None),
        ("", False, None),
        (True, False, None),
        (False, False, None),
        (-1, False, None),
        (0, False, None),
        ("nan", False, None),
        ("inf", False, None),
        (10**400, False, None),
    ],
)
def test_times_remain_distinct(monkeypatch, value, milliseconds, expected):
    monkeypatch.setattr(
        "astrbot.core.platform.astrbot_message.time.time", lambda: 1800000000.5
    )
    message = AstrBotMessage()
    message.set_sent_at(value, milliseconds=milliseconds)
    assert message.received_at == 1800000000.5
    assert message.timestamp == 1800000000
    assert message.sent_at == expected
    message.timestamp = 123
    assert message.received_at == 1800000000.5
    assert message.sent_at == expected
    message.set_sent_at(None)
    assert message.sent_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform", ["telegram", "aiocqhttp", "lark", "dingtalk", "slack"]
)
@pytest.mark.parametrize("valid", [True, False])
async def test_native_send_times_in_real_converters(monkeypatch, platform, valid):
    clock = [1800000000.5]
    monkeypatch.setattr(
        "astrbot.core.platform.astrbot_message.time.time", lambda: clock[0]
    )
    sent = 1700000000 if valid else None
    if platform == "telegram":
        adapter = TelegramPlatformAdapter.__new__(TelegramPlatformAdapter)
        update = create_mock_update(chat_type="private")
        update.message.date = (
            datetime.datetime.fromtimestamp(sent, datetime.timezone.utc)
            if sent
            else None
        )
        context = SimpleNamespace(bot=SimpleNamespace(username="bot"))
        result = await adapter.convert_message(update, context)
    elif platform == "aiocqhttp":
        adapter = AiocqhttpAdapter.__new__(AiocqhttpAdapter)
        event = Event.from_payload(
            dict(
                post_type="message",
                message_type="group",
                self_id=1,
                user_id=2,
                group_id=3,
                sender={"user_id": 2, "nickname": "User"},
                message_id=4,
                message=[{"type": "text", "data": {"text": "hello"}}],
                time=sent,
            )
        )
        result = await adapter.convert_message(event)
    elif platform == "dingtalk":
        adapter = DingtalkPlatformAdapter.__new__(DingtalkPlatformAdapter)
        message = dingtalk_stream.ChatbotMessage.from_dict(
            dict(
                conversationId="group",
                conversationType="2",
                createAt=sent * 1000 if sent else None,
                msgId="message",
                senderId="sender",
                senderNick="Sender",
                chatbotUserId="bot",
                msgtype="text",
                text={"content": "hello"},
            )
        )
        result = await adapter.convert_msg(message)
    elif platform == "lark":
        adapter = LarkPlatformAdapter.__new__(LarkPlatformAdapter)
        adapter.bot_open_id, adapter.bot_name = "bot", "Bot"
        adapter._user_name_cache = {"sender": ("Sender", 1900000000)}
        adapter.handle_msg = AsyncMock()
        event = SimpleNamespace(
            event=SimpleNamespace(
                sender=SimpleNamespace(
                    sender_id=SimpleNamespace(open_id="sender"), sender_type="user"
                ),
                message=SimpleNamespace(
                    create_time=str(sent * 1000) if sent else None,
                    chat_type="group",
                    chat_id="group",
                    parent_id=None,
                    mentions=[],
                    content='{"text":"hello"}',
                    message_id="message",
                    message_type="text",
                ),
            )
        )
        await adapter.convert_msg(event)
        result = adapter.handle_msg.await_args.args[0]
    else:
        adapter = SlackAdapter.__new__(SlackAdapter)
        adapter.bot_self_id = "bot"

        async def users_info(**kwargs):
            clock[0] += 60
            return {"user": {"name": "User"}}

        adapter.web_client = SimpleNamespace(
            users_info=users_info,
            conversations_info=AsyncMock(return_value={"channel": {"is_im": False}}),
        )
        result = await adapter.convert_message(
            dict(
                user="user",
                channel="group",
                text="hello",
                ts=str(sent) if sent else None,
            )
        )
    assert result.received_at == 1800000000.5
    assert result.sent_at == sent
    assert result.timestamp == (
        sent if valid and platform in {"lark", "dingtalk", "slack"} else 1800000000
    )
    assert next(
        m for m in platform_registry if m.name == platform
    ).support_message_sent_at
    if platform in {"telegram", "lark", "dingtalk"}:
        adapter.config = {"id": "test"}
        assert adapter.meta().support_message_sent_at


@pytest.mark.asyncio
async def test_album_retains_first_receipt_time(monkeypatch):
    clock = [1800000000.5]
    monkeypatch.setattr(
        "astrbot.core.platform.astrbot_message.time.time", lambda: clock[0]
    )
    adapter = TelegramPlatformAdapter.__new__(TelegramPlatformAdapter)
    adapter.media_group_cache = {}
    adapter.media_group_max_wait, adapter.media_group_timeout = 10, 1
    adapter.scheduler = MagicMock()
    adapter.handle_msg = AsyncMock()
    update = create_mock_update(chat_type="private", media_group_id="album")
    update.message.date = datetime.datetime.fromtimestamp(
        1700000000, datetime.timezone.utc
    )
    await adapter.handle_media_group_message(
        update, SimpleNamespace(bot=SimpleNamespace(username="bot"))
    )
    clock[0] += 30
    await adapter.process_media_group("album")
    message = adapter.handle_msg.await_args.args[0]
    assert message.received_at == 1800000000.5
    assert message.sent_at == 1700000000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "age,limit,supported,expected",
    [
        (299, 300, True, True),
        (300, 300, True, True),
        (301, 300, True, False),
        (3600, 0, True, True),
        (-1, 300, True, True),
        (None, 300, True, False),
        (None, 300, False, True),
        (3600, 300, False, True),
        (0, -1, True, False),
        (0, "300", True, False),
        (0, True, True, False),
    ],
)
async def test_generic_age_filter(monkeypatch, age, limit, supported, expected):
    now = 1800000000
    monkeypatch.setattr(
        "astrbot.builtin_stars.astrbot.group_chat_context.time.time", lambda: now
    )
    context = MagicMock()
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["provider_ltm_settings"]["active_reply"].update(
        enable=True, possibility_reply=1.0, max_message_age=limit
    )
    context.get_config.return_value = config
    event = MagicMock()
    event.platform_meta = PlatformMetadata(
        "test", "Test", "test", support_message_sent_at=supported
    )
    event.get_message_type.return_value = MessageType.GROUP_MESSAGE
    event.is_at_or_wake_command = False
    event.message_obj = AstrBotMessage()
    event.message_obj.set_sent_at(now - age if age is not None else None)
    group = GroupChatContext(MagicMock(), context)
    assert await group.need_active_reply(event) is expected
    event.is_at_or_wake_command = True
    assert not await group.need_active_reply(event)
    event.is_at_or_wake_command = False
    event.get_message_type.return_value = MessageType.FRIEND_MESSAGE
    assert not await group.need_active_reply(event)


@pytest.mark.parametrize("explicit", [None, 0, 100])
def test_legacy_age_migration(tmp_path, explicit):
    active = {"telegram_max_message_age": 300}
    if explicit is not None:
        active["max_message_age"] = explicit
    config = {"provider_ltm_settings": {"active_reply": active}}
    migrate_config_on_load(config, tmp_path / "config.json")
    assert active["max_message_age"] == (300 if explicit is None else explicit)
    assert "telegram_max_message_age" not in active
    snapshot = copy.deepcopy(config)
    migrate_config_on_load(config, tmp_path / "config.json")
    assert config == snapshot


def test_unsupported_platform_defaults_to_false():
    assert not PlatformMetadata("other", "Other", "other").support_message_sent_at


def test_legacy_age_survives_config_integrity_cleanup(tmp_path):
    import json

    from astrbot.core.config.astrbot_config import AstrBotConfig

    config = copy.deepcopy(DEFAULT_CONFIG)
    active = config["provider_ltm_settings"]["active_reply"]
    active.pop("max_message_age")
    active["telegram_max_message_age"] = 300
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(config))
    loaded = AstrBotConfig(str(path))
    assert loaded["provider_ltm_settings"]["active_reply"]["max_message_age"] == 300
    assert (
        "telegram_max_message_age"
        not in loaded["provider_ltm_settings"]["active_reply"]
    )
    reloaded = AstrBotConfig(str(path))
    assert reloaded["provider_ltm_settings"]["active_reply"]["max_message_age"] == 300
