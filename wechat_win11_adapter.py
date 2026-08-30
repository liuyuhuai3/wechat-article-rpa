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
        press_ctrl_home: Callable[[], None] | None = None,
        wait_for_stable_frames: Callable[[Any], Image.Image] | None = None,
        inspect_search_page: Callable[[Image.Image], bool] | None = None,
        same_search_page: Callable[[Image.Image, Image.Image], bool] | None = None,
    ) -> None:
        self._activate_window = activate_window
        self._capture_window = capture_window
        self._validate_profile_header = validate_profile_header
        self._press_ctrl_tab = press_ctrl_tab
        self._press_ctrl_w = press_ctrl_w
        self._log_event = log_event
        self._sleep = sleep
        self._press_ctrl_home = press_ctrl_home
        self._wait_for_stable_frames = wait_for_stable_frames
        self._inspect_search_page = inspect_search_page
        self._same_search_page = same_search_page
        self.last_switch_steps = 0
        self.last_scan_completed_cycle = False
        self.last_scan_saw_search = False

    @staticmethod
    def _is_sparse_intermediate(validation: dict[str, Any]) -> bool:
        return bool(
            not validation.get("matched")
            and "observed_header_candidates" in validation
            and not validation.get("profile_structure_found")
            and not validation.get("structural_terms")
            and not validation.get("search_page_evidence")
            and not validation.get("name_candidates")
            and len(validation.get("observed_header_candidates") or []) <= 1
        )

    def _stable_capture(self, window: Any) -> Image.Image:
        if self._wait_for_stable_frames is not None:
            return self._wait_for_stable_frames(window.rect)
        return self._capture_window(window.rect)

    def _validate_current_profile(
        self,
        window: Any,
        expected_name: str,
    ) -> tuple[Image.Image, dict[str, Any]]:
        screenshot = self._stable_capture(window)
        validation = self._validate_profile_header(screenshot, expected_name)

        # 页面结构已经成立但名称被滚动出视口时，先回到顶部再做身份校验。
        if (
            not validation.get("matched")
            and validation.get("profile_structure_found")
            and self._press_ctrl_home is not None
        ):
            self._press_ctrl_home()
            screenshot = self._stable_capture(window)
            validation = self._validate_profile_header(screenshot, expected_name)
            self._log_event(
                "profile_identity_retried_after_home",
                account=expected_name,
                matched=bool(validation.get("matched")),
                reason=validation.get("reason"),
            )

        # 空白、加载动画或只有极少文字时留在当前标签重试，不能立即切走。
        for retry_index in range(2):
            if not self._is_sparse_intermediate(validation):
                break
            self._sleep(0.35)
            screenshot = self._stable_capture(window)
            validation = self._validate_profile_header(screenshot, expected_name)
            self._log_event(
                "profile_tab_intermediate_retry",
                account=expected_name,
                retry=retry_index + 1,
                matched=bool(validation.get("matched")),
                reason=validation.get("reason"),
            )
        return screenshot, validation

    def activate_profile_tab(
        self,
        window: Any,
        expected_name: str,
        *,
        max_tabs: int = 96,
    ) -> bool:
        """从当前活动标签开始有界扫描，并按整页资料身份确认目标标签。

        不再用压缩标签栏的相似图标判断“回到起点”。多个公众号标签在 Win11
        微信中常显示成完全相同的蓝色图标，该判断会在第二个标签就提前终止。
        """
        self._activate_window(window.hwnd)
        self.last_switch_steps = 0
        self.last_scan_completed_cycle = False
        self.last_scan_saw_search = False
        search_anchor: Image.Image | None = None
        tabs_since_search = 0
        for probe_index in range(max_tabs):
            screenshot, validation = self._validate_current_profile(window, expected_name)
            # 目标账号名称和资料页结构已经同时通过时立即成功返回。此时再对
            # 同一截图识别搜索框/账号分类/搜一搜首页既不增加安全证据，又会
            # 触发多轮本地 OCR，显著拖慢启动预热和后续轮询。
            if validation.get("matched"):
                self._log_event(
                    "profile_tab_probe",
                    account=expected_name,
                    probe_index=probe_index + 1,
                    tab_index=probe_index + 1,
                    scan_origin="current_active_tab",
                    matched=True,
                    observed_name=validation.get("name"),
                    reason=validation.get("reason"),
                    search_page=False,
                    profile_structure_found=True,
                    search_detection_skipped=True,
                )
                self.last_switch_steps = probe_index
                return True

            # 只有资料页身份不匹配时，才需要识别搜一搜工作面并维护绕圈锚点。
            is_search = bool(
                self._inspect_search_page is not None
                and self._inspect_search_page(screenshot)
            )
            if is_search:
                self.last_scan_saw_search = True
                if search_anchor is None:
                    search_anchor = screenshot
                    tabs_since_search = 0
                elif tabs_since_search > 0 and (
                    self._same_search_page is None
                    or self._same_search_page(search_anchor, screenshot)
                ):
                    self.last_scan_completed_cycle = True
                    self._log_event(
                        "profile_tab_scan_cycle_completed",
                        account=expected_name,
                        probes=probe_index + 1,
                        matched=False,
                    )
                    return False
            self._log_event(
                "profile_tab_probe",
                account=expected_name,
                probe_index=probe_index + 1,
                # 兼容既有日志消费者；它是相对探测次数，不是顶部绝对标签序号。
                tab_index=probe_index + 1,
                scan_origin="current_active_tab",
                matched=bool(validation.get("matched")),
                observed_name=validation.get("name"),
                reason=validation.get("reason"),
                search_page=is_search,
                profile_structure_found=bool(validation.get("profile_structure_found")),
            )
            if probe_index + 1 < max_tabs:
                self._press_ctrl_tab()
                if search_anchor is not None:
                    tabs_since_search += 1
                # 新版微信的内嵌页切换后需要等待标签高亮和页面头部同步更新。
                self._sleep(0.35)
        self._log_event(
            "profile_tab_scan_limit_reached",
            account=expected_name,
            probes=max_tabs,
            search_seen=self.last_scan_saw_search,
            completed_cycle=self.last_scan_completed_cycle,
            reason="tab_cycle_not_observed_before_safety_limit",
        )
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
