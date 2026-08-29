import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import SCREEN_EDGE_VISIBLE_INSET, Tama, WINDOW_PLATFORM_EDGE_GRACE


class StateTransitionTests(unittest.TestCase):
    def _walking_tama(self, direction, center_x):
        tama = Mock()
        tama.is_carrying = False
        tama.is_falling = False
        tama.is_post_land_recovery = False
        tama.walk_direction = direction
        tama.walk_left_frames = [object(), object()]
        tama.walk_right_frames = [object(), object()]
        tama.walk_frame_index = 0
        tama.walk_frame_direction = 1
        tama.current_surface_y = 500
        tama.current_surface_left = 100
        tama.current_surface_right = 900
        tama.interaction_target = None
        tama.walk_target_x = -1000 if direction == "left" else 2000
        tama.width.return_value = 100
        tama.x.return_value = center_x - 50
        tama.y.return_value = 400
        tama._move_during_walk.return_value = True
        return tama

    def test_window_walk_uses_existing_edge_grace_before_right_drop(self):
        tama = self._walking_tama(
            "right",
            900 + WINDOW_PLATFORM_EDGE_GRACE - 10,
        )

        Tama.animate_walk(tama)

        tama._move_during_walk.assert_called_once()
        tama.fall_from_platform.assert_not_called()

    def test_window_walk_drops_after_right_edge_grace(self):
        tama = self._walking_tama(
            "right",
            900 + WINDOW_PLATFORM_EDGE_GRACE,
        )

        Tama.animate_walk(tama)

        tama._move_during_walk.assert_called_once()
        tama.fall_from_platform.assert_called_once()

    def test_window_walk_uses_existing_edge_grace_before_left_drop(self):
        tama = self._walking_tama(
            "left",
            100 - WINDOW_PLATFORM_EDGE_GRACE + 20,
        )

        Tama.animate_walk(tama)

        tama._move_during_walk.assert_called_once()
        tama.fall_from_platform.assert_not_called()

    def test_window_walk_drops_after_left_edge_grace(self):
        tama = self._walking_tama(
            "left",
            100 - WINDOW_PLATFORM_EDGE_GRACE + 10,
        )

        Tama.animate_walk(tama)

        tama._move_during_walk.assert_called_once()
        tama.fall_from_platform.assert_called_once()

    @patch("main.QApplication.screenAt", return_value=None)
    def test_walk_rejects_position_outside_every_screen(self, screen_at):
        tama = Mock()
        tama.width.return_value = 100
        tama.height.return_value = 80
        tama.walk_direction = "right"
        tama._native_screen = None

        moved = Tama._move_during_walk(tama, 300, 400)

        self.assertFalse(moved)
        self.assertEqual(
            (screen_at.call_args.args[0].x(), screen_at.call_args.args[0].y()),
            (399 - SCREEN_EDGE_VISIBLE_INSET, 440),
        )
        tama.move.assert_not_called()
        tama.stop_walking.assert_called_once()

    @patch("main.QApplication.screenAt", return_value=None)
    def test_left_walk_checks_inset_visible_edge(self, screen_at):
        tama = Mock()
        tama.width.return_value = 100
        tama.height.return_value = 80
        tama.walk_direction = "left"
        tama._native_screen = None

        moved = Tama._move_during_walk(tama, 300, 400)

        self.assertFalse(moved)
        self.assertEqual(
            (screen_at.call_args.args[0].x(), screen_at.call_args.args[0].y()),
            (300 + SCREEN_EDGE_VISIBLE_INSET, 440),
        )

    @patch("main.QApplication.screenAt", return_value=Mock())
    def test_walk_allows_position_owned_by_a_connected_screen(self, _screen_at):
        tama = Mock()
        tama.width.return_value = 100
        tama.height.return_value = 80
        tama.walk_direction = "right"
        tama._native_screen = None

        moved = Tama._move_during_walk(tama, 300, 400)

        self.assertTrue(moved)
        tama.move.assert_called_once()
        tama.stop_walking.assert_not_called()

    def test_fall_cancels_every_competing_ground_callback(self):
        tama = Mock()
        tama.is_falling = False
        tama.current_surface_hwnd = 123
        tama.x.return_value = 10
        tama.y.return_value = 20
        tama.get_falling_sprite.return_value = object()

        Tama.fall_from_platform(tama)

        self.assertTrue(tama.is_falling)
        for timer_name in (
            "pose_timer",
            "walk_timer",
            "idle_timer",
            "crouch_start_timer",
            "crouch_timer",
            "crouch_end_timer",
            "sleep_timer",
            "sleep_end_timer",
        ):
            getattr(tama, timer_name).stop.assert_called_once()
        tama.clear_current_surface.assert_called_once()

    def test_queued_landing_timeout_cannot_overwrite_fall(self):
        tama = Mock()
        tama.is_falling = True

        Tama.finish_landing(tama)

        tama.sit_left.assert_not_called()
        tama.sit_right.assert_not_called()
        tama.start_interaction_walk.assert_not_called()

    def test_interaction_is_not_ready_while_airborne(self):
        tama = Mock()
        tama.interaction_target = "food"
        tama.is_falling = True

        self.assertFalse(Tama._interaction_surface_ready(tama))

    def test_interaction_is_not_ready_on_a_window(self):
        tama = Mock()
        tama.interaction_target = "bed"
        tama.is_falling = False
        tama.current_surface_y = 500

        self.assertFalse(Tama._interaction_surface_ready(tama))

    def test_interaction_is_ready_only_when_paws_are_on_taskbar(self):
        tama = Mock()
        tama.interaction_target = "food"
        tama.is_falling = False
        tama.is_post_land_recovery = False
        tama.current_surface_y = None
        sprite = Mock()
        sprite.isNull.return_value = False
        tama.pixmap.return_value = sprite
        tama.y.return_value = 900
        tama.find_visible_bottom.return_value = 79
        tama.get_taskbar_ground.return_value = 979

        self.assertTrue(Tama._interaction_surface_ready(tama))

    def test_interaction_departure_uses_nearest_edge_left(self):
        tama = Mock()
        tama.interaction_target = "food"
        tama.is_falling = False
        tama.is_post_land_recovery = False
        tama.current_surface_y = 400
        tama.current_surface_left = 100
        tama.current_surface_right = 900
        tama.x.return_value = 120
        tama.width.return_value = 100
        tama.interaction_target_x = 1000

        Tama.start_interaction_departure(tama)

        tama.start_walk.assert_called_once_with("left")
        self.assertEqual(tama.walk_target_x, 40)

    def test_interaction_departure_uses_nearest_edge_right(self):
        tama = Mock()
        tama.interaction_target = "bed"
        tama.is_falling = False
        tama.is_post_land_recovery = False
        tama.current_surface_y = 400
        tama.current_surface_left = 100
        tama.current_surface_right = 900
        tama.x.return_value = 800
        tama.width.return_value = 100
        tama.interaction_target_x = 20

        Tama.start_interaction_departure(tama)

        tama.start_walk.assert_called_once_with("right")
        self.assertEqual(tama.walk_target_x, 860)

    def test_interaction_departure_prefers_left_when_edges_are_equally_close(self):
        tama = Mock()
        tama.interaction_target = "food"
        tama.is_falling = False
        tama.is_post_land_recovery = False
        tama.current_surface_y = 400
        tama.current_surface_left = 100
        tama.current_surface_right = 900
        tama.x.return_value = 450
        tama.width.return_value = 100
        tama.interaction_target_x = 1000

        Tama.start_interaction_departure(tama)

        tama.start_walk.assert_called_once_with("left")
        self.assertEqual(tama.walk_target_x, 40)

    def test_interaction_departure_target_follows_moved_window_edge(self):
        tama = Mock()
        tama.walk_direction = "right"
        tama.current_surface_right = 900
        tama.width.return_value = 100

        Tama._update_interaction_departure_target(tama)
        self.assertEqual(tama.walk_target_x, 860)

        tama.current_surface_right = 1200
        Tama._update_interaction_departure_target(tama)
        self.assertEqual(tama.walk_target_x, 1160)

    def test_bonk_landing_uses_locked_recovery(self):
        tama = Mock()
        tama.bonk_drop_pending = True
        tama.get_landing_sprite.return_value = object()

        Tama.land(tama)

        self.assertFalse(tama.bonk_drop_pending)
        self.assertTrue(tama.is_post_land_recovery)
        tama.pose_timer.start.assert_called_once_with(500)

    def test_finish_bonk_recovery_reassesses_interaction(self):
        tama = Mock()
        tama.is_falling = False
        tama.bonk_drop_pending = False
        tama.current_surface_hwnd = 456
        tama.is_post_land_recovery = True
        tama.interaction_target = "food"
        tama._interaction_surface_ready.return_value = False

        Tama.finish_landing(tama)

        self.assertFalse(tama.is_post_land_recovery)
        tama.start_interaction_departure.assert_called_once()

    def test_bonk_fall_marks_navigation_drop(self):
        tama = Mock()
        tama.is_falling = False
        tama.bonk_drop_pending = False
        tama.current_surface_hwnd = 456
        tama.x.return_value = 10
        tama.y.return_value = 20
        tama.get_falling_sprite.return_value = object()

        Tama.fall_from_platform(tama, bonk_navigation=True)

        self.assertTrue(tama.bonk_drop_pending)
        self.assertEqual(tama.bonk_source_surface_hwnd, 456)

    def test_normal_platform_fall_also_ignores_source_window(self):
        tama = Mock()
        tama.is_falling = False
        tama.bonk_drop_pending = False
        tama.current_surface_hwnd = 789
        tama.x.return_value = 10
        tama.y.return_value = 20
        tama.get_falling_sprite.return_value = object()

        Tama.fall_from_platform(tama)

        self.assertFalse(tama.bonk_drop_pending)
        self.assertEqual(tama.bonk_source_surface_hwnd, 789)


if __name__ == "__main__":
    unittest.main()
