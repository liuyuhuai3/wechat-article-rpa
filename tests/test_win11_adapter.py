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
        self.adapter._sleep.assert_called_once_with(0.18)
        self.press_ctrl_w.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
