import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import (
    BED_SIT_TO_SLEEP_MS,
    Qt,
    SCREEN_EDGE_VISIBLE_INSET,
    TURN_FRAME_MS,
    TURN_PIVOT_STEP_PIXELS,
    Tama,
    WINDOW_PLATFORM_EDGE_GRACE,
)


class StateTransitionTests(unittest.TestCase):
    def _turning_tama(self, facing):
        tama = Mock()
        tama.facing_direction = facing
        tama.is_turning = False
        tama.is_carrying = False
        tama.is_falling = False
        tama.is_sleeping = False
        tama.is_waking = False
        tama.is_post_land_recovery = False
        tama.interaction_target = None
        tama.interaction_target_x = None
        tama.interaction_ui = None
        tama.interaction_has_arrived = False
        tama.interaction_final_facing = None
        tama.interaction_arrival_settled = False
        tama.food_arrival_side = None
        tama.current_surface_y = None
        tama.current_surface_left = None
        tama.current_surface_right = None
        tama.x.return_value = 100
        tama.y.return_value = 200
        tama.width.return_value = 80
        tama.turn_frames = [object() for _ in range(7)]
        tama.cancel_turn.side_effect = lambda: Tama.cancel_turn(tama)
        tama._show_turn_frame.side_effect = lambda: Tama._show_turn_frame(tama)
        tama._food_eating_anchor_x.side_effect = (
            lambda side: Tama._food_eating_anchor_x(tama, side)
        )
        return tama

    def test_left_walk_to_right_walk_reversal_uses_turn_then_resumes(self):
        tama = self._turning_tama("left")

        Tama.start_walk(tama, "right")

        tama.start_turn.assert_called_once()
        direction, = tama.start_turn.call_args.args
        on_complete = tama.start_turn.call_args.kwargs["on_complete"]
        self.assertEqual(direction, "right")
        self.assertTrue(tama.start_turn.call_args.kwargs["pivot_step"])
        tama._begin_walk.assert_not_called()

        on_complete()

        tama._begin_walk.assert_called_once_with(
            "right",
            after_turn=True,
        )

    def test_right_walk_to_left_walk_reversal_uses_turn_then_resumes(self):
        tama = self._turning_tama("right")

        Tama.start_walk(tama, "left")

        tama.start_turn.assert_called_once()
        direction, = tama.start_turn.call_args.args
        on_complete = tama.start_turn.call_args.kwargs["on_complete"]
        self.assertEqual(direction, "left")
        self.assertTrue(tama.start_turn.call_args.kwargs["pivot_step"])
        tama._begin_walk.assert_not_called()

        on_complete()

        tama._begin_walk.assert_called_once_with(
            "left",
            after_turn=True,
        )

    def test_same_direction_walk_starts_without_turning(self):
        tama = self._turning_tama("left")

        Tama.start_walk(tama, "left")

        tama.start_turn.assert_not_called()
        tama._begin_walk.assert_called_once_with("left")

    def test_post_turn_walk_cycle_starts_after_duplicated_endpoint(self):
        for direction in ("left", "right"):
            with self.subTest(direction=direction):
                tama = self._turning_tama(direction)
                tama.walk_left_frames = [object(), object(), object()]
                tama.walk_right_frames = [object(), object(), object()]
                tama.current_surface_y = 500
                tama.x.return_value = 500

                with patch("main.random.randint", return_value=100):
                    Tama._begin_walk(
                        tama,
                        direction,
                        after_turn=True,
                    )

                self.assertEqual(tama.walk_frame_index, 1)
                self.assertEqual(tama.walk_frame_direction, 1)
                tama.walk_timer.start.assert_called_once_with(140)
                tama.animate_walk.assert_called_once_with()

    def test_normal_walk_waits_for_its_first_timer_tick(self):
        tama = self._turning_tama("left")
        tama.walk_left_frames = [object(), object(), object()]
        tama.walk_right_frames = [object(), object(), object()]
        tama.current_surface_y = 500
        tama.x.return_value = 500

        with patch("main.random.randint", return_value=100):
            Tama._begin_walk(tama, "left")

        tama.walk_timer.start.assert_called_once_with(140)
        tama.animate_walk.assert_not_called()

    def test_interaction_walk_reversal_uses_guarded_turn(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "food"
        tama.interaction_target_x = 700
        tama.current_surface_y = None
        tama._interaction_surface_ready.return_value = True
        tama.x.return_value = 100
        tama.width.return_value = 100

        Tama.start_interaction_walk(tama, resume_immediately=True)

        tama._start_interaction_turn.assert_called_once()
        direction, continuation = tama._start_interaction_turn.call_args.args
        self.assertEqual(direction, "right")
        tama.walk_timer.start.assert_not_called()

        continuation()

        tama._resume_interaction_walk.assert_called_once_with(
            "right",
            555,
            resume_immediately=True,
        )

    def test_post_landing_route_already_facing_resumes_real_walk_loop(self):
        tama = self._turning_tama("right")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 700
        tama._interaction_surface_ready.return_value = True
        tama.x.return_value = 100
        tama.width.return_value = 100

        Tama.start_interaction_walk(tama, resume_immediately=True)
        direction, target_x = tama._resume_interaction_walk.call_args.args
        Tama._resume_interaction_walk(
            tama,
            direction,
            target_x,
            resume_immediately=True,
        )

        tama._start_interaction_turn.assert_not_called()
        tama.walk_timer.start.assert_called_once_with(140)
        tama.animate_walk.assert_called_once_with()

    def test_post_landing_route_wrong_facing_turns_once_then_resumes_loop(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 700
        tama._interaction_surface_ready.return_value = True
        tama.x.return_value = 100
        tama.width.return_value = 100

        Tama.start_interaction_walk(tama, resume_immediately=True)
        direction, continuation = tama._start_interaction_turn.call_args.args
        self.assertEqual(direction, "right")

        continuation()
        resume_direction, target_x = (
            tama._resume_interaction_walk.call_args.args
        )
        Tama._resume_interaction_walk(
            tama,
            resume_direction,
            target_x,
            resume_immediately=True,
        )

        tama._start_interaction_turn.assert_called_once()
        tama.walk_timer.start.assert_called_once_with(140)
        tama.animate_walk.assert_called_once_with()

    def test_interaction_turn_cancels_when_target_disappears(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "food"
        tama.interaction_target_x = 700
        continuation = Mock()

        Tama._start_interaction_turn(tama, "right", continuation)
        can_continue = tama.start_turn.call_args.kwargs["can_continue"]
        self.assertTrue(tama.start_turn.call_args.kwargs["pivot_step"])

        tama.interaction_target = None
        tama.interaction_target_x = None

        self.assertFalse(can_continue())
        continuation.assert_not_called()

    def test_failed_turn_continuation_guard_cancels_without_callback(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "food"
        can_continue = Mock(return_value=True)
        continuation = Mock()

        Tama.start_turn(
            tama,
            "right",
            on_complete=continuation,
            can_continue=can_continue,
        )
        can_continue.return_value = False

        Tama.animate_turn(tama)

        self.assertFalse(tama.is_turning)
        continuation.assert_not_called()
        tama.turn_timer.stop.assert_called()

    def test_interaction_route_resume_restarts_timer_and_walk_update(self):
        tama = self._turning_tama("right")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 700
        tama.current_surface_y = None
        tama._interaction_surface_ready.return_value = True
        tama.x.return_value = 100
        tama.width.return_value = 100

        Tama._resume_interaction_walk(
            tama,
            "right",
            650,
            resume_immediately=True,
        )

        self.assertEqual(tama.walk_target_x, 650)
        self.assertEqual(tama.walk_direction, "right")
        self.assertEqual(tama.walk_frame_index, 0)
        self.assertEqual(tama.walk_frame_direction, 1)
        tama.walk_timer.start.assert_called_once_with(140)
        tama.animate_walk.assert_called_once_with()

    def test_landing_on_object_finishes_arrival_without_routing_by_x(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 150
        tama.x.return_value = 100
        tama.width.return_value = 100
        tama.is_falling = False
        tama._interaction_surface_ready.return_value = True
        tama._landed_on_interaction_target.side_effect = (
            lambda: Tama._landed_on_interaction_target(tama)
        )

        Tama.finish_landing(tama)

        tama.finish_interaction_arrival.assert_called_once_with(
            from_landing=True
        )
        tama.start_interaction_walk.assert_not_called()
        tama.start_interaction_departure.assert_not_called()

    def test_landing_on_bed_off_center_routes_to_existing_center_anchor(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 150
        tama.x.return_value = 120
        tama.width.return_value = 100
        tama.is_falling = False
        tama._interaction_surface_ready.return_value = True
        tama._landed_on_interaction_target.side_effect = (
            lambda: Tama._landed_on_interaction_target(tama)
        )

        Tama.finish_landing(tama)

        tama.start_interaction_walk.assert_called_once_with(
            resume_immediately=True
        )
        tama.finish_interaction_arrival.assert_not_called()

    def test_normal_food_arrival_does_not_turn_before_interaction(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "food"
        tama.interaction_target_x = 50
        tama.interaction_has_arrived = False
        tama.interaction_final_facing = None
        tama.interaction_arrival_settled = False

        Tama.finish_interaction_arrival(tama)

        tama._start_interaction_turn.assert_not_called()
        tama.start_eating.assert_called_once_with()
        self.assertTrue(tama.interaction_has_arrived)
        self.assertEqual(tama.interaction_final_facing, "left")

    def test_normal_bed_arrival_does_not_turn_before_sitting(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 500
        tama.interaction_has_arrived = False
        tama.interaction_final_facing = None
        tama.interaction_arrival_settled = False
        tama.sit_right_sprite = object()

        Tama.finish_interaction_arrival(tama)

        tama._start_interaction_turn.assert_not_called()
        tama._show_bed_sit_and_schedule_sleep.assert_called_once_with("left")
        self.assertEqual(tama.interaction_final_facing, "left")

    def test_bed_arrival_preserves_approach_direction_from_both_sides(self):
        for direction in ("left", "right"):
            with self.subTest(direction=direction):
                tama = self._turning_tama(direction)
                tama.interaction_target = "bed"
                tama.interaction_target_x = 500

                Tama.finish_interaction_arrival(tama)

                self.assertEqual(tama.facing_direction, direction)
                self.assertEqual(tama.interaction_final_facing, direction)
                tama._show_bed_sit_and_schedule_sleep.assert_called_once_with(
                    direction
                )

    def test_bed_sit_preview_supports_both_directions(self):
        for direction in ("left", "right"):
            with self.subTest(direction=direction):
                tama = self._turning_tama(direction)
                tama.sit_left_sprite = object()
                tama.sit_right_sprite = object()
                expected = (
                    tama.sit_left_sprite
                    if direction == "left"
                    else tama.sit_right_sprite
                )

                Tama._show_bed_sit_and_schedule_sleep(tama, direction)

                tama.set_sprite.assert_called_once_with(expected)
                tama.place_on_ground.assert_called_once_with(expected)
                tama.bed_sleep_pose_timer.start.assert_called_once_with(
                    BED_SIT_TO_SLEEP_MS
                )

    def test_bed_sit_hands_off_to_full_sleep_state_in_both_directions(self):
        for direction in ("left", "right"):
            with self.subTest(direction=direction):
                tama = self._turning_tama(direction)
                tama.interaction_target = "bed"
                tama.interaction_arrival_settled = True

                Tama.enter_bed_sleep_position(tama)

                tama.start_sleep.assert_called_once_with(direction)

    def test_sleep_state_selects_direction_frames_and_starts_entry_timer(self):
        for direction in ("left", "right"):
            with self.subTest(direction=direction):
                tama = self._turning_tama(direction)
                tama.sleep_left_frames = [object() for _ in range(4)]
                tama.sleep_right_frames = [object() for _ in range(4)]
                expected_frames = (
                    tama.sleep_left_frames
                    if direction == "left"
                    else tama.sleep_right_frames
                )

                Tama.start_sleep(tama, direction)

                self.assertTrue(tama.is_sleeping)
                self.assertFalse(tama.is_waking)
                self.assertEqual(tama.sleep_direction, direction)
                self.assertIs(tama.sleep_frames, expected_frames)
                self.assertEqual(tama.sleep_phase, 0)
                tama.set_sprite.assert_called_once_with(expected_frames[0])
                tama.place_on_ground.assert_called_once_with(
                    expected_frames[0]
                )
                tama.sleep_timer.start.assert_called_once_with(1500)

    def test_completed_bed_wake_finishes_interaction(self):
        for direction in ("left", "right"):
            with self.subTest(direction=direction):
                tama = self._turning_tama(direction)
                tama.wake_phase = 2
                tama.is_waking = True
                tama.sleep_direction = direction
                tama.interaction_target = "bed"
                tama.interaction_arrival_settled = True

                Tama.advance_wake(tama)

                self.assertFalse(tama.is_waking)
                tama.finish_bed_sleep.assert_called_once_with()
                tama._show_bed_sit_and_schedule_sleep.assert_not_called()
                tama.sit_left.assert_not_called()
                tama.sit_right.assert_not_called()

    def test_finished_bed_sleep_despawns_and_resumes_normal_decisions(self):
        for direction in ("left", "right"):
            with self.subTest(direction=direction):
                tama = self._turning_tama(direction)
                bed_ui = Mock()
                tama.interaction_target = "bed"
                tama.interaction_target_x = 500
                tama.interaction_ui = bed_ui
                tama.interaction_has_arrived = True
                tama.interaction_final_facing = direction
                tama.interaction_arrival_settled = True
                tama.food_arrival_side = None
                tama.sleep_direction = direction
                tama.current_surface_y = None
                tama.sit_left_sprite = object()
                tama.sit_right_sprite = object()
                if direction == "left":
                    tama.sit_left.side_effect = lambda: Tama.sit_left(tama)
                else:
                    tama.sit_right.side_effect = lambda: Tama.sit_right(tama)

                with patch("main.random.randint", return_value=100):
                    Tama.finish_bed_sleep(tama)

                bed_ui.clear_active_object.assert_called_once_with()
                self.assertIsNone(tama.interaction_target)
                self.assertIsNone(tama.interaction_target_x)
                self.assertIsNone(tama.interaction_ui)
                self.assertFalse(tama.interaction_has_arrived)
                self.assertIsNone(tama.interaction_final_facing)
                self.assertFalse(tama.interaction_arrival_settled)
                tama.schedule_next_action.assert_called_once_with()

    def test_landing_on_food_chooses_one_side_once(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "food"
        tama.interaction_target_x = 500

        with patch("main.random.choice", return_value="left") as choose:
            Tama.finish_interaction_arrival(tama, from_landing=True)
            Tama.finish_interaction_arrival(tama, from_landing=True)

        choose.assert_called_once_with(("left", "right"))
        self.assertEqual(tama.food_arrival_side, "left")
        self.assertEqual(tama._start_landed_food_reposition.call_count, 2)
        tama._start_interaction_turn.assert_not_called()
        self.assertTrue(tama.interaction_has_arrived)

    def test_food_eating_anchors_reuse_existing_95_pixel_offsets(self):
        tama = self._turning_tama("left")
        tama.interaction_target_x = 500
        tama.width.return_value = 100

        self.assertEqual(Tama._food_eating_anchor_x(tama, "left"), 355)
        self.assertEqual(Tama._food_eating_anchor_x(tama, "right"), 545)

    def test_landed_food_side_choices_move_tama_to_matching_anchor(self):
        for side, expected_direction, expected_x in (
            ("left", "left", 355),
            ("right", "right", 545),
        ):
            with self.subTest(side=side):
                tama = self._turning_tama("left")
                tama.interaction_target = "food"
                tama.interaction_target_x = 500
                tama.food_arrival_side = side
                tama.x.return_value = 450
                tama.width.return_value = 100
                tama._food_eating_anchor_x.side_effect = (
                    lambda selected: Tama._food_eating_anchor_x(
                        tama, selected
                    )
                )

                Tama._start_landed_food_reposition(tama)

                tama._resume_interaction_walk.assert_called_once_with(
                    expected_direction,
                    expected_x,
                    resume_immediately=True,
                )
                tama._start_interaction_turn.assert_not_called()
                self.assertEqual(tama.interaction_target_x, 500)

    def test_landed_food_faces_inward_instantly_then_eats_once(self):
        for side, expected_facing in (("left", "right"), ("right", "left")):
            with self.subTest(side=side):
                tama = self._turning_tama("left")
                tama.interaction_target = "food"
                tama.interaction_target_x = 500
                tama.food_arrival_side = side

                Tama.finish_interaction_arrival(tama)
                Tama.finish_interaction_arrival(tama)

                self.assertEqual(tama.facing_direction, expected_facing)
                self.assertEqual(
                    tama.interaction_final_facing,
                    expected_facing,
                )
                tama._start_interaction_turn.assert_not_called()
                tama.start_eating.assert_called_once_with()
                self.assertEqual(tama.interaction_target_x, 500)

    def test_taskbar_landing_away_from_object_preserves_prearrival_route(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 700
        tama.x.return_value = 100
        tama.width.return_value = 100
        tama.is_falling = False
        tama._interaction_surface_ready.return_value = True
        tama._landed_on_interaction_target.side_effect = (
            lambda: Tama._landed_on_interaction_target(tama)
        )

        Tama.finish_landing(tama)

        tama.start_interaction_walk.assert_called_once_with(
            resume_immediately=True
        )
        tama.finish_interaction_arrival.assert_not_called()

    def test_displaced_settled_bed_landing_resets_arrival_and_resumes_route(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 700
        tama.interaction_has_arrived = True
        tama.interaction_final_facing = "right"
        tama.interaction_arrival_settled = True
        tama.is_falling = False
        tama._interaction_surface_ready.return_value = True
        tama._landed_on_interaction_target.return_value = False

        Tama.finish_landing(tama)

        self.assertFalse(tama.interaction_has_arrived)
        self.assertIsNone(tama.interaction_final_facing)
        self.assertFalse(tama.interaction_arrival_settled)
        tama.start_interaction_walk.assert_called_once_with(
            resume_immediately=True
        )

    def test_displaced_settled_bed_window_landing_resumes_departure_route(self):
        tama = self._turning_tama("right")
        tama.interaction_target = "bed"
        tama.interaction_target_x = 700
        tama.interaction_has_arrived = True
        tama.interaction_final_facing = "left"
        tama.interaction_arrival_settled = True
        tama.is_falling = False
        tama._interaction_surface_ready.return_value = False

        Tama.finish_landing(tama)

        self.assertFalse(tama.interaction_has_arrived)
        self.assertIsNone(tama.interaction_final_facing)
        self.assertFalse(tama.interaction_arrival_settled)
        tama.start_interaction_departure.assert_called_once_with(
            resume_immediately=True
        )

    def test_bed_displacement_reset_does_not_change_food_arrival_state(self):
        tama = self._turning_tama("left")
        tama.interaction_target = "food"
        tama.interaction_target_x = 700
        tama.interaction_has_arrived = True
        tama.interaction_final_facing = "right"
        tama.interaction_arrival_settled = True
        tama.food_arrival_side = "left"
        tama.is_falling = False
        tama._interaction_surface_ready.return_value = False

        Tama.finish_landing(tama)

        self.assertTrue(tama.interaction_has_arrived)
        self.assertEqual(tama.interaction_final_facing, "right")
        self.assertTrue(tama.interaction_arrival_settled)
        self.assertEqual(tama.food_arrival_side, "left")

    def test_left_to_right_turn_uses_exact_standalone_path(self):
        tama = self._turning_tama("left")

        Tama.start_turn(tama, "right")

        self.assertEqual(
            tama.turn_sequence,
            [tama.turn_frames[index] for index in (0, 2, 3, 4, 6)],
        )
        tama.turn_timer.start.assert_called_once_with(TURN_FRAME_MS)
        tama._begin_walk.assert_not_called()

        for _ in range(len(tama.turn_sequence)):
            Tama.animate_turn(tama)

        self.assertFalse(tama.is_turning)
        self.assertEqual(tama.facing_direction, "right")
        tama._begin_walk.assert_not_called()

    def test_right_to_left_turn_uses_exact_standalone_path(self):
        tama = self._turning_tama("right")

        Tama.start_turn(tama, "left")

        self.assertEqual(
            tama.turn_sequence,
            [tama.turn_frames[index] for index in (6, 4, 3, 2, 0)],
        )

        for _ in range(len(tama.turn_sequence)):
            Tama.animate_turn(tama)

        self.assertEqual(tama.facing_direction, "left")
        tama._begin_walk.assert_not_called()

    def test_turn_can_run_a_reusable_completion_callback(self):
        tama = self._turning_tama("left")
        on_complete = Mock()

        Tama.start_turn(tama, "right", on_complete=on_complete)
        for _ in range(len(tama.turn_sequence)):
            Tama.animate_turn(tama)

        on_complete.assert_called_once_with()

    def test_turn_does_not_move_horizontally(self):
        tama = self._turning_tama("left")

        Tama.start_turn(tama, "right")
        Tama.animate_turn(tama)

        tama.move.assert_not_called()
        tama._move_during_walk.assert_not_called()

    def test_pivot_step_is_mirrored_and_biased_to_final_three_frames(self):
        for facing, direction, sign in (
            ("left", "right", 1),
            ("right", "left", -1),
        ):
            with self.subTest(direction=direction):
                tama = self._turning_tama(facing)
                tama._move_during_walk.return_value = True
                Tama.start_turn(tama, direction, pivot_step=True)

                Tama.animate_turn(tama)
                tama._move_during_walk.assert_not_called()

                Tama.animate_turn(tama)
                first_step = TURN_PIVOT_STEP_PIXELS // 6
                tama._move_during_walk.assert_called_once_with(
                    100 + (sign * first_step),
                    200,
                    direction=direction,
                    stop_on_reject=False,
                )
                tama.x.return_value = 100 + (sign * first_step)

                Tama.animate_turn(tama)
                second_total = TURN_PIVOT_STEP_PIXELS // 2
                self.assertEqual(
                    tama._move_during_walk.call_args_list[-1].args[0],
                    100 + (sign * second_total),
                )
                tama.x.return_value = 100 + (sign * second_total)

                Tama.animate_turn(tama)
                self.assertEqual(
                    tama._move_during_walk.call_args_list[-1].args[0],
                    100 + (sign * TURN_PIVOT_STEP_PIXELS),
                )
                self.assertEqual(
                    [
                        first_step,
                        second_total - first_step,
                        TURN_PIVOT_STEP_PIXELS - second_total,
                    ],
                    [15, 30, 45],
                )

    def test_invalid_platform_pivot_does_not_cancel_visual_turn(self):
        tama = self._turning_tama("left")
        tama.current_surface_y = 400
        tama.current_surface_left = 0
        tama.current_surface_right = 140
        tama.x.return_value = 100
        tama.width.return_value = 80
        Tama.start_turn(tama, "right", pivot_step=True)

        for _ in range(3):
            Tama.animate_turn(tama)

        self.assertTrue(tama.is_turning)
        tama._move_during_walk.assert_not_called()

        for _ in range(2):
            Tama.animate_turn(tama)

        self.assertFalse(tama.is_turning)
        self.assertEqual(tama.facing_direction, "right")

    def test_interruption_clears_pending_pivot_state(self):
        tama = self._turning_tama("left")
        Tama.start_turn(tama, "right", pivot_step=True)
        tama.is_falling = True

        Tama.animate_turn(tama)

        self.assertFalse(tama.turn_pivot_step)
        self.assertEqual(tama.turn_pivot_applied, 0)

    def test_right_click_does_not_trigger_turn(self):
        tama = self._turning_tama("left")
        tama.is_eating = False
        event = Mock()
        event.button.return_value = Qt.RightButton

        Tama.mousePressEvent(tama, event)

        tama.start_turn.assert_not_called()
        event.accept.assert_not_called()

    def test_fall_cancels_turn_without_resuming_walk(self):
        tama = self._turning_tama("left")
        Tama.start_turn(tama, "right")
        tama.is_falling = True

        Tama.animate_turn(tama)

        self.assertFalse(tama.is_turning)
        tama.turn_timer.stop.assert_called()
        tama._begin_walk.assert_not_called()
        self.assertIsNone(tama.turn_finished_callback)

    def test_pickup_cancels_turn_without_resuming_walk(self):
        tama = self._turning_tama("left")
        tama.is_eating = False
        Tama.start_turn(tama, "right", on_complete=tama._begin_walk)
        event = Mock()
        event.button.return_value = Qt.LeftButton

        Tama.mousePressEvent(tama, event)

        self.assertTrue(tama.is_carrying)
        self.assertFalse(tama.is_turning)
        tama.turn_timer.stop.assert_called()
        tama._begin_walk.assert_not_called()
        self.assertIsNone(tama.turn_finished_callback)

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
            "bed_sleep_pose_timer",
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
        tama.facing_direction = "left"

        Tama.start_interaction_departure(tama)

        tama._resume_interaction_departure.assert_called_once_with(
            "left",
            resume_immediately=False,
        )

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
        tama.facing_direction = "right"

        Tama.start_interaction_departure(tama)

        tama._resume_interaction_departure.assert_called_once_with(
            "right",
            resume_immediately=False,
        )

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
        tama.facing_direction = "left"

        Tama.start_interaction_departure(tama)

        tama._resume_interaction_departure.assert_called_once_with(
            "left",
            resume_immediately=False,
        )

    def test_post_landing_window_departure_turns_toward_intended_edge(self):
        tama = Mock()
        tama.interaction_target = "food"
        tama.interaction_target_x = 1000
        tama.interaction_ui = Mock()
        tama.is_falling = False
        tama.is_post_land_recovery = False
        tama.current_surface_y = 400
        tama.current_surface_left = 100
        tama.current_surface_right = 900
        tama.x.return_value = 120
        tama.width.return_value = 100
        tama.facing_direction = "right"

        Tama.start_interaction_departure(tama)

        tama._start_interaction_turn.assert_called_once()
        direction, continuation = tama._start_interaction_turn.call_args.args
        self.assertEqual(direction, "left")
        tama.start_walk.assert_not_called()

        continuation()

        tama._resume_interaction_departure.assert_called_once_with(
            "left",
            resume_immediately=True,
        )

    def test_window_departure_resume_preserves_selected_direction(self):
        tama = Mock()
        tama.interaction_target = "food"
        tama.is_falling = False
        tama.is_post_land_recovery = False
        tama.current_surface_y = 400
        tama.current_surface_left = 100
        tama.current_surface_right = 900
        tama.width.return_value = 100

        Tama._resume_interaction_departure(tama, "left")

        tama.start_walk.assert_called_once_with("left")
        self.assertEqual(tama.walk_direction, "left")
        self.assertEqual(tama.walk_target_x, 40)

    def test_replacement_target_cancels_old_target_turn(self):
        tama = self._turning_tama("left")
        tama.current_surface_y = None

        Tama.seek_interaction(tama, "bed", 700, Mock())

        tama.cancel_turn.assert_called_once_with()
        self.assertEqual(tama.interaction_target, "bed")
        self.assertEqual(tama.interaction_target_x, 700)
        tama.start_interaction_walk.assert_called_once_with()

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
        tama.start_interaction_departure.assert_called_once_with(
            resume_immediately=True
        )

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
