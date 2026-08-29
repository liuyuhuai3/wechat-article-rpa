"""公众号搜索结果识别的保守匹配回归测试。"""

from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from wechat_profile_ocr import WeChatProfileOCR, _account_name_match
from wechat_visual_rpa import classify_collection_error, resolve_search_account_name


class AccountMatchingTests(unittest.TestCase):
    def test_ascii_case_difference_is_accepted(self) -> None:
        matched, method = _account_name_match("ComfyUI中文", "ComfyUi中文")
        self.assertTrue(matched)
        self.assertEqual(method, "ascii-case-ignored")

    def test_i_and_l_ocr_confusion_is_accepted_only_when_other_chars_match(self) -> None:
        matched, method = _account_name_match("海螺AI-MiniMaxHub", "海螺Al-MiniMaxHub")
        self.assertTrue(matched)
        self.assertEqual(method, "ocr-i-l-confusion")

    def test_known_bili_ocr_confusion_is_accepted(self) -> None:
        matched, method = _account_name_match("哔哩哔哩技术", "哗哩哗哩技术")
        self.assertTrue(matched)
        self.assertEqual(method, "ocr-chinese-confusion")

    def test_known_qwen_ocr_confusion_is_accepted(self) -> None:
        matched, method = _account_name_match("千问大模型", "干问大模型")
        self.assertTrue(matched)
        self.assertEqual(method, "ocr-chinese-confusion")

    def test_ai_prefix_i_omission_is_accepted(self) -> None:
        matched, method = _account_name_match("AI新工匠", "A新工匠")
        self.assertTrue(matched)
        self.assertEqual(method, "ocr-ai-prefix-i-omitted")

    def test_unrelated_similar_name_stays_rejected(self) -> None:
        matched, method = _account_name_match("ComfyUI中文", "ComfyUl中文站")
        self.assertFalse(matched)
        self.assertEqual(method, "")

    def test_alias_only_changes_the_search_name(self) -> None:
        # 开源包不携带用户私有的别名配置，测试时使用临时夹具验证解析逻辑。
        with tempfile.TemporaryDirectory() as tmp:
            alias_path = Path(tmp) / "account_aliases.json"
            alias_path.write_text(
                json.dumps({"通义千问Qwen": "千问大模型", "通义大模型": "千问大模型"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch("wechat_visual_rpa.ACCOUNT_ALIASES_PATH", alias_path):
                self.assertEqual(resolve_search_account_name("通义千问Qwen"), "千问大模型")
                self.assertEqual(resolve_search_account_name("通义大模型"), "千问大模型")
                self.assertEqual(resolve_search_account_name("不存在的账号"), "不存在的账号")

    def test_verified_identity_suffix_is_accepted(self) -> None:
        matched, method = _account_name_match("书生Intern", "书生Intern事业单位")
        self.assertTrue(matched)
        self.assertEqual(method, "safe-suffix-alias")

    def test_filter_and_account_not_found_errors_are_separated(self) -> None:
        self.assertEqual(
            classify_collection_error(
                RuntimeError("二级公众号筛选未确认选中：下划线未显示")
            ),
            "account_filter",
        )
        self.assertEqual(
            classify_collection_error(
                RuntimeError("公众号筛选已选中，但未找到可确认的同名公众号：AI新工匠")
            ),
            "account_not_found",
        )

    def test_personal_subject_with_original_count_stays_valid_after_public_filter(self) -> None:
        # 微信公众号二级筛选后，卡片的“个人”是主体类型，不代表它不是公众号。
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)
        ocr._rows = lambda _image: [
            {
                "text": "AI新工匠",
                "normalized": "AI新工匠",
                "left": 80.0,
                "right": 200.0,
                "bottom": 300.0,
                "center_x": 140.0,
                "center_y": 280.0,
                "confidence": 0.99,
            },
            {
                "text": "个人",
                "normalized": "个人",
                "left": 80.0,
                "right": 120.0,
                "bottom": 330.0,
                "center_x": 100.0,
                "center_y": 320.0,
                "confidence": 0.99,
            },
            {
                "text": "127篇原创内容",
                "normalized": "127篇原创内容",
                "left": 80.0,
                "right": 210.0,
                "bottom": 360.0,
                "center_x": 145.0,
                "center_y": 350.0,
                "confidence": 0.99,
            },
        ]
        result = ocr.locate_search_result(Image.new("RGB", (1000, 1000)), "AI新工匠")
        self.assertTrue(result["found"])
        self.assertIn("127篇原创内容", result["official_evidence"])

    def test_win11_all_page_account_section_is_detected(self) -> None:
        """新版 Win11 默认“全部”页应直接命中公众号账号区块。"""
        ocr = WeChatProfileOCR.__new__(WeChatProfileOCR)

        def row(text: str, left: float, center_y: float, width: float = 120) -> dict[str, object]:
            return {
                "text": text,
                "normalized": "".join(text.split()),
                "left": left,
                "right": left + width,
                "top": center_y - 15,
                "bottom": center_y + 15,
                "center_x": left + width / 2,
                "center_y": center_y,
                "confidence": 0.99,
            }

        ocr._rows = lambda _image: [
            row("全部", 80, 150, 60),
            row("账号", 380, 150, 60),
            row("厦门日报-账号", 80, 390, 220),
            row("厦门日报", 230, 500, 140),
            row("公众号", 230, 550, 90),
            row("378篇原创内容 34分钟前更新", 230, 590, 260),
        ]

        result = ocr.locate_all_page_account_result(
            Image.new("RGB", (1568, 1439)), "厦门日报"
        )

        self.assertTrue(result["found"], result)
        self.assertEqual(result["layout"], "all-account-section")
        self.assertIn("公众号", result["official_evidence"])
        self.assertIn("378篇原创内容 34分钟前更新", result["original_content_evidence"])


if __name__ == "__main__":
    unittest.main()
