import sys
import signal
import random
import ctypes
import json
import os
from pathlib import Path

from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from tama_ui import TamaUI


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

        # Direction Tama is currently facing
        self.facing_direction = "left"
        self.last_cursor_x = None

        # Current platform.
        # hwnd = None means Tama is standing on the taskbar.
        self.current_surface_hwnd = None
        self.current_surface_y = None
        self.current_surface_left = None
        self.current_surface_right = None

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

    def is_window_exposed_at_x(
        self,
        hwnd,
        x,
        window_top
    ):
        if sys.platform != "win32":
            return True

        user32 = ctypes.windll.user32

        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.restype = wintypes.HWND

        point = wintypes.POINT(
            x,
            window_top + 1
        )

        top_hwnd = user32.WindowFromPoint(
            point
        )

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

            class_buffer = (
                ctypes.create_unicode_buffer(
                    256
                )
            )

            user32.GetClassNameW(
                hwnd,
                class_buffer,
                256
            )

            window_class = (
                class_buffer.value
            )

            ignored_classes = {
                "WinUIDesktopWin32WindowClass",
            }

            if (
                window_class
                in ignored_classes
            ):
                return True

            rect = wintypes.RECT()

            if not user32.GetWindowRect(
                hwnd,
                ctypes.byref(rect)
            ):
                return True

            width = (
                rect.right
                - rect.left
            )

            height = (
                rect.bottom
                - rect.top
            )

            if (
                width < 150
                or height < 100
            ):
                return True

            if not (
                rect.left
                <= tama_center_x
                <= rect.right
            ):
                return True

            if not (
                current_paw_y
                <= rect.top
                <= next_paw_y
            ):
                return True

            if not self.is_window_exposed_at_x(
                hwnd,
                tama_center_x,
                rect.top
            ):
                return True

            candidate = (
                hwnd,
                rect.top,
                rect.left,
                rect.right
            )

            if (
                best_surface is None
                or rect.top
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

        rect = wintypes.RECT()

        if not user32.GetWindowRect(
            hwnd,
            ctypes.byref(rect)
        ):
            self.fall_from_platform()
            return

        tama_center_x = (
            self.x()
            + (self.width() // 2)
        )

        if not (
            rect.left
            <= tama_center_x
            <= rect.right
        ):
            self.fall_from_platform()
            return

        if not self.is_window_exposed_at_x(
            hwnd,
            tama_center_x,
            rect.top
        ):
            self.fall_from_platform()
            return

        self.current_surface_y = rect.top
        self.current_surface_left = rect.left
        self.current_surface_right = rect.right

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
            self.is_sleeping = False
            self.is_waking = False

            self.pose_timer.stop()
            self.walk_timer.stop()
            self.idle_timer.stop()

            self.crouch_start_timer.stop()
            self.crouch_timer.stop()
            self.crouch_end_timer.stop()

            self.sleep_timer.stop()
            self.sleep_end_timer.stop()

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

            self.move(
                self.x(),
                (
                    self.current_surface_y
                    - visible_bottom
                )
            )

            self.is_falling = False

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
        self.pose_timer.start(250)

    def finish_landing(self):
        if self.interaction_target is not None:
            self.start_interaction_walk()
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
        self.sit_front()

    # -----------------------------------------------------
    # SLEEP
    # -----------------------------------------------------

    def start_sleep(
        self,
        direction
    ):
        if (
            self.is_carrying
            or self.is_falling
        ):
            return

        self.idle_timer.stop()

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

        if self.sleep_direction == "left":
            self.sit_left()
        else:
            self.sit_right()

    # -----------------------------------------------------
    # INTERACTION SEEKING
    # -----------------------------------------------------

    def seek_interaction(self, interaction_type, target_x, interaction_ui=None):
        """Stop normal idle behaviour and go to a spawned object."""

        self.interaction_target = interaction_type
        self.interaction_target_x = target_x
        self.interaction_ui = interaction_ui

        # Stop Tama choosing unrelated activities.
        self.idle_timer.stop()
        self.crouch_start_timer.stop()
        self.crouch_timer.stop()
        self.crouch_end_timer.stop()

        self.sleep_timer.stop()
        self.sleep_end_timer.stop()

        self.is_sleeping = False
        self.is_waking = False

        self.walk_timer.stop()
        self.walk_target_x = None

        # If Tama is standing on a program window,
        # get her down toward the taskbar first.
        if self.current_surface_y is not None:
            self.fall_from_platform()
            return

        self.start_interaction_walk()

    def start_interaction_walk(self):
        if self.interaction_target is None:
            return

        if self.interaction_target_x is None:
            return

        # Aim Tama's centre roughly at the object's centre.
        target_x = (
            self.interaction_target_x
            - (self.width() // 2)
        )

        if self.interaction_target == "food":
            food_stop_offset = 95

            if target_x < self.x():
                target_x += food_stop_offset
            else:
                target_x -= food_stop_offset

        self.walk_target_x = target_x

        if target_x < self.x():
            self.walk_direction = "left"
            self.facing_direction = "left"
        else:
            self.walk_direction = "right"
            self.facing_direction = "right"

        self.walk_frame_index = 0
        self.walk_frame_direction = 1

        self.walk_timer.start(140)

    def finish_interaction_walk(self):
        self.walk_timer.stop()
        self.walk_target_x = None

        # Food begins its eating animation immediately.
        if self.interaction_target == "food":
            tama_center_x = (
                self.x()
                + (self.width() // 2)
            )

            if self.interaction_target_x < tama_center_x:
                self.facing_direction = "left"
            else:
                self.facing_direction = "right"

            self.start_eating()
            return

        # Other interactions currently just sit facing
        # toward their object.
        tama_center_x = (
            self.x()
            + (self.width() // 2)
        )

        if self.interaction_target_x < tama_center_x:
            self.facing_direction = "left"

            self.set_sprite(
                self.sit_left_sprite
            )

            self.place_on_ground(
                self.sit_left_sprite
            )

        else:
            self.facing_direction = "right"

            self.set_sprite(
                self.sit_right_sprite
            )

            self.place_on_ground(
                self.sit_right_sprite
            )


    # -----------------------------------------------------
    # EATING
    # -----------------------------------------------------

    def start_eating(self):
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

        # Happy normal Tama again.
        if self.facing_direction == "left":
            self.sit_left()
        else:
            self.sit_right()

    # -----------------------------------------------------
    # WALKING
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
        ):
            return

        self.walk_direction = direction
        self.facing_direction = direction

        self.walk_frame_index = 0
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

    def fall_from_platform(self):
        if self.is_falling:
            return

        if (
            self.current_surface_hwnd is not None
            and (
                self.crouch_timer.isActive()
                or self.crouch_end_timer.isActive()
            )
        ):
            return

        self.walk_timer.stop()
        self.idle_timer.stop()

        self.walk_target_x = None

        self.clear_current_surface()

        self.set_sprite(
            self.get_falling_sprite()
        )

        self.move(
            self.x(),
            self.y() + 2
        )

        self.is_falling = True

    def animate_walk(self):
        if (
            self.is_carrying
            or self.is_falling
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

            if self.walk_direction == "left":
                new_x = (
                    self.x() - 10
                )

                new_center_x = (
                    new_x
                    + (self.width() // 2)
                )

                if (
                    new_center_x
                    < self.current_surface_left
                ):
                    self.move(
                        new_x,
                        self.y()
                    )

                    self.fall_from_platform()
                    return

                if (
                    new_x
                    <= self.walk_target_x
                ):
                    self.move(
                        self.walk_target_x,
                        self.y()
                    )

                    self.stop_walking()
                    return

            else:
                new_x = (
                    self.x() + 10
                )

                new_center_x = (
                    new_x
                    + (self.width() // 2)
                )

                if (
                    new_center_x
                    > self.current_surface_right
                ):
                    self.move(
                        new_x,
                        self.y()
                    )

                    self.fall_from_platform()
                    return

                if (
                    new_x
                    >= self.walk_target_x
                ):
                    self.move(
                        self.walk_target_x,
                        self.y()
                    )

                    self.stop_walking()
                    return

            self.move(
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
                self.move(
                    self.walk_target_x,
                    self.y()
                )

                self.stop_walking()
                return

            if (
                new_x
                <= desktop_left
            ):
                self.move(
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
                self.move(
                    self.walk_target_x,
                    self.y()
                )

                self.stop_walking()
                return

            if (
                new_x
                >= right_edge
            ):
                self.move(
                    right_edge,
                    self.y()
                )

                self.stop_walking()
                return

        self.move(
            new_x,
            self.y()
        )


def main():
    app = QApplication(sys.argv)

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
