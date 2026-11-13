import copy
import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from astrbot.builtin_stars.astrbot.group_chat_context import GroupChatContext
from astrbot.core.config.default import DEFAULT_CONFIG
from astrbot.core.platform.message_type import MessageType


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("age", "limit", "platform", "expected"),
    [
        (299, 300, "telegram", True),
        (300, 300, "telegram", True),
        (301, 300, "telegram", False),
        (3600, 0, "telegram", True),
        (3600, 300, "aiocqhttp", True),
        (-1, 300, "telegram", True),
        (0, -1, "telegram", False),
        (0, "300", "telegram", False),
        (0, True, "telegram", False),
        (None, 300, "telegram", False),
    ],
)
async def test_active_reply_uses_telegram_send_time(
    monkeypatch, age, limit, platform, expected
):
    now = 1_700_000_000
    monkeypatch.setattr(
        "astrbot.builtin_stars.astrbot.group_chat_context.time.time", lambda: now
    )
    context = MagicMock()
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["provider_ltm_settings"]["active_reply"].update(
        enable=True, possibility_reply=1.0, telegram_max_message_age=limit
    )
    context.get_config.return_value = config
    group = GroupChatContext(MagicMock(), context)
    event = MagicMock()
    event.get_platform_name.return_value = platform
    event.get_message_type.return_value = MessageType.GROUP_MESSAGE
    event.is_at_or_wake_command = False
    date = (
        datetime.datetime.fromtimestamp(now - age, datetime.timezone.utc)
        if age is not None
        else None
    )
    # A fresh receipt timestamp must not make an old Telegram message replyable.
    event.message_obj = SimpleNamespace(
        timestamp=now,
        raw_message=SimpleNamespace(message=SimpleNamespace(date=date)),
    )
    assert await group.need_active_reply(event) is expected
    event.is_at_or_wake_command = True
    assert await group.need_active_reply(event) is False
