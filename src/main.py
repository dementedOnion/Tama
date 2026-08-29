import sys
import signal
import random
import ctypes
import json
import os
import math
from datetime import datetime
from pathlib import Path

from ctypes import wintypes

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from tama_ui import TamaUI


DIAGNOSTIC_BUILD = "movement-screen-diagnostics-2026-08-29-1"

# Logical pixels around Tama's horizontal landing point.  Alternate probes are
# still required to be genuinely exposed by Win32, so this does not turn a
# fully covered window into a platform.  Keeping this in Qt coordinates makes
# the allowance consistent across monitor scaling factors.
WINDOW_PLATFORM_EDGE_GRACE = 16
WINDOW_PLATFORM_EDGE_PROBE_STEP = 4
SCREEN_EDGE_VISIBLE_INSET = 2
BONK_LANDING_RECOVERY_MS = 500
BED_SIT_TO_SLEEP_MS = 700
TURN_FRAME_MS = 95
TURN_PIVOT_STEP_PIXELS = 90
TURN_FRAME_PATHS = {
    ("left", "right"): (0, 2, 3, 4, 6),
    ("right", "left"): (6, 4, 3, 2, 0),
}


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def get_dpi_log_file():
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) / "Tama" if appdata else Path.home() / ".tama"
    base.mkdir(parents=True, exist_ok=True)
    return base / "dpi-debug.log"


def dpi_log(message):
    """Append diagnostics even in the windowed packaged executable."""
    try:
        with get_dpi_log_file().open("a", encoding="utf-8") as file:
            timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
            file.write(f"{timestamp} [{DIAGNOSTIC_BUILD}] {message}\n")
    except OSError:
        pass


def windows_dpi_context():
    if sys.platform != "win32":
        return "non-Windows"

    details = []
    try:
        user32 = ctypes.windll.user32
        context = user32.GetThreadDpiAwarenessContext()
        user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
        awareness = user32.GetAwarenessFromDpiAwarenessContext(context)
        details.append(f"thread_context={context:#x} awareness={awareness}")
    except (AttributeError, OSError, ValueError) as error:
        details.append(f"thread_context_error={error!r}")

    try:
        shcore = ctypes.windll.shcore
        process_awareness = ctypes.c_int(-1)
        result = shcore.GetProcessDpiAwareness(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(process_awareness),
        )
        details.append(
            f"process_awareness={process_awareness.value} result={result}"
        )
    except (AttributeError, OSError, ValueError) as error:
        details.append(f"process_awareness_error={error!r}")

    return " ".join(details)


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).resolve().parent.parent

    return base_path / relative_path

def get_state_file():
    appdata = os.environ.get("APPDATA")

    if appdata:
        state_dir = Path(appdata) / "Tama"
    else:
        state_dir = Path.home() / ".tama"

    state_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    return state_dir / "state.json"


def load_state():
    state_file = get_state_file()

    if not state_file.exists():
        return {}

    try:
        with state_file.open(
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (
        OSError,
        json.JSONDecodeError
    ):
        return {}


def save_state(tama, tama_ui):
    state = {
        "tama": {
            "x": tama.x(),
            "y": tama.y(),
        },
        "ui": {
            "x": tama_ui.x(),
            "y": tama_ui.y(),
        },
    }

    state_file = get_state_file()

    try:
        with state_file.open(
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                state,
                file,
                indent=4
            )

    except OSError:
        pass


def position_is_on_screen(x, y):
    for screen in QApplication.screens():
        if screen.geometry().contains(
            x,
            y
        ):
            return True

    return False


def get_taskbar_horizontal_bounds(x, offscreen_margin=200):
    """Return the contiguous monitor span containing x,
    with a small allowed wander area beyond the outer edges.
    """
    intervals = sorted(
        (
            screen.availableGeometry().left(),
            screen.availableGeometry().right(),
        )
        for screen in QApplication.screens()
    )

    if not intervals:
        return x, x

    spans = []

    for left, right in intervals:
        if spans and left <= spans[-1][1] + 1:
            spans[-1] = (
                spans[-1][0],
                max(spans[-1][1], right),
            )
        else:
            spans.append((left, right))

    for left, right in spans:
        if left <= x <= right:
            return (
                left - offscreen_margin,
                right + offscreen_margin,
            )

    nearest_span = min(
        spans,
        key=lambda span: min(
            abs(x - span[0]),
            abs(x - span[1]),
        ),
    )

    return (
        nearest_span[0] - offscreen_margin,
        nearest_span[1] + offscreen_margin,
    )


class CloseButton(QPushButton):
    def __init__(self):
        super().__init__("X")

        self.setFixedSize(34, 34)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        self.setStyleSheet(
            """
            QPushButton {
                background-color: white;
                color: red;
                border: 2px solid red;
                border-radius: 4px;
                font-size: 20px;
                font-weight: bold;
            }
            """
        )

        self.drag_start = None
        self.window_start = None
        self.was_dragged = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.window_start = self.pos()
            self.was_dragged = False

            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self.drag_start is not None
            and event.buttons() & Qt.LeftButton
        ):
            current_position = event.globalPosition().toPoint()
            movement = current_position - self.drag_start

            if movement.manhattanLength() > 3:
                self.was_dragged = True

            self.move(
                self.window_start + movement
            )

            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if not self.was_dragged:
                QApplication.instance().quit()

            self.drag_start = None
            self.window_start = None
            self.was_dragged = False

            event.accept()
            return

        super().mouseReleaseEvent(event)


class Tama(QLabel):
    def __init__(self):
        super().__init__()

        self.is_carrying = False
        self.is_falling = False
        self.is_sleeping = False
        self.is_waking = False
        self.is_post_land_recovery = False
        self.bonk_drop_pending = False
        self.bonk_source_surface_hwnd = None
        self.ignored_platform_hwnds = set()

        # Direction Tama is currently facing
        self.facing_direction = "left"
        self.last_cursor_x = None

        # Current platform.
        # hwnd = None means Tama is standing on the taskbar.
        self.current_surface_hwnd = None
        self.current_surface_y = None
        self.current_surface_left = None
        self.current_surface_right = None
        self.live_exposure_failures = 0

        # -------------------------------------------------
        # IDLE SPRITES
        # -------------------------------------------------

        self.sit_front_sprite = self.load_sprite(
            "assets/sprites/idle/cat_sit_front.png"
        )

        self.sit_left_sprite = self.load_sprite(
            "assets/sprites/idle/cat_sit_left.png"
        )

        self.sit_right_sprite = self.load_sprite(
            "assets/sprites/idle/cat_sit_right.png"
        )

        # -------------------------------------------------
        # CROUCH
        # -------------------------------------------------

        self.crouch_front_frames = [
            self.load_sprite(
                f"assets/sprites/idle/cat_crouch_front_{i:02}.png"
            )
            for i in range(1, 3)
        ]

        self.crouch_frame_index = 0

        # -------------------------------------------------
        # SLEEP
        # -------------------------------------------------

        self.sleep_left_frames = [
            self.load_sprite(
                f"assets/sprites/sleep/sleep_left/cat_sleep_left_{i:02}.png"
            )
            for i in range(1, 5)
        ]

        self.sleep_right_frames = [
            self.load_sprite(
                f"assets/sprites/sleep/sleep_right/cat_sleep_right_{i:02}.png"
            )
            for i in range(1, 5)
        ]

        self.sleep_direction = "left"
        self.sleep_frames = self.sleep_left_frames
        self.sleep_phase = 0
        self.sleep_snore_frame = 2
        self.wake_phase = 0

        # -------------------------------------------------
        # CARRY / FALLING / LANDING - LEFT
        # -------------------------------------------------

        self.carry_left_sprite = self.load_sprite(
            "assets/sprites/carry/carry_left/cat_carry_left.png"
        )

        self.falling_left_sprite = self.load_sprite(
            "assets/sprites/carry/carry_left/cat_falling_left.png"
        )

        self.landing_left_sprite = self.load_sprite(
            "assets/sprites/carry/carry_left/cat_landing_left.png"
        )

        # -------------------------------------------------
        # CARRY / FALLING / LANDING - RIGHT
        # -------------------------------------------------

        self.carry_right_sprite = self.load_sprite(
            "assets/sprites/carry/carry_right/cat_carry_right.png"
        )

        self.falling_right_sprite = self.load_sprite(
            "assets/sprites/carry/carry_right/cat_falling_right.png"
        )

        self.landing_right_sprite = self.load_sprite(
            "assets/sprites/carry/carry_right/cat_landing_right.png"
        )

        # -------------------------------------------------
        # WALKING
        # -------------------------------------------------

        self.offscreen_decisions = 0
        self.offscreen_return_after = random.randint(5, 6)

        self.walk_left_frames = [
            self.load_sprite(
                f"assets/sprites/walk/left/cat_walk_left_{i:02}.png"
            )
            for i in range(1, 4)
        ]

        self.walk_right_frames = [
            self.load_sprite(
                f"assets/sprites/walk/right/cat_walk_right_{i:02}.png"
            )
            for i in range(1, 4)
        ]

        self.walk_frame_index = 0
        self.walk_frame_direction = 1
        self.walk_direction = "left"
        self.walk_target_x = None

        # -------------------------------------------------
        # TURNING
        # -------------------------------------------------

        self.turn_frames = [
            self.load_sprite(
                f"assets/sprites/turn/cat_turn_{i:02}.png"
            )
            for i in range(1, 8)
        ]
        self.is_turning = False
        self.turn_sequence = []
        self.turn_frame_index = 0
        self.turn_target_direction = None
        self.turn_finished_callback = None
        self.turn_continue_condition = None
        self.turn_pivot_step = False
        self.turn_pivot_applied = 0

        # -------------------------------------------------
        # EATING
        # -------------------------------------------------

        self.eating_left_frames = [
            self.load_sprite(
                "assets/sprites/eating/left/eat_left_01.png"
            ),
            self.load_sprite(
                "assets/sprites/eating/left/eat_left_02.png"
            ),
        ]

        self.eating_right_frames = [
            self.load_sprite(
                "assets/sprites/eating/right/eat_right_01.png"
            ),
            self.load_sprite(
                "assets/sprites/eating/right/eat_right_02.png"
            ),
        ]

        self.eating_frames = self.eating_left_frames

        self.is_eating = False
        self.eat_frame_index = 0
        self.eat_frames_shown = 0

        # Eating-animation position adjustment.
        # Positive X = right
        # Negative X = left
        # Positive Y = down
        # Negative Y = up
        # Eating position offsets.
        # Positive X = right
        # Negative X = left
        # Positive Y = down
        # Negative Y = up

        self.eating_left_x_offset = -61
        self.eating_left_y_offset = 10

        self.eating_right_x_offset = 23
        self.eating_right_y_offset = 10

        # -------------------------------------------------
        # INTERACTION TARGET
        # -------------------------------------------------

        self.interaction_target = None
        self.interaction_target_x = None
        self.interaction_ui = None
        self.interaction_has_arrived = False
        self.interaction_final_facing = None
        self.interaction_arrival_settled = False
        self.food_arrival_side = None

        # -------------------------------------------------
        # WINDOW SETUP
        # -------------------------------------------------

        self.set_sprite(self.sit_front_sprite)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        self.setAttribute(Qt.WA_TranslucentBackground)

        # The QWidget and all of Tama's animation/game state survive screen
        # changes.  Only the native translucent window is replaced when its
        # device-pixel ratio changes (see move()).
        self._native_screen = None
        self._last_dpi_diag_screen = None

        # -------------------------------------------------
        # TIMERS
        # -------------------------------------------------

        self.eating_timer = QTimer(self)
        self.eating_timer.timeout.connect(
            self.animate_eating
        )

        self.carry_timer = QTimer(self)
        self.carry_timer.timeout.connect(self.follow_mouse)
        self.carry_timer.start(16)

        self.gravity_timer = QTimer(self)
        self.gravity_timer.timeout.connect(self.apply_gravity)
        self.gravity_timer.start(16)

        self.pose_timer = QTimer(self)
        self.pose_timer.setSingleShot(True)
        self.pose_timer.timeout.connect(self.finish_landing)

        self.walk_timer = QTimer(self)
        self.walk_timer.timeout.connect(self.animate_walk)

        self.turn_timer = QTimer(self)
        self.turn_timer.timeout.connect(self.animate_turn)

        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self.choose_next_action)

        self.crouch_start_timer = QTimer(self)
        self.crouch_start_timer.setSingleShot(True)
        self.crouch_start_timer.timeout.connect(self.start_crouch)

        self.crouch_timer = QTimer(self)
        self.crouch_timer.timeout.connect(self.animate_crouch)

        self.crouch_end_timer = QTimer(self)
        self.crouch_end_timer.setSingleShot(True)
        self.crouch_end_timer.timeout.connect(self.finish_crouch)

        self.sleep_timer = QTimer(self)
        self.sleep_timer.setSingleShot(True)
        self.sleep_timer.timeout.connect(self.advance_sleep)

        self.sleep_end_timer = QTimer(self)
        self.sleep_end_timer.setSingleShot(True)
        self.sleep_end_timer.timeout.connect(self.begin_wake)

        self.bed_sleep_pose_timer = QTimer(self)
        self.bed_sleep_pose_timer.setSingleShot(True)
        self.bed_sleep_pose_timer.timeout.connect(
            self.enter_bed_sleep_position
        )

        # Check whether Tama's current window-platform
        # has moved, vanished, minimized, etc.
        self.platform_timer = QTimer(self)
        self.platform_timer.timeout.connect(
            self.update_current_platform
        )
        self.platform_timer.start(30)

        self.topmost_timer = QTimer(self)
        self.topmost_timer.timeout.connect(self.keep_on_top)
        self.topmost_timer.start(1000)

        QTimer.singleShot(
            0,
            self.start_on_taskbar
        )

        QTimer.singleShot(
            0,
            self.keep_on_top
        )

    # -----------------------------------------------------
    # SPRITE HELPERS
    # -----------------------------------------------------

    def move(self, *args):
        """Move Tama and rebuild her native surface at a mixed-DPI boundary.

        A Windows translucent top-level widget owns a native, DPR-sized
        backing surface.  Reassigning the existing QWindow to another screen
        does not reliably rebuild that surface, leaving Qt and Windows to
        disagree about its physical size.  Keep the QLabel and its state, but
        replace only its native window when Tama's centre crosses to a screen
        with a different device-pixel ratio.
        """
        if len(args) == 1 and isinstance(args[0], QPoint):
            position = args[0]
        elif len(args) == 2:
            position = QPoint(int(args[0]), int(args[1]))
        else:
            return super().move(*args)

        center = QPoint(
            position.x() + (self.width() // 2),
            position.y() + (self.height() // 2),
        )
        target_screen = QApplication.screenAt(center)
        window_handle = self.windowHandle()
        current_screen = self._native_screen

        if current_screen is None and window_handle is not None:
            current_screen = window_handle.screen()

        self._log_dpi_state(
            "move-request",
            requested=position,
            target_screen=target_screen,
        )

        target_name = target_screen.name() if target_screen is not None else None
        if target_name != self._last_dpi_diag_screen:
            self._log_dpi_state(
                "move-target-change",
                requested=position,
                target_screen=target_screen,
            )
            self._last_dpi_diag_screen = target_name

        crosses_dpr_boundary = (
            target_screen is not None
            and current_screen is not None
            and current_screen is not target_screen
            and abs(
                current_screen.devicePixelRatio()
                - target_screen.devicePixelRatio()
            ) > 0.01
        )

        if crosses_dpr_boundary:
            handoff_position = self._contained_handoff_position(
                position,
                target_screen,
            )
            self._log_dpi_state(
                "mixed-dpi-handoff-enter",
                requested=handoff_position,
                target_screen=target_screen,
            )
            self._recreate_native_window(handoff_position, target_screen)
            return

        super().move(position)

        if (
            target_screen is not None
            and window_handle is not None
            and window_handle.screen() is not target_screen
        ):
            window_handle.setScreen(target_screen)

        if target_screen is not None:
            self._native_screen = target_screen

        self._log_dpi_state(
            "move-complete",
            requested=position,
            target_screen=target_screen,
        )

    def _contained_handoff_position(self, position, target_screen):
        """Return a position wholly on the destination side of a boundary.

        The centre-based screen change occurs while roughly half the widget is
        still on the old monitor.  A translucent native surface cannot safely
        span monitors with different DPRs, so complete that small horizontal
        step while the old HWND is hidden.
        """
        geometry = target_screen.geometry()
        x = position.x()

        if x < geometry.left():
            x = geometry.left()
        elif x + self.width() - 1 > geometry.right():
            x = geometry.right() - self.width() + 1

        return QPoint(x, position.y())

    def _move_during_walk(
        self,
        x,
        y,
        direction=None,
        stop_on_reject=True,
    ):
        """Move one autonomous step without bouncing across a DPI edge.

        Walking frames have slightly different widths. Letting the normal
        centre-based move() choose a screen after every adjustSize() can make
        those width changes repeatedly switch the candidate screen at a
        mixed-DPI boundary. A mouse drag does not suffer from that ambiguity
        because the cursor supplies a steadily advancing destination.

        For an autonomous walk, use its direction instead: as soon as the
        next window rectangle would straddle a different-DPR neighbour,
        recreate the native window wholly on that neighbour. The global
        walk_target_x is deliberately left untouched so the current walk
        continues after the handoff.
        """
        position = QPoint(int(x), int(y))
        movement_direction = direction or self.walk_direction
        intended_edge_x = (
            position.x() + SCREEN_EDGE_VISIBLE_INSET
            if movement_direction == "left"
            else position.x() + self.width() - 1 - SCREEN_EDGE_VISIBLE_INSET
        )
        intended_edge = QPoint(
            intended_edge_x,
            position.y() + (self.height() // 2),
        )

        if QApplication.screenAt(intended_edge) is None:
            self._log_dpi_state(
                "walk-rejected-outside-screens",
                requested=position,
                target_screen=None,
            )
            if stop_on_reject:
                self.stop_walking()
            return False

        native_screen = self._native_screen

        if native_screen is None:
            self.move(position)
            return True

        geometry = native_screen.geometry()
        target_screen = None

        if (
            movement_direction == "right"
            and position.x() + self.width() - 1 > geometry.right()
        ):
            target_screen = self._directional_neighbor_screen(
                native_screen,
                movement_direction,
                position.y() + (self.height() // 2),
            )
        elif (
            movement_direction == "left"
            and position.x() < geometry.left()
        ):
            target_screen = self._directional_neighbor_screen(
                native_screen,
                movement_direction,
                position.y() + (self.height() // 2),
            )

        crosses_dpr_boundary = (
            target_screen is not None
            and target_screen is not native_screen
            and abs(
                native_screen.devicePixelRatio()
                - target_screen.devicePixelRatio()
            ) > 0.01
        )

        if crosses_dpr_boundary:
            handoff_position = self._contained_handoff_position(
                position,
                target_screen,
            )
            handoff_position = self._taskbar_handoff_position(
                handoff_position,
                target_screen,
            )
            self._log_dpi_state(
                "mixed-dpi-directional-walk-handoff-enter",
                requested=handoff_position,
                target_screen=target_screen,
            )
            self._recreate_native_window(handoff_position, target_screen)
            return True

        self.move(position)
        return True

    def _would_cross_mixed_dpi_boundary(self, x, y):
        """Return whether this walk step would straddle a mixed-DPI edge."""
        native_screen = self._native_screen
        if native_screen is None:
            return False

        geometry = native_screen.geometry()
        target_screen = None
        if self.walk_direction == "right" and x + self.width() - 1 > geometry.right():
            target_screen = self._directional_neighbor_screen(
                native_screen, "right", y + (self.height() // 2)
            )
        elif self.walk_direction == "left" and x < geometry.left():
            target_screen = self._directional_neighbor_screen(
                native_screen, "left", y + (self.height() // 2)
            )

        return (
            target_screen is not None
            and target_screen is not native_screen
            and abs(
                native_screen.devicePixelRatio()
                - target_screen.devicePixelRatio()
            ) > 0.01
        )

    def _directional_neighbor_screen(self, current_screen, direction, y):
        """Find an adjacent screen using Qt logical coordinates only.

        A one-pixel screenAt() probe is unreliable in mixed-DPI layouts: Qt's
        logical monitor rectangles can contain a gap even when the native
        monitor rectangles touch. Rank the screens on the requested side by
        horizontal distance, then by distance from the walking height.
        """
        current = current_screen.geometry()
        candidates = []

        for screen in QApplication.screens():
            if screen is current_screen:
                continue

            area = screen.geometry()
            if direction == "right" and area.left() <= current.left():
                continue
            if direction == "left" and area.right() >= current.right():
                continue

            horizontal_gap = (
                abs(area.left() - current.right())
                if direction == "right"
                else abs(current.left() - area.right())
            )
            vertical_gap = (
                area.top() - y
                if y < area.top()
                else y - area.bottom()
                if y > area.bottom()
                else 0
            )
            candidates.append((horizontal_gap, vertical_gap, screen))

        if not candidates:
            return None

        return min(candidates, key=lambda item: (item[0], item[1]))[2]

    def _taskbar_handoff_position(self, position, target_screen):
        """Anchor a taskbar walk to the destination taskbar during handoff."""
        if self.current_surface_y is not None:
            return position

        sprite = self.pixmap()
        if sprite is None:
            return position

        visible_bottom = self.find_visible_bottom(sprite)
        return QPoint(
            position.x(),
            target_screen.availableGeometry().bottom() - visible_bottom,
        )

    def _recreate_native_window(self, position, target_screen):
        """Recreate only the platform window on the destination screen."""
        was_visible = self.isVisible()
        old_hwnd = int(self.winId())

        if was_visible:
            self.hide()

        # QWidget.destroy() frees the HWND/backing store without destroying
        # this Python/Qt widget, its pixmap, timers, or animation state.
        self.destroy(True, True)
        super().move(position)

        # winId() creates the replacement native window at the new logical
        # geometry.  Explicitly bind it before showing so its translucent
        # backing surface is allocated using the destination screen's DPR.
        self.winId()
        window_handle = self.windowHandle()

        if (
            window_handle is not None
            and window_handle.screen() is not target_screen
        ):
            window_handle.setScreen(target_screen)

        super().move(position)
        self._native_screen = target_screen

        self._log_dpi_state(
            f"mixed-dpi-handoff-exit old_hwnd={old_hwnd:#x} "
            f"new_hwnd={int(self.winId()):#x}",
            requested=position,
            target_screen=target_screen,
        )

        if was_visible:
            self.show()
            self.raise_()

        self.update()

    def _log_dpi_state(self, event, requested=None, target_screen=None):
        """Record Qt and Win32's views of Tama's top-level surface."""
        try:
            hwnd = int(self.winId())
            rect = wintypes.RECT()
            client = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client))
            try:
                window_dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
            except AttributeError:
                window_dpi = None

            handle = self.windowHandle()
            actual_screen = handle.screen() if handle is not None else None
            believed_screen = getattr(self, "_native_screen", None)
            widget_center = QPoint(
                self.x() + (self.width() // 2),
                self.y() + (self.height() // 2),
            )
            detected_screen = QApplication.screenAt(widget_center)
            pixmap = self.pixmap()
            pixmap_text = "none"
            if pixmap is not None:
                pixmap_text = (
                    f"{pixmap.width()}x{pixmap.height()}@{pixmap.devicePixelRatio():g}"
                )

            def screen_text(screen):
                if screen is None:
                    return "none"
                geometry = screen.geometry()
                available = screen.availableGeometry()
                return (
                    f"{screen.name()!r}:"
                    f"{geometry.x()},{geometry.y()},"
                    f"{geometry.width()}x{geometry.height()} "
                    f"available={available.x()},{available.y()},"
                    f"{available.width()}x{available.height()} "
                    f"dpr={screen.devicePixelRatio():g}"
                )

            requested_text = (
                f"{requested.x()},{requested.y()}" if requested is not None else "none"
            )
            requested_center = None
            requested_screen = None
            if requested is not None:
                requested_center = QPoint(
                    requested.x() + (self.width() // 2),
                    requested.y() + (self.height() // 2),
                )
                requested_screen = QApplication.screenAt(requested_center)

            requested_center_text = (
                f"{requested_center.x()},{requested_center.y()}"
                if requested_center is not None
                else "none"
            )

            platform_text = "none"
            platform_hwnd = getattr(self, "current_surface_hwnd", None)
            if platform_hwnd is not None:
                native_platform = self._native_platform_rect(platform_hwnd)
                qt_platform = self._window_rect_in_qt_coordinates(platform_hwnd)
                if native_platform is None:
                    native_platform_text = "none"
                else:
                    native_platform_text = (
                        f"{native_platform.left},{native_platform.top},"
                        f"{native_platform.right},{native_platform.bottom}"
                    )

                if qt_platform is None:
                    qt_platform_text = "none"
                    mapping_text = "none"
                else:
                    left, top, right, bottom, mapping = qt_platform
                    qt_platform_text = f"{left},{top},{right},{bottom}"
                    native_monitor, logical_monitor = mapping
                    mapping_text = (
                        f"native={native_monitor.left},{native_monitor.top},"
                        f"{native_monitor.right},{native_monitor.bottom} "
                        f"logical={logical_monitor.x()},{logical_monitor.y()},"
                        f"{logical_monitor.width()}x{logical_monitor.height()}"
                    )

                platform_text = (
                    f"hwnd={int(platform_hwnd):#x} "
                    f"native_rect={native_platform_text} "
                    f"qt_rect={qt_platform_text} mapping=({mapping_text})"
                )

            dpi_log(
                f"{event} requested={requested_text} "
                f"requested_center={requested_center_text} "
                f"requested_screen={screen_text(requested_screen)} "
                f"qt_widget={self.x()},{self.y()},{self.width()}x{self.height()} "
                f"qt_center={widget_center.x()},{widget_center.y()} "
                f"hwnd={hwnd:#x} "
                f"win_rect={rect.left},{rect.top},"
                f"{rect.right - rect.left}x{rect.bottom - rect.top} "
                f"win_center={(rect.left + rect.right) // 2},"
                f"{(rect.top + rect.bottom) // 2} "
                f"client={client.right - client.left}x{client.bottom - client.top} "
                f"window_dpi={window_dpi} pixmap={pixmap_text} "
                f"qwindow_dpr={handle.devicePixelRatio() if handle else None} "
                f"screen_at_center={screen_text(detected_screen)} "
                f"believed_screen={screen_text(believed_screen)} "
                f"actual_screen={screen_text(actual_screen)} "
                f"target_screen={screen_text(target_screen)} "
                f"platform=({platform_text}) "
                f"{windows_dpi_context()}"
            )
        except Exception as error:
            dpi_log(f"{event} diagnostic_error={error!r}")

    def load_sprite(self, path):
        pixmap = QPixmap(str(resource_path(path)))

        return pixmap.scaled(
            int(pixmap.width() * 0.7),
            int(pixmap.height() * 0.7),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

    def set_sprite(self, sprite):
        self.setPixmap(sprite)
        self.adjustSize()
        self._contain_resized_surface_at_mixed_dpi_edge()

    def _contain_resized_surface_at_mixed_dpi_edge(self):
        """Keep a wider animation frame from re-straddling a DPI boundary."""
        native_screen = getattr(self, "_native_screen", None)
        if native_screen is None:
            return

        geometry = native_screen.geometry()
        center_y = self.y() + (self.height() // 2)
        x = self.x()

        if x < geometry.left():
            neighbor = QApplication.screenAt(
                QPoint(geometry.left() - 1, center_y)
            )
            if (
                neighbor is not None
                and abs(
                    neighbor.devicePixelRatio()
                    - native_screen.devicePixelRatio()
                ) > 0.01
            ):
                x = geometry.left()

        elif x + self.width() - 1 > geometry.right():
            neighbor = QApplication.screenAt(
                QPoint(geometry.right() + 1, center_y)
            )
            if (
                neighbor is not None
                and abs(
                    neighbor.devicePixelRatio()
                    - native_screen.devicePixelRatio()
                ) > 0.01
            ):
                x = geometry.right() - self.width() + 1

        if x != self.x():
            self.move(x, self.y())

    def get_carry_sprite(self):
        if self.facing_direction == "right":
            return self.carry_right_sprite

        return self.carry_left_sprite

    def get_falling_sprite(self):
        if self.facing_direction == "right":
            return self.falling_right_sprite

        return self.falling_left_sprite

    def get_landing_sprite(self):
        if self.facing_direction == "right":
            return self.landing_right_sprite

        return self.landing_left_sprite

    def find_visible_bottom(self, pixmap):
        image = pixmap.toImage()

        for y in range(
            image.height() - 1,
            -1,
            -1
        ):
            for x in range(image.width()):
                if image.pixelColor(
                    x,
                    y
                ).alpha() > 0:
                    return y

        return image.height() - 1

    # -----------------------------------------------------
    # GROUND / PLATFORM HELPERS
    # -----------------------------------------------------

    def get_taskbar_ground(self):
        screen = QApplication.screenAt(
            self.pos()
        )

        if screen is None:
            screen = QApplication.primaryScreen()

        return screen.availableGeometry().bottom()

    def get_current_ground(self):
        if self.current_surface_y is not None:
            return self.current_surface_y

        return self.get_taskbar_ground()

    def place_on_ground(self, sprite):
        visible_bottom = self.find_visible_bottom(
            sprite
        )

        ground = self.get_current_ground()

        self.move(
            self.x(),
            ground - visible_bottom
        )

        self.keep_on_top()

    def start_on_taskbar(self):
        self.clear_current_surface()

        self.place_on_ground(
            self.sit_front_sprite
        )

        self.schedule_next_action()

    def clear_current_surface(self):
        self.current_surface_hwnd = None
        self.current_surface_y = None
        self.current_surface_left = None
        self.current_surface_right = None
        self.live_exposure_failures = 0

    # -----------------------------------------------------
    # WINDOWS TOPMOST
    # -----------------------------------------------------

    def keep_on_top(self):
        if sys.platform != "win32":
            return

        HWND_TOPMOST = -1

        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010

        ctypes.windll.user32.SetWindowPos(
            int(self.winId()),
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOSIZE
            | SWP_NOMOVE
            | SWP_NOACTIVATE
        )

    # -----------------------------------------------------
    # WINDOWS PLATFORM FILTERING
    # -----------------------------------------------------

    def _monitor_mapping_for_window(self, hwnd):
        """Return the native monitor bounds and matching Qt screen.

        Win32 window rectangles are physical pixels in this per-monitor-DPI
        aware process. Tama movement is in Qt's device-independent global
        coordinates, so platform geometry must cross this mapping exactly
        once before it participates in collision detection.
        """
        if sys.platform != "win32":
            return None

        user32 = ctypes.windll.user32
        MONITOR_DEFAULTTONEAREST = 2
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None

        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None

        device_name = info.szDevice.removeprefix("\\\\.\\").upper()
        screen = next(
            (
                candidate
                for candidate in QApplication.screens()
                if candidate.name().removeprefix("\\\\.\\").upper()
                == device_name
            ),
            None,
        )
        if screen is None:
            # QScreen.name() is a friendly monitor name on some Qt/driver
            # combinations rather than the Win32 DISPLAY device identifier.
            # Windows preserves monitor origins in Qt's global desktop space;
            # use that stable geometry relationship as the fallback match.
            screens = QApplication.screens()
            if screens:
                screen = min(
                    screens,
                    key=lambda candidate: (
                        abs(candidate.geometry().left() - info.rcMonitor.left)
                        + abs(candidate.geometry().top() - info.rcMonitor.top)
                    ),
                )
            else:
                return None

        native = info.rcMonitor
        logical = screen.geometry()
        native_width = native.right - native.left
        native_height = native.bottom - native.top
        if native_width <= 0 or native_height <= 0:
            return None

        return native, logical

    def _window_rect_in_qt_coordinates(self, hwnd):
        """Get an HWND rectangle normalized to Tama's Qt coordinate space."""
        rect = self._native_platform_rect(hwnd)
        if rect is None:
            return None

        mapping = self._monitor_mapping_for_window(hwnd)
        if mapping is None:
            return None

        native, logical = mapping
        scale_x = logical.width() / (native.right - native.left)
        scale_y = logical.height() / (native.bottom - native.top)

        left = logical.left() + (rect.left - native.left) * scale_x
        top = logical.top() + (rect.top - native.top) * scale_y
        right = logical.left() + (rect.right - native.left) * scale_x
        bottom = logical.top() + (rect.bottom - native.top) * scale_y

        # Win32 RECT right/bottom are exclusive; Tama's stored surface bounds
        # and Qt QRect edges are inclusive.
        return (
            math.floor(left),
            math.floor(top),
            math.ceil(right) - 1,
            math.ceil(bottom) - 1,
            mapping,
        )

    def _window_class_name(self, hwnd):
        buffer = ctypes.create_unicode_buffer(256)
        if not ctypes.windll.user32.GetClassNameW(hwnd, buffer, len(buffer)):
            return ""
        return buffer.value

    def _window_title(self, hwnd):
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value

    def _window_process_name(self, hwnd):
        """Best-effort executable identity; class fallbacks cover elevation."""
        process_id = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd,
            ctypes.byref(process_id),
        )
        if not process_id.value:
            return ""

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ctypes.windll.kernel32.OpenProcess.restype = wintypes.HANDLE
        process = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            process_id.value,
        )
        if not process:
            return ""

        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                process,
                0,
                buffer,
                ctypes.byref(size),
            ):
                return ""
            return Path(buffer.value).name.casefold()
        finally:
            ctypes.windll.kernel32.CloseHandle(process)

    def _special_platform_kind(self, hwnd, window_class=None):
        """Identify only window types whose visible frame differs materially."""
        window_class = window_class or self._window_class_name(hwnd)
        class_name = window_class.casefold()

        if class_name == "taskmanagerwindow":
            return "task-manager"

        title = self._window_title(hwnd).strip().casefold()
        if title in {"task manager", "windows task manager"}:
            return "task-manager"

        # ApplicationFrameHost owns the top-level HWND on older Settings
        # versions, so the process alone cannot distinguish it from other
        # hosted apps. Keep this fallback deliberately title-specific.
        settings_classes = {
            "applicationframewindow",
            "winuidesktopwin32windowclass",
        }
        if class_name in settings_classes:
            if title == "settings":
                return "settings"
            if self._window_process_name(hwnd) == "systemsettings.exe":
                return "settings"

        return None

    def _live_exposure_failure_limit(self, hwnd):
        """Return consecutive failed hit-tests required to leave a platform.

        Task Manager can produce an isolated false WindowFromPoint result while
        its elevated non-client window reorders.  Debounce that transient, but
        continue checking it so a genuinely covering window wins normally.
        """
        if self._special_platform_kind(hwnd) == "task-manager":
            return 3
        return 1

    def _live_exposure_probe_inset(self, hwnd):
        """Return the logical-pixel inset used for the platform hit-test.

        Task Manager's DWM visible-frame top can sit on an unstable non-client
        boundary after conversion on a scaled monitor.  Probe safely inside
        its title bar while preserving the same WindowFromPoint z-order test.
        """
        if self._special_platform_kind(hwnd) == "task-manager":
            return 8
        return 1

    def _native_platform_rect(self, hwnd):
        """Return physical bounds, using visible frames only where required."""
        rect = wintypes.RECT()
        special_kind = self._special_platform_kind(hwnd)

        if special_kind is not None:
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            try:
                result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    hwnd,
                    DWMWA_EXTENDED_FRAME_BOUNDS,
                    ctypes.byref(rect),
                    ctypes.sizeof(rect),
                )
                if (
                    result == 0
                    and rect.right > rect.left
                    and rect.bottom > rect.top
                ):
                    return rect
            except (AttributeError, OSError):
                pass

        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return rect

    def _qt_point_to_native(self, x, y, mapping):
        """Convert a collision-space point for a Win32 visibility query."""
        native, logical = mapping
        scale_x = (native.right - native.left) / logical.width()
        scale_y = (native.bottom - native.top) / logical.height()
        return wintypes.POINT(
            round(native.left + (x - logical.left()) * scale_x),
            round(native.top + (y - logical.top()) * scale_y),
        )

    def is_window_cloaked(self, hwnd):
        if sys.platform != "win32":
            return False

        try:
            DWMWA_CLOAKED = 14

            cloaked = wintypes.DWORD()

            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd,
                DWMWA_CLOAKED,
                ctypes.byref(cloaked),
                ctypes.sizeof(cloaked)
            )

            if result != 0:
                return False

            return cloaked.value != 0

        except Exception:
            return False

    def ignore_platform_window(self, hwnd):
        """Make one of Tama's own windows transparent to platform sensing."""
        if hwnd:
            self.ignored_platform_hwnds.add(int(hwnd))

    def _is_ignored_platform_window(self, hwnd):
        if not hwnd:
            return False

        hwnd = int(hwnd)
        tama_hwnd = int(self.winId())
        if hwnd == tama_hwnd or hwnd in self.ignored_platform_hwnds:
            return True

        if sys.platform != "win32":
            return False

        user32 = ctypes.windll.user32
        root = user32.GetAncestor(hwnd, 2)
        tama_root = user32.GetAncestor(tama_hwnd, 2) or tama_hwnd
        return bool(
            root
            and (
                int(root) == int(tama_root)
                or int(root) in self.ignored_platform_hwnds
            )
        )

    def _top_nonignored_window_at_point(self, point):
        """Return the first real app window at point, looking through Tama UI."""
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetWindow.restype = wintypes.HWND

        top_hwnd = user32.WindowFromPoint(point)
        if not top_hwnd or not self._is_ignored_platform_window(top_hwnd):
            return top_hwnd

        top_root = user32.GetAncestor(top_hwnd, 2) or top_hwnd
        hwnd = user32.GetWindow(top_root, 2)  # GW_HWNDNEXT
        while hwnd:
            rect = wintypes.RECT()
            if (
                not self._is_ignored_platform_window(hwnd)
                and user32.IsWindowVisible(hwnd)
                and not user32.IsIconic(hwnd)
                and user32.GetWindowRect(hwnd, ctypes.byref(rect))
                and rect.left <= point.x < rect.right
                and rect.top <= point.y < rect.bottom
            ):
                return hwnd
            hwnd = user32.GetWindow(hwnd, 2)

        return None

    def is_window_exposed_at_x(
        self,
        hwnd,
        x,
        window_top,
        mapping,
    ):
        if sys.platform != "win32":
            return True

        user32 = ctypes.windll.user32

        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.restype = wintypes.HWND

        point = self._qt_point_to_native(
            x,
            window_top + self._live_exposure_probe_inset(hwnd),
            mapping,
        )

        top_hwnd = self._top_nonignored_window_at_point(point)

        if not top_hwnd:
            return False

        GA_ROOT = 2

        top_root = user32.GetAncestor(
            top_hwnd,
            GA_ROOT
        )

        if not top_root:
            top_root = top_hwnd

        candidate_root = user32.GetAncestor(
            hwnd,
            GA_ROOT
        )

        if not candidate_root:
            candidate_root = hwnd

        return (
            int(top_root)
            == int(candidate_root)
        )

    def _window_platform_exposed_sample_x(
        self,
        hwnd,
        tama_center_x,
        window_left,
        window_right,
        window_top,
        mapping,
    ):
        """Return a genuinely exposed landing sample near Tama, if any.

        The centre remains the preferred collision point.  The small lateral
        search is only used by window-platform landing and only within the
        candidate window's real bounds.  Each alternate point goes through the
        normal WindowFromPoint z-order check, which rejects fully hidden
        windows and lets a foreground window win at every point it covers.
        """
        probe_left = max(
            window_left,
            tama_center_x - WINDOW_PLATFORM_EDGE_GRACE,
        )
        probe_right = min(
            window_right,
            tama_center_x + WINDOW_PLATFORM_EDGE_GRACE,
        )

        if probe_left > probe_right:
            return None

        primary_x = min(max(tama_center_x, window_left), window_right)
        sample_xs = [primary_x]

        for offset in range(
            WINDOW_PLATFORM_EDGE_PROBE_STEP,
            WINDOW_PLATFORM_EDGE_GRACE + 1,
            WINDOW_PLATFORM_EDGE_PROBE_STEP,
        ):
            for sample_x in (primary_x - offset, primary_x + offset):
                if probe_left <= sample_x <= probe_right:
                    sample_xs.append(sample_x)

        for sample_x in (probe_left, probe_right):
            if sample_x not in sample_xs:
                sample_xs.append(sample_x)

        for sample_x in sample_xs:
            if self.is_window_exposed_at_x(
                hwnd,
                sample_x,
                window_top,
                mapping,
            ):
                return sample_x

        return None

    def find_window_surface_crossing(
        self,
        current_paw_y,
        next_paw_y
    ):
        if sys.platform != "win32":
            return None

        user32 = ctypes.windll.user32

        user32.GetWindow.restype = wintypes.HWND

        tama_hwnd = int(
            self.winId()
        )

        tama_center_x = (
            self.x()
            + (self.width() // 2)
        )

        best_surface = None

        def enum_windows(
            hwnd,
            lparam
        ):
            nonlocal best_surface

            if hwnd == tama_hwnd:
                return True

            if self._is_ignored_platform_window(hwnd):
                return True

            if (
                self.bonk_source_surface_hwnd is not None
                and int(hwnd) == int(self.bonk_source_surface_hwnd)
            ):
                return True

            if not user32.IsWindowVisible(
                hwnd
            ):
                return True

            if user32.IsIconic(
                hwnd
            ):
                return True

            if self.is_window_cloaked(
                hwnd
            ):
                return True

            GW_OWNER = 4

            owner_hwnd = user32.GetWindow(
                hwnd,
                GW_OWNER
            )

            if owner_hwnd == tama_hwnd:
                return True

            window_class = self._window_class_name(hwnd)
            special_kind = self._special_platform_kind(hwnd, window_class)

            ignored_classes = {
                "WinUIDesktopWin32WindowClass",
            }

            if (
                window_class
                in ignored_classes
                and special_kind is None
            ):
                return True

            platform_rect = self._window_rect_in_qt_coordinates(hwnd)
            if platform_rect is None:
                return True

            left, top, right, bottom, mapping = platform_rect

            width = (
                right
                - left
                + 1
            )

            height = (
                bottom
                - top
                + 1
            )

            if (
                width < 150
                or height < 100
            ):
                return True

            if not (
                left - WINDOW_PLATFORM_EDGE_GRACE
                <= tama_center_x
                <= right + WINDOW_PLATFORM_EDGE_GRACE
            ):
                return True

            if not (
                current_paw_y
                <= top
                <= next_paw_y
            ):
                return True

            exposed_sample_x = self._window_platform_exposed_sample_x(
                hwnd,
                tama_center_x,
                left,
                right,
                top,
                mapping,
            )
            if exposed_sample_x is None:
                return True

            candidate = (
                hwnd,
                top,
                left,
                right
            )

            if (
                best_surface is None
                or top
                < best_surface[1]
            ):
                best_surface = candidate

            return True

        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            wintypes.HWND,
            wintypes.LPARAM
        )

        callback = EnumWindowsProc(
            enum_windows
        )

        user32.EnumWindows(
            callback,
            0
        )

        return best_surface

    # -----------------------------------------------------
    # LIVE PLATFORM TRACKING
    # -----------------------------------------------------

    def update_current_platform(self):
        if sys.platform != "win32":
            return

        if self.current_surface_hwnd is None:
            return

        if self.is_carrying:
            return

        if self.is_falling:
            return

        user32 = ctypes.windll.user32

        hwnd = self.current_surface_hwnd

        if not user32.IsWindow(hwnd):
            self.fall_from_platform()
            return

        if not user32.IsWindowVisible(hwnd):
            self.fall_from_platform()
            return

        if user32.IsIconic(hwnd):
            self.fall_from_platform()
            return

        if self.is_window_cloaked(hwnd):
            self.fall_from_platform()
            return

        platform_rect = self._window_rect_in_qt_coordinates(hwnd)
        if platform_rect is None:
            self.fall_from_platform()
            return

        left, top, right, _bottom, mapping = platform_rect

        tama_center_x = (
            self.x()
            + (self.width() // 2)
        )

        if not (
            left
            <= tama_center_x
            <= right
        ):
            self.fall_from_platform()
            return

        exposed_sample_x = self._window_platform_exposed_sample_x(
            hwnd,
            tama_center_x,
            left,
            right,
            top,
            mapping,
        )
        if exposed_sample_x is None:
            self.live_exposure_failures += 1
            if (
                self.live_exposure_failures
                >= self._live_exposure_failure_limit(hwnd)
            ):
                self.fall_from_platform()
                return
        else:
            self.live_exposure_failures = 0

        self.current_surface_y = top
        self.current_surface_left = left
        self.current_surface_right = right

        if (
            self.interaction_target is not None
            and self.walk_timer.isActive()
        ):
            Tama._update_interaction_departure_target(self)

        current_sprite = self.pixmap()

        if (
            current_sprite is None
            or current_sprite.isNull()
        ):
            return

        visible_bottom = self.find_visible_bottom(
            current_sprite
        )

        crouch_offset = 0

        if (
            self.crouch_timer.isActive()
            or self.crouch_end_timer.isActive()
        ):
            crouch_offset = 20

        new_y = (
            self.current_surface_y
            - visible_bottom
            + crouch_offset
        )

        self.move(
            self.x(),
            new_y
        )

    # -----------------------------------------------------
    # PICK UP / CARRY
    # -----------------------------------------------------

    def mousePressEvent(
        self,
        event
    ):
        if self.is_eating:
            event.accept()
            return

        if (
            event.button()
            == Qt.LeftButton
        ):
            self.is_carrying = True
            self.is_falling = False
            self.is_post_land_recovery = False
            self.bonk_drop_pending = False
            self.bonk_source_surface_hwnd = None
            self.is_sleeping = False
            self.is_waking = False

            self.pose_timer.stop()
            self.walk_timer.stop()
            self.cancel_turn()
            self.idle_timer.stop()

            self.crouch_start_timer.stop()
            self.crouch_timer.stop()
            self.crouch_end_timer.stop()

            self.sleep_timer.stop()
            self.sleep_end_timer.stop()
            self.bed_sleep_pose_timer.stop()

            self.walk_target_x = None

            self.clear_current_surface()

            self.last_cursor_x = (
                QCursor.pos().x()
            )

            self.set_sprite(
                self.get_carry_sprite()
            )

    def follow_mouse(self):
        if not self.is_carrying:
            return

        cursor_position = QCursor.pos()

        current_x = (
            cursor_position.x()
        )

        previous_direction = (
            self.facing_direction
        )

        if self.last_cursor_x is not None:

            if (
                current_x
                > self.last_cursor_x
            ):
                self.facing_direction = "right"

            elif (
                current_x
                < self.last_cursor_x
            ):
                self.facing_direction = "left"

        self.last_cursor_x = current_x

        if (
            self.facing_direction
            != previous_direction
        ):
            self.set_sprite(
                self.get_carry_sprite()
            )

        self.move(
            cursor_position.x() - 73,
            cursor_position.y() - 10
        )

    def mouseReleaseEvent(
        self,
        event
    ):
        if self.is_eating:
            event.accept()
            return

        if (
            event.button()
            == Qt.LeftButton
        ):
            self.is_carrying = False
            self.is_falling = True

            self.last_cursor_x = None

            self.set_sprite(
                self.get_falling_sprite()
            )

    # -----------------------------------------------------
    # GRAVITY
    # -----------------------------------------------------

    def apply_gravity(self):
        if not self.is_falling:
            return

        falling_sprite = (
            self.get_falling_sprite()
        )

        visible_bottom = (
            self.find_visible_bottom(
                falling_sprite
            )
        )

        current_paw_y = (
            self.y()
            + visible_bottom
        )

        next_paw_y = (
            current_paw_y
            + 8
        )

        window_surface = (
            self.find_window_surface_crossing(
                current_paw_y,
                next_paw_y
            )
        )

        if window_surface is not None:

            (
                self.current_surface_hwnd,
                self.current_surface_y,
                self.current_surface_left,
                self.current_surface_right
            ) = window_surface

            self.live_exposure_failures = 0

            self.move(
                self.x(),
                (
                    self.current_surface_y
                    - visible_bottom
                )
            )

            self.is_falling = False
            self.bonk_source_surface_hwnd = None

            self.land()

            return

        taskbar_ground = (
            self.get_taskbar_ground()
        )

        if (
            next_paw_y
            >= taskbar_ground
        ):
            self.clear_current_surface()

            self.move(
                self.x(),
                (
                    taskbar_ground
                    - visible_bottom
                )
            )

            self.is_falling = False
            self.bonk_source_surface_hwnd = None

            self.land()

            return

        self.move(
            self.x(),
            self.y() + 8
        )

    # -----------------------------------------------------
    # LANDING
    # -----------------------------------------------------

    def land(self):
        # Landing owns the pose until pose_timer completes.  In particular, a
        # queued idle/crouch/walk callback from the previous platform must not
        # repaint the landing frame.
        self.walk_timer.stop()
        self.idle_timer.stop()
        self.crouch_start_timer.stop()
        self.crouch_timer.stop()
        self.crouch_end_timer.stop()

        landing_sprite = (
            self.get_landing_sprite()
        )

        self.set_sprite(
            landing_sprite
        )

        self.place_on_ground(
            landing_sprite
        )

        self.pose_timer.stop()
        if self.bonk_drop_pending:
            self.bonk_drop_pending = False
            self.is_post_land_recovery = True
            self.pose_timer.start(BONK_LANDING_RECOVERY_MS)
        else:
            self.pose_timer.start(250)

    def finish_landing(self):
        # A platform can disappear during the landing pause.  fall_from_platform
        # stops pose_timer, but an already queued timeout must also be harmless.
        if self.is_falling:
            return

        self.is_post_land_recovery = False

        if self.interaction_target is not None:
            # A completed Bed interaction belongs to the position where Tama
            # sat.  Picking her up or otherwise falling moves her away from
            # that completed arrival, even though the same Bed remains active.
            # Clear only the Bed arrival latch here so landing recovery can
            # route back to it instead of returning behind the settled guard
            # and leaving the landing/crouch frame visible.
            if (
                self.interaction_target == "bed"
                and self.interaction_has_arrived
                and self.interaction_arrival_settled
            ):
                self.interaction_has_arrived = False
                self.interaction_final_facing = None
                self.interaction_arrival_settled = False

            # Food and bed live on the taskbar.  A window encountered on the
            # way down is only an intermediate landing, not arrival.
            if not self._interaction_surface_ready():
                self.start_interaction_departure(resume_immediately=True)
                return

            if self._landed_on_interaction_target():
                if self.interaction_target == "bed":
                    bed_centered_x = (
                        self.interaction_target_x - (self.width() // 2)
                    )
                    if self.x() != bed_centered_x:
                        self.start_interaction_walk(
                            resume_immediately=True
                        )
                        return
                self.finish_interaction_arrival(from_landing=True)
                return

            self.start_interaction_walk(resume_immediately=True)
            return

        if (
            self.facing_direction
            == "right"
        ):
            self.sit_right()
        else:
            self.sit_left()

    # -----------------------------------------------------
    # SITTING / IDLE BRAIN
    # -----------------------------------------------------

    def sit_front(self):
        self.set_sprite(
            self.sit_front_sprite
        )

        self.place_on_ground(
            self.sit_front_sprite
        )

        if random.randint(
            1,
            100
        ) <= 25:
            self.crouch_start_timer.start(
                1000
            )
        else:
            self.schedule_next_action()

    def sit_left(self):
        self.facing_direction = "left"

        self.set_sprite(
            self.sit_left_sprite
        )

        self.place_on_ground(
            self.sit_left_sprite
        )

        if (
            self.current_surface_y
            is not None
        ):
            self.schedule_next_action()
            return

        if random.randint(
            1,
            100
        ) <= 15:
            self.start_sleep("left")
        else:
            self.schedule_next_action()

    def sit_right(self):
        self.facing_direction = "right"

        self.set_sprite(
            self.sit_right_sprite
        )

        self.place_on_ground(
            self.sit_right_sprite
        )

        if (
            self.current_surface_y
            is not None
        ):
            self.schedule_next_action()
            return

        if random.randint(
            1,
            100
        ) <= 15:
            self.start_sleep("right")
        else:
            self.schedule_next_action()

    def schedule_next_action(self):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_turning
            or self.is_sleeping
            or self.is_waking
            or self.interaction_target is not None
        ):
            return

        wait_time = random.randint(
            2000,
            6000
        )

        self.idle_timer.start(
            wait_time
        )

    def is_completely_offscreen(self):
        tama_left = self.x()
        tama_right = self.x() + self.width()

        for screen in QApplication.screens():
            area = screen.availableGeometry()

            if (
                tama_right >= area.left()
                and tama_left <= area.right()
            ):
                return False

        return True

    def choose_next_action(self):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_turning
            or self.interaction_target is not None
        ):
            return

        # If Tama is completely off-screen, let her continue
        # making normal random decisions for a while.
        if self.is_completely_offscreen():
            self.offscreen_decisions += 1

            # She's been fucking around out there long enough.
            if (
                self.offscreen_decisions
                >= self.offscreen_return_after
            ):
                self.offscreen_decisions = 0
                self.offscreen_return_after = random.randint(
                    5,
                    6
                )

                # Work out which direction leads back toward
                # the nearest monitor.
                tama_center = (
                    self.x()
                    + (self.width() // 2)
                )

                nearest_screen = min(
                    QApplication.screens(),
                    key=lambda screen: min(
                        abs(
                            tama_center
                            - screen.availableGeometry().left()
                        ),
                        abs(
                            tama_center
                            - screen.availableGeometry().right()
                        ),
                    ),
                )

                area = nearest_screen.availableGeometry()

                if tama_center < area.left():
                    self.start_walk("right")
                else:
                    self.start_walk("left")

                return

        else:
            # She's visible again, so forget the escape count.
            self.offscreen_decisions = 0
            self.offscreen_return_after = random.randint(
                5,
                6
            )

        # Normal Tama brain.
        choice = random.randint(
            1,
            100
        )

        if choice <= 40:
            self.sit_front()
            return

        if choice <= 70:
            self.start_walk("left")
            return

        self.start_walk("right")

    # -----------------------------------------------------
    # CROUCH / BUTT WIGGLE
    # -----------------------------------------------------

    def start_crouch(self):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_sleeping
            or self.is_waking
            or self.is_eating
            or self.is_turning
            or self.interaction_target is not None
            or self.walk_timer.isActive()
        ):
            return

        self.idle_timer.stop()

        self.crouch_frame_index = 0

        frame = (
            self.crouch_front_frames[
                self.crouch_frame_index
            ]
        )

        visible_bottom = (
            self.find_visible_bottom(
                frame
            )
        )

        ground = (
            self.get_current_ground()
        )

        crouch_y = (
            ground
            - visible_bottom
            + 20
        )

        self.move(
            self.x(),
            crouch_y
        )

        self.set_sprite(
            frame
        )

        self.crouch_timer.start(
            500
        )

        crouch_time = random.randint(
            2000,
            5000
        )

        self.crouch_end_timer.start(
            crouch_time
        )

    def animate_crouch(self):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_turning
            or self.walk_timer.isActive()
        ):
            self.crouch_timer.stop()
            return

        self.crouch_frame_index += 1

        if (
            self.crouch_frame_index
            >= len(
                self.crouch_front_frames
            )
        ):
            self.crouch_frame_index = 0

        frame = (
            self.crouch_front_frames[
                self.crouch_frame_index
            ]
        )

        self.set_sprite(
            frame
        )

    def finish_crouch(self):
        self.crouch_timer.stop()

        if (
            self.is_carrying
            or self.is_falling
            or self.is_turning
            or self.walk_timer.isActive()
            or self.interaction_target is not None
        ):
            return

        self.sit_front()

    # -----------------------------------------------------
    # SLEEP
    # -----------------------------------------------------

    def enter_bed_sleep_position(self):
        """Start Bed's direction-matched sleep state after the sit preview."""
        if (
            self.interaction_target != "bed"
            or not self.interaction_arrival_settled
            or self.is_carrying
            or self.is_falling
            or self.is_turning
        ):
            return

        self.start_sleep(self.facing_direction)

    def _show_bed_sit_and_schedule_sleep(self, direction):
        """Show Bed's approved sit transition before the next sleep cycle."""
        self.facing_direction = direction
        sprite = (
            self.sit_left_sprite
            if direction == "left"
            else self.sit_right_sprite
        )
        self.set_sprite(sprite)
        self.place_on_ground(sprite)
        self.bed_sleep_pose_timer.start(BED_SIT_TO_SLEEP_MS)

    def start_sleep(
        self,
        direction
    ):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_turning
        ):
            return

        self.idle_timer.stop()
        self.bed_sleep_pose_timer.stop()

        self.is_sleeping = True
        self.is_waking = False

        self.sleep_direction = direction
        self.facing_direction = direction

        if direction == "left":
            self.sleep_frames = (
                self.sleep_left_frames
            )
        else:
            self.sleep_frames = (
                self.sleep_right_frames
            )

        self.sleep_phase = 0
        self.sleep_snore_frame = 2

        frame = self.sleep_frames[0]

        self.set_sprite(
            frame
        )

        self.place_on_ground(
            frame
        )

        self.sleep_timer.start(
            1500
        )

    def advance_sleep(self):
        if (
            self.is_carrying
            or self.is_falling
        ):
            self.sleep_timer.stop()
            return

        if self.is_waking:
            self.advance_wake()
            return

        if self.sleep_phase == 0:
            self.sleep_phase = 1

            self.set_sprite(
                self.sleep_frames[1]
            )

            self.sleep_timer.start(
                700
            )

            return

        if self.sleep_phase == 1:
            self.sleep_phase = 2

            self.set_sprite(
                self.sleep_frames[2]
            )

            self.sleep_timer.start(
                700
            )

            return

        if self.sleep_phase == 2:
            self.sleep_phase = 3

            self.set_sprite(
                self.sleep_frames[3]
            )

            sleep_time = random.randint(
                8000,
                20000
            )

            self.sleep_end_timer.start(
                sleep_time
            )

            self.sleep_snore_frame = 2

            self.sleep_timer.start(
                random.randint(
                    600,
                    800
                )
            )

            return

        if self.sleep_snore_frame == 2:
            self.sleep_snore_frame = 3
        else:
            self.sleep_snore_frame = 2

        self.set_sprite(
            self.sleep_frames[
                self.sleep_snore_frame
            ]
        )

        self.sleep_timer.start(
            random.randint(
                600,
                800
            )
        )

    def begin_wake(self):
        if not self.is_sleeping:
            return

        self.sleep_timer.stop()
        self.sleep_end_timer.stop()
        self.bed_sleep_pose_timer.stop()

        self.is_sleeping = False
        self.is_waking = True
        self.wake_phase = 0

        self.set_sprite(
            self.sleep_frames[2]
        )

        self.sleep_timer.start(
            600
        )

    def advance_wake(self):
        if self.wake_phase == 0:
            self.wake_phase = 1

            self.set_sprite(
                self.sleep_frames[1]
            )

            self.sleep_timer.start(
                700
            )

            return

        if self.wake_phase == 1:
            self.wake_phase = 2

            self.set_sprite(
                self.sleep_frames[0]
            )

            self.sleep_timer.start(
                1000
            )

            return

        self.is_waking = False

        if (
            self.interaction_target == "bed"
            and self.interaction_arrival_settled
        ):
            self.finish_bed_sleep()
            return

        if self.sleep_direction == "left":
            self.sit_left()
        else:
            self.sit_right()

    def finish_bed_sleep(self):
        """Despawn Bed and return a completed sleeper to normal decisions."""
        if self.interaction_target != "bed":
            return

        direction = self.sleep_direction
        self.bed_sleep_pose_timer.stop()

        if self.interaction_ui is not None:
            self.interaction_ui.clear_active_object()

        self.interaction_target = None
        self.interaction_target_x = None
        self.interaction_ui = None
        self.interaction_has_arrived = False
        self.interaction_final_facing = None
        self.interaction_arrival_settled = False
        self.food_arrival_side = None

        # Use the ordinary post-wake sit path now that the interaction lock is
        # gone; it owns scheduling Tama's next autonomous decision.
        if direction == "left":
            self.sit_left()
        else:
            self.sit_right()

    # -----------------------------------------------------
    # INTERACTION SEEKING
    # -----------------------------------------------------

    def _interaction_surface_ready(self):
        """Return whether Tama is stably standing on the target taskbar."""
        if self.interaction_target is None or self.is_falling:
            return False

        if self.current_surface_y is not None:
            return False

        current_sprite = self.pixmap()
        if current_sprite is None or current_sprite.isNull():
            return False

        paw_y = self.y() + self.find_visible_bottom(current_sprite)
        return abs(paw_y - self.get_taskbar_ground()) <= 2

    def seek_interaction(self, interaction_type, target_x, interaction_ui=None):
        """Stop normal idle behaviour and go to a spawned object."""

        self.cancel_turn()
        self.interaction_target = interaction_type
        self.interaction_target_x = target_x
        self.interaction_ui = interaction_ui
        self.interaction_has_arrived = False
        self.interaction_final_facing = None
        self.interaction_arrival_settled = False
        self.food_arrival_side = None

        # Stop Tama choosing unrelated activities.
        self.idle_timer.stop()
        self.crouch_start_timer.stop()
        self.crouch_timer.stop()
        self.crouch_end_timer.stop()

        self.sleep_timer.stop()
        self.sleep_end_timer.stop()
        self.bed_sleep_pose_timer.stop()

        self.is_sleeping = False
        self.is_waking = False

        self.walk_timer.stop()
        self.walk_target_x = None

        # If Tama is standing on a program window, walk clear of its nearest
        # edge before falling. Dropping in place lets gravity immediately
        # rediscover the same window and creates a fall/land loop.
        if self.current_surface_y is not None:
            self.start_interaction_departure()
            return

        self.start_interaction_walk()

    def start_interaction_departure(self, resume_immediately=False):
        """Walk off whichever edge of the current platform is closest."""
        if (
            self.interaction_target is None
            or self.is_falling
            or self.is_post_land_recovery
        ):
            return

        if (
            self.current_surface_y is None
            or self.current_surface_left is None
            or self.current_surface_right is None
        ):
            self.fall_from_platform()
            return

        tama_center_x = self.x() + (self.width() // 2)
        distance_to_left = abs(tama_center_x - self.current_surface_left)
        distance_to_right = abs(self.current_surface_right - tama_center_x)

        if distance_to_left <= distance_to_right:
            direction = "left"
        else:
            direction = "right"

        if direction != self.facing_direction:
            self._start_interaction_turn(
                direction,
                lambda: self._resume_interaction_departure(
                    direction,
                    resume_immediately=True,
                ),
            )
            return

        self._resume_interaction_departure(
            direction,
            resume_immediately=resume_immediately,
        )

    def _resume_interaction_departure(
        self,
        direction,
        resume_immediately=False,
    ):
        """Resume the already-selected platform-edge route."""
        if (
            self.interaction_target is None
            or self.is_falling
            or self.is_post_land_recovery
            or self.current_surface_y is None
        ):
            return

        self.start_walk(direction)
        self.walk_direction = direction
        Tama._update_interaction_departure_target(self)
        if resume_immediately:
            self.animate_walk()

    def _update_interaction_departure_target(self):
        """Keep an interaction drop point attached to its moving platform."""
        if self.walk_direction == "left":
            self.walk_target_x = (
                self.current_surface_left
                - (self.width() // 2)
                - 10
            )
        else:
            self.walk_target_x = (
                self.current_surface_right
                - (self.width() // 2)
                + 10
            )

    def start_interaction_walk(self, resume_immediately=False):
        if self.interaction_target is None or self.is_post_land_recovery:
            return

        # Once arrival has been confirmed, the object's X coordinate is no
        # longer a navigation target.  In particular, a pivot step must not
        # make the continuation choose the opposite direction again.
        if self.interaction_has_arrived:
            self.finish_interaction_arrival()
            return

        if self.interaction_target_x is None:
            return

        if not self._interaction_surface_ready():
            if self.current_surface_y is not None:
                self.start_interaction_departure()
            elif not self.is_falling:
                self.fall_from_platform()
            return

        if self.interaction_target == "food":
            side = (
                "right"
                if self.interaction_target_x < self.x() + (self.width() // 2)
                else "left"
            )
            target_x = self._food_eating_anchor_x(side)
        else:
            # Aim Tama's centre roughly at the object's centre.
            target_x = (
                self.interaction_target_x
                - (self.width() // 2)
            )

        if target_x < self.x():
            direction = "left"
        else:
            direction = "right"

        if direction != self.facing_direction:
            self._start_interaction_turn(
                direction,
                lambda: self._resume_interaction_walk(
                    direction,
                    target_x,
                    resume_immediately=True,
                ),
            )
            return

        self._resume_interaction_walk(
            direction,
            target_x,
            resume_immediately=resume_immediately,
        )

    def _resume_interaction_walk(
        self,
        direction,
        target_x,
        resume_immediately=False,
    ):
        """Resume a previously selected object route, including its timer."""
        if (
            self.interaction_target is None
            or self.is_falling
            or self.is_post_land_recovery
            or not self._interaction_surface_ready()
        ):
            return

        self.walk_target_x = target_x
        self.walk_direction = direction
        self.facing_direction = direction

        self.walk_frame_index = 0
        self.walk_frame_direction = 1

        self.walk_timer.start(140)
        if resume_immediately:
            self.animate_walk()

    def _food_eating_anchor_x(self, side):
        """Return Tama's existing Food-relative stop position for one side."""
        bowl_centered_x = self.interaction_target_x - (self.width() // 2)
        food_stop_offset = 95
        if side == "left":
            return bowl_centered_x - food_stop_offset
        return bowl_centered_x + food_stop_offset

    def _start_landed_food_reposition(self):
        """Move Tama from a Food landing to her chosen eating anchor."""
        target_x = self._food_eating_anchor_x(self.food_arrival_side)
        if target_x == self.x():
            self.finish_interaction_arrival()
            return

        direction = "left" if target_x < self.x() else "right"
        # Landing-on-Food deliberately uses an instant walking orientation.
        # The reusable animated turn is not part of this short reposition.
        self._resume_interaction_walk(
            direction,
            target_x,
            resume_immediately=True,
        )

    def _start_interaction_turn(self, direction, on_complete):
        """Turn toward the current object while guarding its continuation."""
        expected_target = self.interaction_target
        expected_x = self.interaction_target_x
        expected_ui = self.interaction_ui

        def target_is_current():
            return (
                self.interaction_target == expected_target
                and self.interaction_target_x == expected_x
                and self.interaction_ui is expected_ui
            )

        self.start_turn(
            direction,
            on_complete=on_complete,
            can_continue=target_is_current,
            pivot_step=True,
        )

    def finish_interaction_walk(self):
        self.walk_timer.stop()
        self.walk_target_x = None

        if not self._interaction_surface_ready():
            if not self.is_falling:
                self.fall_from_platform()
            return

        self.finish_interaction_arrival()

    def _landed_on_interaction_target(self):
        """Return whether a taskbar landing already overlaps the object."""
        if (
            not self._interaction_surface_ready()
            or self.interaction_target_x is None
        ):
            return False

        return self.x() <= self.interaction_target_x <= self.x() + self.width()

    def finish_interaction_arrival(self, from_landing=False):
        """Commit arrival and enter the object's existing interaction."""
        if self.interaction_target is None:
            return

        # Arrival is committed before any pose/facing work.  Route updates can
        # no longer compare the target X and reverse after a landing or pivot.
        self.interaction_has_arrived = True
        self.walk_timer.stop()
        self.walk_target_x = None

        if self.interaction_target == "food" and from_landing:
            if self.food_arrival_side is None:
                self.food_arrival_side = random.choice(("left", "right"))
            self._start_landed_food_reposition()
            return

        if self.interaction_arrival_settled:
            return

        self.interaction_arrival_settled = True

        if self.interaction_target == "bed":
            # Bed is centred beneath Tama, so deriving a side from the final
            # X position is ambiguous and can flip with walk-frame widths.
            # Preserve the direction she used to approach the Bed instead.
            direction = self.facing_direction
        elif self.interaction_target == "food" and self.food_arrival_side:
            # Final Food orientation is intentionally instantaneous: Tama
            # faces inward from the stored eating side, then eats at once.
            direction = (
                "right" if self.food_arrival_side == "left" else "left"
            )
        else:
            tama_center_x = self.x() + (self.width() // 2)
            direction = (
                "left"
                if self.interaction_target_x < tama_center_x
                else "right"
            )
        self.interaction_final_facing = direction
        self.facing_direction = direction

        # Food begins its eating animation immediately.
        if self.interaction_target == "food":
            self.start_eating()
            return

        if self.interaction_target == "bed":
            self._show_bed_sit_and_schedule_sleep(direction)


    # -----------------------------------------------------
    # EATING
    # -----------------------------------------------------

    def start_eating(self):
        if not self._interaction_surface_ready():
            if not self.is_falling:
                self.fall_from_platform()
            return

        self.walk_timer.stop()
        self.idle_timer.stop()

        self.is_eating = True

        # The eating sprites replace the visible bowl, but
        # the interaction stays locked until the animation ends.
        if self.interaction_ui is not None:
            self.interaction_ui.clear_active_object()

        self.eat_frame_index = 0
        self.eat_frames_shown = 1

        # Choose the eating sprites and offsets
        # based on which way Tama is facing.
        if self.facing_direction == "left":
            self.eating_frames = (
                self.eating_left_frames
            )

            x_offset = (
                self.eating_left_x_offset
            )

            y_offset = (
                self.eating_left_y_offset
            )

        else:
            self.eating_frames = (
                self.eating_right_frames
            )

            x_offset = (
                self.eating_right_x_offset
            )

            y_offset = (
                self.eating_right_y_offset
            )

        frame = self.eating_frames[
            self.eat_frame_index
        ]

        self.set_sprite(frame)

        # First put the eating sprite on the normal ground.
        self.place_on_ground(frame)

        # THEN apply the eating-specific adjustment,
        # otherwise place_on_ground() overwrites Y.
        self.move(
            self.x() + x_offset,
            self.y() + y_offset
        )

        self.eating_timer.start(500)

    def animate_eating(self):
        # 01 -> 02 repeated three times
        # = six frames total.
        if self.eat_frames_shown >= 6:
            self.finish_eating()
            return

        if self.eat_frame_index == 0:
            self.eat_frame_index = 1
        else:
            self.eat_frame_index = 0

        frame = self.eating_frames[
            self.eat_frame_index
        ]

        # Remember Tama's current position so changing
        # eating frames cannot reset the eating offsets.
        current_x = self.x()
        current_y = self.y()

        self.set_sprite(frame)

        self.move(
            current_x,
            current_y
        )

        # Hold the resting/head-down frame a little longer,
        # then make the NOM frame quicker.
        if self.eat_frame_index == 0:
            self.eating_timer.setInterval(500)
        else:
            self.eating_timer.setInterval(300)

        self.eat_frames_shown += 1

    def finish_eating(self):
        self.eating_timer.stop()

        self.is_eating = False

        self.interaction_target = None
        self.interaction_target_x = None
        self.interaction_ui = None
        self.interaction_has_arrived = False
        self.interaction_final_facing = None
        self.interaction_arrival_settled = False
        self.food_arrival_side = None

        # Happy normal Tama again.
        if self.facing_direction == "left":
            self.sit_left()
        else:
            self.sit_right()

    # -----------------------------------------------------
    # TURNING / WALKING
    # -----------------------------------------------------

    def start_walk(
        self,
        direction
    ):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_sleeping
            or self.is_waking
            or self.is_post_land_recovery
            or self.is_turning
        ):
            return

        if (
            self.interaction_target is None
            and direction != self.facing_direction
        ):
            self.start_turn(
                direction,
                on_complete=lambda: self._begin_walk(
                    direction,
                    after_turn=True,
                ),
                pivot_step=True,
            )
            return

        self._begin_walk(direction)

    def start_turn(
        self,
        direction,
        on_complete=None,
        can_continue=None,
        pivot_step=False,
    ):
        path = TURN_FRAME_PATHS.get(
            (self.facing_direction, direction)
        )
        if (
            path is None
            or self.is_turning
            or self.is_carrying
            or self.is_falling
            or self.is_sleeping
            or self.is_waking
            or self.is_post_land_recovery
            or (
                self.interaction_target is not None
                and can_continue is None
            )
            or (
                can_continue is not None
                and not can_continue()
            )
        ):
            return

        self.idle_timer.stop()
        self.crouch_start_timer.stop()
        self.crouch_timer.stop()
        self.crouch_end_timer.stop()
        self.walk_timer.stop()
        self.walk_target_x = None

        self.is_turning = True
        self.turn_target_direction = direction
        self.turn_finished_callback = on_complete
        self.turn_continue_condition = can_continue
        self.turn_pivot_step = pivot_step
        self.turn_pivot_applied = 0
        self.turn_sequence = [self.turn_frames[index] for index in path]
        self.turn_frame_index = 0
        self._show_turn_frame()
        self.turn_timer.start(TURN_FRAME_MS)

    def _show_turn_frame(self):
        frame = self.turn_sequence[self.turn_frame_index]
        self.set_sprite(frame)
        self.place_on_ground(frame)
        Tama._apply_turn_pivot_step(self)

    def _apply_turn_pivot_step(self):
        """Apply the optional late, cosmetic step without changing turn state."""
        if not self.turn_pivot_step:
            return

        movement_start_frame = len(self.turn_sequence) - 3
        if self.turn_frame_index < movement_start_frame:
            return

        if self.turn_frame_index == movement_start_frame:
            desired_total = TURN_PIVOT_STEP_PIXELS // 6
        elif self.turn_frame_index == movement_start_frame + 1:
            desired_total = TURN_PIVOT_STEP_PIXELS // 2
        else:
            desired_total = TURN_PIVOT_STEP_PIXELS
        step = desired_total - self.turn_pivot_applied
        if step <= 0:
            return

        direction_sign = -1 if self.turn_target_direction == "left" else 1
        new_x = self.x() + (direction_sign * step)

        # A turn on a window must never step Tama off that platform. Reject
        # only this cosmetic movement; the visual turn and continuation remain.
        if self.current_surface_y is not None:
            new_center_x = new_x + (self.width() // 2)
            if (
                self.current_surface_left is None
                or self.current_surface_right is None
                or new_center_x < self.current_surface_left
                or new_center_x > self.current_surface_right
            ):
                return

        moved = self._move_during_walk(
            new_x,
            self.y(),
            direction=self.turn_target_direction,
            stop_on_reject=False,
        )
        if moved:
            self.turn_pivot_applied = desired_total

    def animate_turn(self):
        if (
            not self.is_turning
            or self.is_carrying
            or self.is_falling
            or self.is_post_land_recovery
            or (
                self.turn_continue_condition is not None
                and not self.turn_continue_condition()
            )
            or (
                self.interaction_target is not None
                and self.turn_continue_condition is None
            )
        ):
            self.cancel_turn()
            return

        self.turn_frame_index += 1
        if self.turn_frame_index < len(self.turn_sequence):
            self._show_turn_frame()
            return

        direction = self.turn_target_direction
        on_complete = self.turn_finished_callback
        self.cancel_turn()
        self.facing_direction = direction
        if on_complete is not None:
            on_complete()

    def cancel_turn(self):
        self.turn_timer.stop()
        self.is_turning = False
        self.turn_sequence = []
        self.turn_frame_index = 0
        self.turn_target_direction = None
        self.turn_finished_callback = None
        self.turn_continue_condition = None
        self.turn_pivot_step = False
        self.turn_pivot_applied = 0

    def _begin_walk(self, direction, after_turn=False):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_sleeping
            or self.is_waking
            or self.is_post_land_recovery
        ):
            return

        # A delayed idle/crouch callback must not be allowed to replace walk
        # frames after walking has begun.
        self.idle_timer.stop()
        self.crouch_start_timer.stop()
        self.crouch_timer.stop()
        self.crouch_end_timer.stop()

        self.walk_direction = direction
        self.facing_direction = direction

        frames = (
            self.walk_left_frames
            if direction == "left"
            else self.walk_right_frames
        )
        self.walk_frame_index = (
            1
            if after_turn and len(frames) > 1
            else 0
        )
        self.walk_frame_direction = 1

        distance = random.randint(
            100,
            800
        )

        if (
            self.current_surface_y
            is not None
        ):
            if direction == "left":
                self.walk_target_x = (
                    self.x()
                    - distance
                )
            else:
                self.walk_target_x = (
                    self.x()
                    + distance
                )

            self.walk_timer.start(
                140
            )

            if after_turn:
                self.animate_walk()

            return

        desktop_left, desktop_right = (
            get_taskbar_horizontal_bounds(
                self.x() + (self.width() // 2)
            )
        )

        if direction == "left":
            self.walk_target_x = max(
                desktop_left,
                self.x() - distance
            )

        else:
            right_edge = (
                desktop_right
                - self.width()
                + 1
            )

            self.walk_target_x = min(
                right_edge,
                self.x() + distance
            )

        self.walk_timer.start(
            140
        )

        if after_turn:
            self.animate_walk()

    def stop_walking(self):
        self.walk_timer.stop()
        self.walk_target_x = None

        if self.interaction_target is not None:
            self.finish_interaction_walk()
            return

        if self.walk_direction == "left":
            self.sit_left()
        else:
            self.sit_right()

    def fall_from_platform(self, bonk_navigation=False):
        if self.is_falling:
            return

        # Falling has priority over every ground pose.  Commit the state and
        # cancel all callbacks which could repaint or reposition Tama.
        self.is_falling = True
        self.is_post_land_recovery = False
        # Remember the window Tama is leaving for every kind of platform
        # drop.  The landing scan must not immediately rediscover that same
        # window at its edge and bounce between falling and landing.  Actual
        # bonks still use bonk_drop_pending for their longer recovery pose.
        self.bonk_source_surface_hwnd = self.current_surface_hwnd
        if bonk_navigation:
            self.bonk_drop_pending = True
        self.pose_timer.stop()
        self.walk_timer.stop()
        self.cancel_turn()
        self.idle_timer.stop()

        self.crouch_start_timer.stop()
        self.crouch_timer.stop()
        self.crouch_end_timer.stop()

        self.sleep_timer.stop()
        self.sleep_end_timer.stop()
        self.bed_sleep_pose_timer.stop()
        self.is_sleeping = False
        self.is_waking = False

        self.walk_target_x = None

        self.clear_current_surface()

        self.set_sprite(
            self.get_falling_sprite()
        )

        self.move(
            self.x(),
            self.y() + 2
        )

    def animate_walk(self):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_post_land_recovery
        ):
            self.walk_timer.stop()
            return

        if self.walk_direction == "left":
            frames = self.walk_left_frames
        else:
            frames = self.walk_right_frames

        frame = frames[
            self.walk_frame_index
        ]

        self.set_sprite(
            frame
        )

        self.place_on_ground(
            frame
        )

        self.walk_frame_index += (
            self.walk_frame_direction
        )

        if (
            self.walk_frame_index
            >= len(frames) - 1
        ):
            self.walk_frame_index = (
                len(frames) - 1
            )

            self.walk_frame_direction = -1

        elif self.walk_frame_index <= 0:
            self.walk_frame_index = 0
            self.walk_frame_direction = 1

        # ---------------------------------------------
        # WINDOW WALKING
        # ---------------------------------------------

        if (
            self.current_surface_y
            is not None
        ):

            new_x = self.x() - 10 if self.walk_direction == "left" else self.x() + 10

            if (
                self.interaction_target is not None
                and self._would_cross_mixed_dpi_boundary(new_x, self.y())
            ):
                self.fall_from_platform(bonk_navigation=True)
                return

            if self.walk_direction == "left":
                new_center_x = (
                    new_x
                    + (self.width() // 2)
                )

                if (
                    new_center_x
                    <= self.current_surface_left - WINDOW_PLATFORM_EDGE_GRACE
                ):
                    moved = self._move_during_walk(
                        new_x,
                        self.y()
                    )

                    if moved:
                        self.fall_from_platform()
                    return

                if (
                    new_x
                    <= self.walk_target_x
                ):
                    self._move_during_walk(
                        self.walk_target_x,
                        self.y()
                    )

                    self.stop_walking()
                    return

            else:
                new_center_x = (
                    new_x
                    + (self.width() // 2)
                )

                if (
                    new_center_x
                    > self.current_surface_right + WINDOW_PLATFORM_EDGE_GRACE
                ):
                    moved = self._move_during_walk(
                        new_x,
                        self.y()
                    )

                    if moved:
                        self.fall_from_platform()
                    return

                if (
                    new_x
                    >= self.walk_target_x
                ):
                    self._move_during_walk(
                        self.walk_target_x,
                        self.y()
                    )

                    self.stop_walking()
                    return

            self._move_during_walk(
                new_x,
                self.y()
            )

            return

        # ---------------------------------------------
        # TASKBAR WALKING
        # ---------------------------------------------

        desktop_left, desktop_right = (
            get_taskbar_horizontal_bounds(
                self.x() + (self.width() // 2)
            )
        )

        if self.walk_direction == "left":
            new_x = (
                self.x() - 10
            )

            if (
                new_x
                <= self.walk_target_x
            ):
                self._move_during_walk(
                    self.walk_target_x,
                    self.y()
                )

                self.stop_walking()
                return

            if (
                new_x
                <= desktop_left
            ):
                self._move_during_walk(
                    desktop_left,
                    self.y()
                )

                self.stop_walking()
                return

        else:
            new_x = (
                self.x() + 10
            )

            right_edge = (
                desktop_right
                - self.width()
                + 1
            )

            if (
                new_x
                >= self.walk_target_x
            ):
                self._move_during_walk(
                    self.walk_target_x,
                    self.y()
                )

                self.stop_walking()
                return

            if (
                new_x
                >= right_edge
            ):
                self._move_during_walk(
                    right_edge,
                    self.y()
                )

                self.stop_walking()
                return

        self._move_during_walk(
            new_x,
            self.y()
        )


def main():
    app = QApplication(sys.argv)

    dpi_log(
        f"START executable={sys.executable!r} frozen={getattr(sys, 'frozen', False)} "
        f"pid={os.getpid()} pyside={__import__('PySide6').__version__} "
        f"{windows_dpi_context()}"
    )
    for screen in QApplication.screens():
        geometry = screen.geometry()
        available = screen.availableGeometry()
        dpi_log(
            f"SCREEN name={screen.name()!r} "
            f"geometry={geometry.x()},{geometry.y()},"
            f"{geometry.width()}x{geometry.height()} "
            f"available={available.x()},{available.y()},"
            f"{available.width()}x{available.height()} "
            f"dpr={screen.devicePixelRatio():g} "
            f"logical_dpi={screen.logicalDotsPerInch():g} "
            f"physical_dpi={screen.physicalDotsPerInch():g}"
        )

    signal.signal(
        signal.SIGINT,
        lambda *_: app.quit()
    )

    state = load_state()

    # -------------------------------------------------
    # TAMA
    # -------------------------------------------------

    tama = Tama()
    tama.show()
    tama._log_dpi_state("shown")

    saved_tama = state.get(
        "tama",
        {}
    )

    tama_x = saved_tama.get("x")
    tama_y = saved_tama.get("y")

    if (
        isinstance(tama_x, int)
        and isinstance(tama_y, int)
        and position_is_on_screen(
            tama_x,
            tama_y
        )
    ):
        tama.move(
            tama_x,
            tama_y
        )

        # Tama remembers where she was,
        # but does not assume the old platform
        # still exists.
        #
        # Gravity will immediately find whatever
        # is underneath her now.
        tama.clear_current_surface()

        tama.set_sprite(
            tama.get_falling_sprite()
        )

        tama.is_falling = True

    else:
        QTimer.singleShot(
            0,
            tama.start_on_taskbar
        )

    # -------------------------------------------------
    # TAMAGOTCHI UI
    # -------------------------------------------------

    tama_ui = TamaUI(
        resource_path("assets"),
        tama_window=tama
    )

    saved_ui = state.get(
        "ui",
        {}
    )

    ui_x = saved_ui.get("x")
    ui_y = saved_ui.get("y")

    if (
        isinstance(ui_x, int)
        and isinstance(ui_y, int)
        and position_is_on_screen(
            ui_x,
            ui_y
        )
    ):
        tama_ui.move(
            ui_x,
            ui_y
        )

    else:
        screen = (
            QApplication
            .primaryScreen()
            .availableGeometry()
        )

        tama_ui.move(
            screen.left() + 20,
            screen.top() + 20
        )

    tama_ui.show()
    tama.ignore_platform_window(int(tama_ui.winId()))

    # -------------------------------------------------
    # SAVE MEMORY WHEN TAMA CLOSES
    # -------------------------------------------------

    app.aboutToQuit.connect(
        lambda: save_state(
            tama,
            tama_ui
        )
    )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
