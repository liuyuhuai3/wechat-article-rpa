from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

from wechat_win11_adapter import Win11WeChatAdapter


class Win11AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = SimpleNamespace(hwnd=100, rect=(0, 0, 1600, 1440))
        self.activate_window = Mock()
        self.capture_window = Mock(
            side_effect=[Image.new("RGB", (10, 10), "black"), Image.new("RGB", (10, 10), "white")]
        )
        self.validate_profile_header = Mock(
            side_effect=[{"matched": False}, {"matched": True, "name": "厦门日报"}]
        )
        self.press_ctrl_tab = Mock()
        self.press_ctrl_w = Mock()
        self.log_event = Mock()
        self.adapter = Win11WeChatAdapter(
            activate_window=self.activate_window,
            capture_window=self.capture_window,
            validate_profile_header=self.validate_profile_header,
            press_ctrl_tab=self.press_ctrl_tab,
            press_ctrl_w=self.press_ctrl_w,
            log_event=self.log_event,
            sleep=Mock(),
        )

    def test_profile_tab_is_found_by_content_not_window_handle(self) -> None:
        self.assertTrue(self.adapter.activate_profile_tab(self.window, "厦门日报"))
        self.activate_window.assert_called_once_with(100)
        self.assertEqual(self.validate_profile_header.call_count, 2)
        self.press_ctrl_tab.assert_called_once_with()
        self.adapter._sleep.assert_called_once_with(0.35)
        self.press_ctrl_w.assert_not_called()

    def test_exact_profile_match_skips_search_page_detection(self) -> None:
        inspect_search = Mock()
        adapter = Win11WeChatAdapter(
            activate_window=self.activate_window,
            capture_window=Mock(return_value=Image.new("RGB", (10, 10), "black")),
            validate_profile_header=Mock(
                return_value={
                    "matched": True,
                    "name": "厦门日报",
                    "profile_structure_found": True,
                }
            ),
            press_ctrl_tab=self.press_ctrl_tab,
            press_ctrl_w=self.press_ctrl_w,
            log_event=self.log_event,
            sleep=Mock(),
            inspect_search_page=inspect_search,
        )

        self.assertTrue(adapter.activate_profile_tab(self.window, "厦门日报"))
        inspect_search.assert_not_called()
        self.press_ctrl_tab.assert_not_called()

    def test_similar_tab_icons_do_not_end_scan_early(self) -> None:
        self.capture_window.side_effect = None
        self.capture_window.return_value = Image.new("RGB", (10, 10), "black")
        self.validate_profile_header.side_effect = lambda image, name: {"matched": False}

        self.assertFalse(self.adapter.activate_profile_tab(self.window, "厦门晚报", max_tabs=4))
        self.assertEqual(self.press_ctrl_tab.call_count, 3)
        self.assertTrue(
            any(
                call.args[0] == "profile_tab_scan_limit_reached"
                for call in self.log_event.call_args_list
            )
        )

    def test_profile_close_is_skipped_when_no_profile_tab_is_confirmed(self) -> None:
        self.capture_window.side_effect = None
        self.capture_window.return_value = Image.new("RGB", (10, 10), "black")
        self.validate_profile_header.side_effect = lambda image, name: {"matched": False}
        self.assertFalse(
            self.adapter.close_profile_tab_if_confirmed(
                self.window, "厦门日报"
            )
        )
        self.press_ctrl_w.assert_not_called()
        self.assertTrue(
            any(call.args[0] == "profile_tab_close_skipped" for call in self.log_event.call_args_list)
        )

    def test_scrolled_profile_returns_home_before_exact_identity_check(self) -> None:
        press_home = Mock()
        stable_capture = Mock(
            side_effect=[
                Image.new("RGB", (10, 10), "black"),
                Image.new("RGB", (10, 10), "white"),
            ]
        )
        validate = Mock(
            side_effect=[
                {
                    "matched": False,
                    "profile_structure_found": True,
                    "reason": "资料页结构成立但名称不可见",
                },
                {"matched": True, "name": "厦门晚报"},
            ]
        )
        adapter = Win11WeChatAdapter(
            activate_window=self.activate_window,
            capture_window=self.capture_window,
            validate_profile_header=validate,
            press_ctrl_tab=self.press_ctrl_tab,
            press_ctrl_w=self.press_ctrl_w,
            log_event=self.log_event,
            sleep=Mock(),
            press_ctrl_home=press_home,
            wait_for_stable_frames=stable_capture,
        )

        self.assertTrue(adapter.activate_profile_tab(self.window, "厦门晚报"))
        press_home.assert_called_once_with()
        self.press_ctrl_tab.assert_not_called()

    def test_loading_intermediate_retries_current_tab_before_switching(self) -> None:
        validate = Mock(
            side_effect=[
                {
                    "matched": False,
                    "reason": "公众号资料页整屏未找到名称匹配",
                    "observed_header_candidates": ["Q"],
                    "structural_terms": [],
                    "search_page_evidence": [],
                },
                {"matched": True, "name": "厦门日报"},
            ]
        )
        adapter = Win11WeChatAdapter(
            activate_window=self.activate_window,
            capture_window=Mock(return_value=Image.new("RGB", (10, 10), "black")),
            validate_profile_header=validate,
            press_ctrl_tab=self.press_ctrl_tab,
            press_ctrl_w=self.press_ctrl_w,
            log_event=self.log_event,
            sleep=Mock(),
        )

        self.assertTrue(adapter.activate_profile_tab(self.window, "厦门日报"))
        self.press_ctrl_tab.assert_not_called()
        self.assertEqual(validate.call_count, 2)

    def test_absence_requires_return_to_same_search_workspace(self) -> None:
        inspect_search = Mock(side_effect=[True, False, True])
        adapter = Win11WeChatAdapter(
            activate_window=self.activate_window,
            capture_window=Mock(return_value=Image.new("RGB", (10, 10), "black")),
            validate_profile_header=Mock(return_value={"matched": False}),
            press_ctrl_tab=self.press_ctrl_tab,
            press_ctrl_w=self.press_ctrl_w,
            log_event=self.log_event,
            sleep=Mock(),
            inspect_search_page=inspect_search,
            same_search_page=Mock(return_value=True),
        )

        self.assertFalse(adapter.activate_profile_tab(self.window, "不存在的账号", max_tabs=8))
        self.assertTrue(adapter.last_scan_saw_search)
        self.assertTrue(adapter.last_scan_completed_cycle)
        self.assertEqual(self.press_ctrl_tab.call_count, 2)

    def test_inventory_registers_all_accounts_in_one_tab_cycle(self) -> None:
        identify = Mock(
            side_effect=[
                {
                    "matched": False,
                    "profile_structure_found": False,
                    "search_page_evidence": ["搜索"],
                },
                {
                    "matched": True,
                    "account": "厦门日报",
                    "name": "厦门日报",
                    "profile_structure_found": True,
                    "header_identity_visible": True,
                },
                {
                    "matched": True,
                    "account": "厦门晚报",
                    "name": "厦门晚报",
                    "profile_structure_found": True,
                    "header_identity_visible": True,
                },
                {
                    "matched": False,
                    "profile_structure_found": False,
                    "search_page_evidence": ["搜索"],
                },
            ]
        )
        adapter = Win11WeChatAdapter(
            activate_window=self.activate_window,
            capture_window=Mock(return_value=Image.new("RGB", (10, 10), "black")),
            validate_profile_header=self.validate_profile_header,
            press_ctrl_tab=self.press_ctrl_tab,
            press_ctrl_w=self.press_ctrl_w,
            log_event=self.log_event,
            sleep=Mock(),
            identify_profile_account=identify,
            inspect_search_page=Mock(side_effect=[True, True]),
            same_search_page=Mock(return_value=True),
        )

        result = adapter.inventory_profile_tabs(
            self.window,
            ["厦门日报", "厦门晚报"],
            max_tabs=8,
        )

        self.assertTrue(result["completed_cycle"])
        self.assertEqual(result["profiles_found"], ["厦门日报", "厦门晚报"])
        self.assertEqual(identify.call_count, 4)
        self.assertEqual(self.press_ctrl_tab.call_count, 3)

    def test_inventory_does_not_home_when_other_identity_text_is_visible(self) -> None:
        press_home = Mock()
        identify = Mock(
            return_value={
                "matched": False,
                "profile_structure_found": True,
                "header_identity_visible": True,
                "observed_header_candidates": ["未知公众号"],
            }
        )
        adapter = Win11WeChatAdapter(
            activate_window=self.activate_window,
            capture_window=Mock(return_value=Image.new("RGB", (10, 10), "black")),
            validate_profile_header=self.validate_profile_header,
            press_ctrl_tab=self.press_ctrl_tab,
            press_ctrl_w=self.press_ctrl_w,
            log_event=self.log_event,
            sleep=Mock(),
            press_ctrl_home=press_home,
            identify_profile_account=identify,
        )

        adapter.inventory_profile_tabs(self.window, ["厦门日报"], max_tabs=1)

        press_home.assert_not_called()


if __name__ == "__main__":
    unittest.main()
