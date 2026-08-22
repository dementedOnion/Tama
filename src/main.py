import sys
import signal
import random
import ctypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel


class Tama(QLabel):
    def __init__(self):
        super().__init__()

        self.is_carrying = False
        self.is_falling = False
        self.is_sleeping = False
        self.is_waking = False

        # Idle sprites
        self.sit_front_sprite = self.load_sprite(
            "assets/sprites/idle/cat_sit_front.png"
        )

        self.sit_left_sprite = self.load_sprite(
            "assets/sprites/idle/cat_sit_left.png"
        )

        self.sit_right_sprite = self.load_sprite(
            "assets/sprites/idle/cat_sit_right.png"
        )

        # Crouch animation
        self.crouch_front_frames = [
            self.load_sprite(
                f"assets/sprites/idle/cat_crouch_front_{i:02}.png"
            )
            for i in range(1, 3)
        ]

        self.crouch_frame_index = 0

        # Sleep animations
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

        # Carry / falling / landing sprites
        self.carry_sprite = self.load_sprite(
            "assets/sprites/carry/cat_carry.png"
        )

        self.falling_sprite = self.load_sprite(
            "assets/sprites/carry/cat_falling.png"
        )

        self.landing_sprite = self.load_sprite(
            "assets/sprites/carry/cat_landing.png"
        )

        # Walking sprites
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

        # Walking state
        self.walk_frame_index = 0
        self.walk_frame_direction = 1
        self.walk_direction = "left"
        self.walk_target_x = None

        # Starting pose
        self.set_sprite(self.sit_front_sprite)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        self.setAttribute(Qt.WA_TranslucentBackground)

        # Mouse-follow timer
        self.carry_timer = QTimer(self)
        self.carry_timer.timeout.connect(self.follow_mouse)
        self.carry_timer.start(16)

        # Gravity timer
        self.gravity_timer = QTimer(self)
        self.gravity_timer.timeout.connect(self.apply_gravity)
        self.gravity_timer.start(16)

        # Landing timer
        self.pose_timer = QTimer(self)
        self.pose_timer.setSingleShot(True)
        self.pose_timer.timeout.connect(self.sit_left)

        # Walking animation timer
        self.walk_timer = QTimer(self)
        self.walk_timer.timeout.connect(self.animate_walk)

        # Random idle behaviour timer
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self.choose_next_action)

        # Delay before crouching
        self.crouch_start_timer = QTimer(self)
        self.crouch_start_timer.setSingleShot(True)
        self.crouch_start_timer.timeout.connect(self.start_crouch)

        # Crouch animation timer
        self.crouch_timer = QTimer(self)
        self.crouch_timer.timeout.connect(self.animate_crouch)

        # Crouch duration timer
        self.crouch_end_timer = QTimer(self)
        self.crouch_end_timer.setSingleShot(True)
        self.crouch_end_timer.timeout.connect(self.finish_crouch)

        # Sleep animation timer
        self.sleep_timer = QTimer(self)
        self.sleep_timer.setSingleShot(True)
        self.sleep_timer.timeout.connect(self.advance_sleep)

        # Overall sleep duration timer
        self.sleep_end_timer = QTimer(self)
        self.sleep_end_timer.setSingleShot(True)
        self.sleep_end_timer.timeout.connect(self.begin_wake)

        # Windows topmost enforcement timer
        self.topmost_timer = QTimer(self)
        self.topmost_timer.timeout.connect(self.keep_on_top)
        self.topmost_timer.start(1000)

        # Place Tama correctly and assert topmost after startup
        QTimer.singleShot(0, self.start_on_taskbar)
        QTimer.singleShot(0, self.keep_on_top)

    def load_sprite(self, path):
        pixmap = QPixmap(path)

        return pixmap.scaled(
            int(pixmap.width() * 0.7),
            int(pixmap.height() * 0.7),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

    def set_sprite(self, sprite):
        self.setPixmap(sprite)
        self.adjustSize()

    def find_visible_bottom(self, pixmap):
        image = pixmap.toImage()

        for y in range(image.height() - 1, -1, -1):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() > 0:
                    return y

        return image.height() - 1

    def place_on_ground(self, sprite):
        screen = QApplication.screenAt(self.pos())

        if screen is None:
            screen = QApplication.primaryScreen()

        desktop = screen.availableGeometry()
        visible_bottom = self.find_visible_bottom(sprite)

        self.move(
            self.x(),
            desktop.bottom() - visible_bottom
        )

    def start_on_taskbar(self):
        self.place_on_ground(self.sit_front_sprite)
        self.schedule_next_action()

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
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
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

            self.set_sprite(self.carry_sprite)

    def follow_mouse(self):
        if self.is_carrying:
            cursor_position = QCursor.pos()

            self.move(
                cursor_position.x() - 73,
                cursor_position.y() - 10
            )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_carrying = False
            self.is_falling = True

            self.set_sprite(self.falling_sprite)

    def apply_gravity(self):
        if not self.is_falling:
            return

        screen = QApplication.screenAt(self.pos())

        if screen is None:
            screen = QApplication.primaryScreen()

        desktop = screen.availableGeometry()
        visible_bottom = self.find_visible_bottom(self.falling_sprite)

        ground_y = desktop.bottom() - visible_bottom

        if self.y() < ground_y:
            self.move(
                self.x(),
                min(self.y() + 8, ground_y)
            )
        else:
            self.is_falling = False
            self.land()

    def land(self):
        self.set_sprite(self.landing_sprite)
        self.place_on_ground(self.landing_sprite)

        self.pose_timer.stop()
        self.pose_timer.start(250)

    def sit_front(self):
        self.set_sprite(self.sit_front_sprite)
        self.place_on_ground(self.sit_front_sprite)

        if random.randint(1, 100) <= 25:
            self.crouch_start_timer.start(1000)
        else:
            self.schedule_next_action()

    def sit_left(self):
        self.set_sprite(self.sit_left_sprite)
        self.place_on_ground(self.sit_left_sprite)

        if random.randint(1, 100) <= 15:
            self.start_sleep("left")
        else:
            self.schedule_next_action()

    def sit_right(self):
        self.set_sprite(self.sit_right_sprite)
        self.place_on_ground(self.sit_right_sprite)

        if random.randint(1, 100) <= 15:
            self.start_sleep("right")
        else:
            self.schedule_next_action()

    def schedule_next_action(self):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_sleeping
            or self.is_waking
        ):
            return

        wait_time = random.randint(2000, 6000)
        self.idle_timer.start(wait_time)

    def choose_next_action(self):
        if self.is_carrying or self.is_falling:
            return

        choice = random.randint(1, 100)

        if choice <= 40:
            self.sit_front()
            return

        if choice <= 70:
            self.start_walk("left")
            return

        self.start_walk("right")

    def start_crouch(self):
        if self.is_carrying or self.is_falling:
            return

        self.idle_timer.stop()

        self.crouch_frame_index = 0
        frame = self.crouch_front_frames[self.crouch_frame_index]

        screen = QApplication.screenAt(self.pos())

        if screen is None:
            screen = QApplication.primaryScreen()

        desktop = screen.availableGeometry()
        visible_bottom = self.find_visible_bottom(frame)

        crouch_y = desktop.bottom() - visible_bottom + 20

        self.move(
            self.x(),
            crouch_y
        )

        self.set_sprite(frame)

        self.crouch_timer.start(500)

        crouch_time = random.randint(2000, 5000)
        self.crouch_end_timer.start(crouch_time)

    def animate_crouch(self):
        if self.is_carrying or self.is_falling:
            self.crouch_timer.stop()
            return

        self.crouch_frame_index += 1

        if self.crouch_frame_index >= len(self.crouch_front_frames):
            self.crouch_frame_index = 0

        frame = self.crouch_front_frames[self.crouch_frame_index]

        self.set_sprite(frame)

    def finish_crouch(self):
        self.crouch_timer.stop()
        self.sit_front()

    def start_sleep(self, direction):
        if self.is_carrying or self.is_falling:
            return

        self.idle_timer.stop()

        self.is_sleeping = True
        self.is_waking = False

        self.sleep_direction = direction

        if direction == "left":
            self.sleep_frames = self.sleep_left_frames
        else:
            self.sleep_frames = self.sleep_right_frames

        self.sleep_phase = 0
        self.sleep_snore_frame = 2

        frame = self.sleep_frames[0]

        self.set_sprite(frame)
        self.place_on_ground(frame)

        self.sleep_timer.start(1500)

    def advance_sleep(self):
        if self.is_carrying or self.is_falling:
            self.sleep_timer.stop()
            return

        if self.is_waking:
            self.advance_wake()
            return

        if self.sleep_phase == 0:
            self.sleep_phase = 1
            self.set_sprite(self.sleep_frames[1])
            self.sleep_timer.start(700)
            return

        if self.sleep_phase == 1:
            self.sleep_phase = 2
            self.set_sprite(self.sleep_frames[2])
            self.sleep_timer.start(700)
            return

        if self.sleep_phase == 2:
            self.sleep_phase = 3
            self.set_sprite(self.sleep_frames[3])

            sleep_time = random.randint(8000, 20000)
            self.sleep_end_timer.start(sleep_time)

            self.sleep_snore_frame = 2
            self.sleep_timer.start(
                random.randint(600, 800)
            )
            return

        if self.sleep_snore_frame == 2:
            self.sleep_snore_frame = 3
        else:
            self.sleep_snore_frame = 2

        self.set_sprite(
            self.sleep_frames[self.sleep_snore_frame]
        )

        self.sleep_timer.start(
            random.randint(600, 800)
        )

    def begin_wake(self):
        if not self.is_sleeping:
            return

        self.sleep_timer.stop()
        self.sleep_end_timer.stop()

        self.is_sleeping = False
        self.is_waking = True
        self.wake_phase = 0

        self.set_sprite(self.sleep_frames[2])
        self.sleep_timer.start(600)

    def advance_wake(self):
        if self.wake_phase == 0:
            self.wake_phase = 1
            self.set_sprite(self.sleep_frames[1])
            self.sleep_timer.start(700)
            return

        if self.wake_phase == 1:
            self.wake_phase = 2
            self.set_sprite(self.sleep_frames[0])
            self.sleep_timer.start(1000)
            return

        self.is_waking = False

        if self.sleep_direction == "left":
            self.sit_left()
        else:
            self.sit_right()

    def start_walk(self, direction):
        if (
            self.is_carrying
            or self.is_falling
            or self.is_sleeping
            or self.is_waking
        ):
            return

        self.walk_direction = direction
        self.walk_frame_index = 0
        self.walk_frame_direction = 1

        screen = QApplication.screenAt(self.pos())

        if screen is None:
            screen = QApplication.primaryScreen()

        desktop = screen.availableGeometry()

        distance = random.randint(80, 400)

        if direction == "left":
            self.walk_target_x = max(
                desktop.left(),
                self.x() - distance
            )

        else:
            right_edge = desktop.right() - self.width() + 1

            self.walk_target_x = min(
                right_edge,
                self.x() + distance
            )

        self.walk_timer.start(140)

    def stop_walking(self):
        self.walk_timer.stop()
        self.walk_target_x = None

        if self.walk_direction == "left":
            self.sit_left()
        else:
            self.sit_right()

    def animate_walk(self):
        if self.is_carrying or self.is_falling:
            self.walk_timer.stop()
            return

        if self.walk_direction == "left":
            frames = self.walk_left_frames
        else:
            frames = self.walk_right_frames

        frame = frames[self.walk_frame_index]

        self.set_sprite(frame)
        self.place_on_ground(frame)

        self.walk_frame_index += self.walk_frame_direction

        if self.walk_frame_index >= len(frames) - 1:
            self.walk_frame_index = len(frames) - 1
            self.walk_frame_direction = -1

        elif self.walk_frame_index <= 0:
            self.walk_frame_index = 0
            self.walk_frame_direction = 1

        screen = QApplication.screenAt(self.pos())

        if screen is None:
            screen = QApplication.primaryScreen()

        desktop = screen.availableGeometry()

        if self.walk_direction == "left":
            new_x = self.x() - 10

            if new_x <= self.walk_target_x:
                self.move(
                    self.walk_target_x,
                    self.y()
                )

                self.stop_walking()
                return

            if new_x <= desktop.left():
                self.move(
                    desktop.left(),
                    self.y()
                )

                self.stop_walking()
                return

        else:
            new_x = self.x() + 10
            right_edge = desktop.right() - self.width() + 1

            if new_x >= self.walk_target_x:
                self.move(
                    self.walk_target_x,
                    self.y()
                )

                self.stop_walking()
                return

            if new_x >= right_edge:
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


app = QApplication(sys.argv)

signal.signal(signal.SIGINT, lambda *_: app.quit())

tama = Tama()
tama.show()

sys.exit(app.exec())