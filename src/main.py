import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel


class Tama(QLabel):
    def __init__(self):
        super().__init__()

        self.is_carrying = False

        sprite_sheet = QPixmap("assets/sprites/cat_sprite_sheet.png")
        self.idle_sprite = sprite_sheet.copy(10, 500, 170, 170)

        self.carry_sprite = QPixmap("assets/sprites/cat_carry.png").scaled(
            170,
            170,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        self.setPixmap(self.idle_sprite)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )

        self.setAttribute(Qt.WA_TranslucentBackground)

        self.carry_timer = QTimer(self)
        self.carry_timer.timeout.connect(self.follow_mouse)
        self.carry_timer.start(16)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_carrying = True
            self.setPixmap(self.carry_sprite)

    def follow_mouse(self):
        if self.is_carrying:
            cursor_position = QCursor.pos()

            self.move(
                cursor_position.x() - 75,
                cursor_position.y() - 25
            )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_carrying = False

            self.move(
                self.x(),
                self.y() + 20
            )

            self.setPixmap(self.idle_sprite)


app = QApplication(sys.argv)

tama = Tama()
tama.show()

sys.exit(app.exec())