"""Windows 11 新版微信的 Chromium 标签页适配器。

新版微信的搜一搜、公众号资料页和文章页可能共享同一个
``Chrome_WidgetWin_0`` 窗口句柄，因此窗口激活不等于页面标签激活。
本模块只处理窗口/标签页生命周期，不包含公众号或文章业务规则。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from PIL import Image


class Win11WeChatAdapter:
    """通过页面内容管理新版微信的活动标签。"""

    def __init__(
        self,
        *,
        activate_window: Callable[[int], None],
        capture_window: Callable[[Any], Image.Image],
        validate_profile_header: Callable[[Image.Image, str], dict[str, Any]],
        press_ctrl_tab: Callable[[], None],
        press_ctrl_w: Callable[[], None],
        log_event: Callable[..., None],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._activate_window = activate_window
        self._capture_window = capture_window
        self._validate_profile_header = validate_profile_header
        self._press_ctrl_tab = press_ctrl_tab
        self._press_ctrl_w = press_ctrl_w
        self._log_event = log_event
        self._sleep = sleep

    def activate_profile_tab(
        self,
        window: Any,
        expected_name: str,
        *,
        max_tabs: int = 12,
    ) -> bool:
        """循环标签并用资料页头部名称确认目标标签已置前。"""
        self._activate_window(window.hwnd)
        for tab_index in range(max_tabs):
            screenshot = self._capture_window(window.rect)
            validation = self._validate_profile_header(screenshot, expected_name)
            self._log_event(
                "profile_tab_probe",
                account=expected_name,
                tab_index=tab_index + 1,
                matched=bool(validation.get("matched")),
            )
            if validation.get("matched"):
                return True
            if tab_index + 1 < max_tabs:
                self._press_ctrl_tab()
                # 下一轮会立即截图并校验；只留短暂渲染缓冲，不固定等待 350ms。
                self._sleep(0.18)
        return False

    def close_profile_tab_if_confirmed(
        self,
        window: Any,
        expected_name: str,
    ) -> bool:
        """仅在当前标签再次确认是目标资料页时关闭它。"""
        if not self.activate_profile_tab(window, expected_name):
            self._log_event(
                "profile_tab_close_skipped",
                account=expected_name,
                reason="profile_tab_not_confirmed_before_cleanup",
                action="preserve_all_tabs",
            )
            return False
        self._press_ctrl_w()
        self._sleep(0.15)
        self._log_event(
            "profile_tab_closed",
            account=expected_name,
            method="ctrl-w-active-profile-tab",
        )
        return True
