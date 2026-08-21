import unittest

from webview_ui import (
    DEFAULT_WINDOW_SIZE,
    MIN_WINDOW_SIZE,
    resolve_window_size,
    sanitize_window_size,
)


class TestSanitizeWindowSize(unittest.TestCase):
    def test_valid_size_kept(self):
        self.assertEqual(sanitize_window_size(1450, 850), (1450, 850))

    def test_zero_size_ignored(self):
        # WebView2 销毁路径的残留事件：0x0 不得进入窗口尺寸
        self.assertIsNone(sanitize_window_size(0, 0))

    def test_tiny_width_ignored(self):
        self.assertIsNone(sanitize_window_size(50, 850))

    def test_tiny_height_ignored(self):
        self.assertIsNone(sanitize_window_size(1450, 30))

    def test_boundary_min_kept(self):
        self.assertEqual(
            sanitize_window_size(MIN_WINDOW_SIZE, MIN_WINDOW_SIZE),
            (MIN_WINDOW_SIZE, MIN_WINDOW_SIZE),
        )

    def test_below_min_ignored(self):
        self.assertIsNone(sanitize_window_size(MIN_WINDOW_SIZE - 1, 850))

    def test_non_numeric_ignored(self):
        self.assertIsNone(sanitize_window_size("tiny", 850))

    def test_non_finite_ignored(self):
        # int(inf) 抛 OverflowError，同样视为损坏尺寸
        self.assertIsNone(sanitize_window_size(float("inf"), 850))
        self.assertIsNone(sanitize_window_size(float("-inf"), 850))


class TestResolveWindowSize(unittest.TestCase):
    def test_valid_conf_size_kept(self):
        self.assertEqual(resolve_window_size(1450, 850), (1450, 850))

    def test_broken_conf_falls_back_to_default(self):
        # conf.yml 已被旧 bug 写坏（极小/零尺寸）时兜底到默认启动尺寸
        self.assertEqual(resolve_window_size(0, 0), DEFAULT_WINDOW_SIZE)
        self.assertEqual(resolve_window_size(50, 850), DEFAULT_WINDOW_SIZE)
        self.assertEqual(resolve_window_size("tiny", 850), DEFAULT_WINDOW_SIZE)

    def test_non_finite_conf_falls_back_to_default(self):
        self.assertEqual(resolve_window_size(float("inf"), 850), DEFAULT_WINDOW_SIZE)


if __name__ == "__main__":
    unittest.main()
