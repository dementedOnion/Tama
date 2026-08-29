import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import Tama, WINDOW_PLATFORM_EDGE_GRACE


class WindowIdentity:
    def __init__(self, title="", process_name=""):
        self.title = title
        self.process_name = process_name

    def _window_class_name(self, _hwnd):
        return ""

    def _window_title(self, _hwnd):
        return self.title

    def _window_process_name(self, _hwnd):
        return self.process_name

    def _special_platform_kind(self, hwnd, window_class=None):
        return Tama._special_platform_kind(self, hwnd, window_class)


class SpecialPlatformWindowTests(unittest.TestCase):
    def classify(self, window_class, title="", process_name=""):
        identity = WindowIdentity(title, process_name)
        return Tama._special_platform_kind(identity, 123, window_class)

    def test_task_manager_class_is_recognized_without_process_access(self):
        self.assertEqual(
            self.classify("TaskManagerWindow"),
            "task-manager",
        )

    def test_settings_host_is_recognized_by_title(self):
        self.assertEqual(
            self.classify("ApplicationFrameWindow", title="Settings"),
            "settings",
        )

    def test_settings_is_recognized_by_process_when_title_is_localized(self):
        self.assertEqual(
            self.classify(
                "WinUIDesktopWin32WindowClass",
                title="Parametres",
                process_name="systemsettings.exe",
            ),
            "settings",
        )

    def test_unrelated_winui_window_keeps_existing_filter_behavior(self):
        self.assertIsNone(
            self.classify(
                "WinUIDesktopWin32WindowClass",
                title="Another app",
                process_name="another.exe",
            )
        )

    def test_task_manager_debounces_transient_live_exposure_failures(self):
        identity = WindowIdentity(title="Task Manager")
        self.assertEqual(Tama._live_exposure_failure_limit(identity, 123), 3)

    def test_normal_windows_react_to_first_live_exposure_failure(self):
        identity = WindowIdentity(title="Notepad")
        self.assertEqual(Tama._live_exposure_failure_limit(identity, 123), 1)

    def test_task_manager_exposure_probe_avoids_scaled_frame_boundary(self):
        identity = WindowIdentity(title="Task Manager")
        self.assertEqual(Tama._live_exposure_probe_inset(identity, 123), 8)

    def test_normal_window_exposure_probe_keeps_existing_edge_sample(self):
        identity = WindowIdentity(title="Notepad")
        self.assertEqual(Tama._live_exposure_probe_inset(identity, 123), 1)

    def test_edge_grace_accepts_nearby_exposed_point(self):
        identity = WindowIdentity()
        identity.is_window_exposed_at_x = lambda _hwnd, x, _top, _mapping: x == 104

        sample = Tama._window_platform_exposed_sample_x(
            identity, 123, 100, 0, 500, 50, object()
        )

        self.assertEqual(sample, 104)

    def test_edge_grace_rejects_fully_covered_window(self):
        identity = WindowIdentity()
        identity.is_window_exposed_at_x = lambda *_args: False

        sample = Tama._window_platform_exposed_sample_x(
            identity, 123, 100, 0, 500, 50, object()
        )

        self.assertIsNone(sample)

    def test_edge_grace_can_reach_just_inside_window_edge(self):
        identity = WindowIdentity()
        identity.is_window_exposed_at_x = lambda _hwnd, x, _top, _mapping: x == 200

        sample = Tama._window_platform_exposed_sample_x(
            identity,
            123,
            200 - WINDOW_PLATFORM_EDGE_GRACE,
            200,
            600,
            50,
            object(),
        )

        self.assertEqual(sample, 200)


if __name__ == "__main__":
    unittest.main()
