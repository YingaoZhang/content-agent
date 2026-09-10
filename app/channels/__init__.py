"""Channel registry used by generation jobs."""

from ..schemas import Platform
from .base import Channel
from .wechat import WechatChannel
from .xiaohongshu import XiaohongshuChannel

_channels: dict[Platform, Channel] = {
    Platform.WECHAT: WechatChannel(),
    Platform.XIAOHONGSHU: XiaohongshuChannel(),
}


def get_channel(platform: Platform) -> Channel:
    channel = _channels.get(platform)
    if channel is None:
        raise ValueError(f"暂不支持的内容平台：{platform}")
    return channel
