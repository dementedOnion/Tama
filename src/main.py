import sys
import signal

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel


class Tama(QLabel):
    def __init__(self):
        super().__init__()

        self.is_carrying = False
        self.is_falling = False

        self.front_sprite = self.load_sprite("assets/sprites/cat_front.png")
        self.carry_sprite = self.load_sprite("assets/sprites/cat_carry.png")
        self.falling_sprite = self.load_sprite("assets/sprites/cat_falling.png")
        self.crouch_sprite = self.load_sprite("assets/sprites/cat_crouch.png")
        self.stand_left_sprite = self.load_sprite("assets/sprites/cat_left_stand.png")

        self.setPixmap(self.front_sprite)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        self.setAttribute(Qt.WA_TranslucentBackground)

        self.carry_timer = QTimer(self)
        self.carry_timer.timeout.connect(self.follow_mouse)
        self.carry_timer.start(16)

        self.gravity_timer = QTimer(self)
        self.gravity_timer.timeout.connect(self.apply_gravity)
        self.gravity_timer.start(16)

    def load_sprite(self, path):
        return QPixmap(path).scaled(
            170,
            170,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

    def find_visible_bottom(self, pixmap):
        image = pixmap.toImage()

        for y in range(image.height() - 1, -1, -1):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() > 0:
                    return y

        return image.height() - 1

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_carrying = True
            self.is_falling = False
            self.setPixmap(self.carry_sprite)

    def follow_mouse(self):
        if self.is_carrying:
            cursor_position = QCursor.pos()

            self.move(
                cursor_position.x() - 75,
                cursor_position.y() - 15
            )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_carrying = False
            self.is_falling = True
            self.setPixmap(self.falling_sprite)

    def apply_gravity(self):
        if not self.is_falling:
            return

        screen = QApplication.screenAt(self.pos())

        if screen is None:
            screen = QApplication.primaryScreen()

        desktop = screen.availableGeometry()

        visible_bottom = self.find_visible_bottom(self.falling_sprite)

        fall_offset = 12
        ground_y = desktop.bottom() - visible_bottom - fall_offset

        if self.y() < ground_y:
            self.move(
                self.x(),
                min(self.y() + 8, ground_y)
            )
        else:
            self.is_falling = False
            self.land()

    def land(self):
        self.setPixmap(self.crouch_sprite)

        crouch_bottom = self.find_visible_bottom(self.crouch_sprite)

        screen = QApplication.screenAt(self.pos())

        if screen is None:
            screen = QApplication.primaryScreen()

        desktop = screen.availableGeometry()

        crouch_offset = 14

        self.move(
            self.x(),
            desktop.bottom() - crouch_bottom - crouch_offset
        )

        QTimer.singleShot(250, self.stand_left)

    def stand_left(self):
        self.setPixmap(self.stand_left_sprite)

        stand_bottom = self.find_visible_bottom(self.stand_left_sprite)

        screen = QApplication.screenAt(self.pos())

        if screen is None:
            screen = QApplication.primaryScreen()

        desktop = screen.availableGeometry()

        self.move(
            self.x(),
            desktop.bottom() - stand_bottom
        )


app = QApplication(sys.argv)

signal.signal(signal.SIGINT, lambda *_: app.quit())

tama = Tama()
tama.show()

sys.exit(app.exec())