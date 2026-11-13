import math
import time
from dataclasses import dataclass
from datetime import datetime

from astrbot.core.message.components import BaseMessageComponent

from .message_type import MessageType


@dataclass
class MessageMember:
    user_id: str  # 发送者id
    nickname: str | None = None

    def __str__(self) -> str:
        # 使用 f-string 来构建返回的字符串表示形式
        return (
            f"User ID: {self.user_id},"
            f"Nickname: {self.nickname if self.nickname else 'N/A'}"
        )


@dataclass
class Group:
    group_id: str
    """群号"""
    group_name: str | None = None
    """群名称"""
    group_avatar: str | None = None
    """群头像"""
    group_owner: str | None = None
    """群主 id"""
    group_admins: list[str] | None = None
    """群管理员 id"""
    members: list[MessageMember] | None = None
    """所有群成员"""
    member_count: int | None = None
    """Total members, available even when the member list is incomplete."""

    def __str__(self) -> str:
        # 使用 f-string 来构建返回的字符串表示形式
        return (
            f"Group ID: {self.group_id}\n"
            f"Name: {self.group_name if self.group_name else 'N/A'}\n"
            f"Avatar: {self.group_avatar if self.group_avatar else 'N/A'}\n"
            f"Owner ID: {self.group_owner if self.group_owner else 'N/A'}\n"
            f"Admin IDs: {self.group_admins if self.group_admins else 'N/A'}\n"
            f"Member Count: {self.member_count if self.member_count is not None else 'N/A'}\n"
            f"Members Len: {len(self.members) if self.members else 0}\n"
            f"First Member: {self.members[0] if self.members else 'N/A'}\n"
        )


class AstrBotMessage:
    """AstrBot 的消息对象"""

    type: MessageType  # 消息类型
    self_id: str  # 机器人的识别id
    session_id: str  # 会话id。取决于 unique_session 的设置。
    message_id: str  # 消息id
    group: Group | None  # 群组
    sender: MessageMember  # 发送者
    message: list[BaseMessageComponent]  # 消息链使用 Nakuru 的消息链格式
    message_str: str  # 最直观的纯文本消息字符串
    raw_message: object
    timestamp: int  # 消息时间戳
    received_at: float  # Local Unix seconds when the adapter observes the message.
    sent_at: float | None  # Platform send time in Unix seconds, or unknown.

    def __init__(self) -> None:
        self.received_at = time.time()
        self.sent_at = None
        # Preserve the legacy timestamp semantics for existing consumers.
        self.timestamp = int(self.received_at)
        self.group = None

    def set_sent_at(
        self, value: datetime | str | int | float | None, *, milliseconds: bool = False
    ) -> None:
        """Normalize a platform send time without substituting local time.

        Args:
            value: A timezone-aware datetime or numeric Unix timestamp.
            milliseconds: Whether a numeric platform timestamp uses milliseconds.
        """
        self.sent_at = None
        try:
            if isinstance(value, datetime):
                if value.utcoffset() is None:
                    return
                timestamp = value.timestamp()
            elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
                timestamp = float(value) / (1000 if milliseconds else 1)
            else:
                return
            if math.isfinite(timestamp) and timestamp > 0:
                self.sent_at = timestamp
        except (ValueError, OverflowError, OSError):
            return

    def __str__(self) -> str:
        return str(self.__dict__)

    @property
    def group_id(self) -> str:
        """向后兼容的 group_id 属性
        群组id，如果为私聊，则为空
        """
        if self.group:
            return self.group.group_id
        return ""

    @group_id.setter
    def group_id(self, value: str | None) -> None:
        """设置 group_id"""
        if value:
            if self.group:
                self.group.group_id = value
            else:
                self.group = Group(group_id=value)
        else:
            self.group = None
