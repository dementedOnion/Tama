import ctypes
import random
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


class TaskbarObject(QWidget):
    """A transparent taskbar object kept directly behind Tama."""

    def __init__(self, image_path: Path, tama_window=None, y_offset=0, parent=None):
        super().__init__(parent)
        self.tama_window = tama_window
        self.y_offset = y_offset
        self.pixmap = QPixmap(str(image_path))
        if self.pixmap.isNull():
            raise FileNotFoundError(f"Could not load object sprite: {image_path}")

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.pixmap.size())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)

    def place_on_taskbar(self, screen=None):
        screen = screen or QApplication.primaryScreen()
        area = screen.availableGeometry()
        maximum_x = max(area.left(), area.right() - self.width() + 1)
        x = random.randint(area.left(), maximum_x)

        image = self.pixmap.toImage()
        visible_bottom = image.height() - 1
        for y in range(image.height() - 1, -1, -1):
            if any(image.pixelColor(px, y).alpha() for px in range(image.width())):
                visible_bottom = y
                break

        self.move(x, area.bottom() - visible_bottom + self.y_offset)

    def keep_behind_tama(self):
        if sys.platform != "win32" or self.tama_window is None:
            return

        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010

        # Both windows remain in the topmost band, but this window is inserted
        # immediately after (behind) Tama in that band's z-order.
        ctypes.windll.user32.SetWindowPos(
            int(self.winId()),
            int(self.tama_window.winId()),
            0,
            0,
            0,
            0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE,
        )


class TamaUI(QWidget):
    """The draggable Tamagotchi shell and its food/bed menu."""

    OPTIONS = ("food", "bed")
    UI_SCALE = 0.5
    OBJECT_Y_OFFSETS = {"food": 10, "bed": 20}
    PRESS_DURATION_MS = 140

    def __init__(self, assets_root: Path, tama_window=None, parent=None):
        super().__init__(parent)
        self.assets_root = Path(assets_root)
        self.tama_window = tama_window
        ui_root = self.assets_root / "sprites" / "ui"

        self.base = self._load(ui_root / "ui_base" / "ui_pink.png")
        buttons = ui_root / "ui_buttons"
        self.button_pixmaps = {
            "left": (
                self._load(buttons / "left_b_pink.png"),
                self._load(buttons / "left_pressed_pink.png"),
            ),
            "middle": (
                self._load(buttons / "middle_b_pink.png"),
                self._load(buttons / "middle_pressed_pink.png"),
            ),
            "right": (
                self._load(buttons / "right_b_pink.png"),
                self._load(buttons / "right_pressed_pink.png"),
            ),
        }
        icons = ui_root / "ui_icons" / "menu_icons"
        self.icons = {
            "food": self._load(icons / "icon_food.png"),
            "bed": self._load(icons / "icon_bed.png"),
        }
        self.object_paths = {
            name: self.assets_root / "sprites" / "objects" / f"{name}.png"
            for name in self.OPTIONS
        }

        self.selected_index = 0
        self.pressed_button = None
        self.active_button = None
        self.active_object = None
        self.drag_start = None
        self.window_start = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.base.size())

    def _load(self, path: Path):
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise FileNotFoundError(f"Could not load UI sprite: {path}")
        return pixmap.scaled(
            max(1, round(pixmap.width() * self.UI_SCALE)),
            max(1, round(pixmap.height() * self.UI_SCALE)),
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )

    @property
    def selected_option(self):
        return self.OPTIONS[self.selected_index]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.base)
        painter.drawPixmap(0, 0, self.icons[self.selected_option])
        for name, states in self.button_pixmaps.items():
            painter.drawPixmap(0, 0, states[name == self.pressed_button])

    def _button_at(self, point):
        # The aligned button art doubles as its exact, alpha-aware hit mask.
        for name, (normal, _) in self.button_pixmaps.items():
            if 0 <= point.x() < normal.width() and 0 <= point.y() < normal.height():
                if normal.toImage().pixelColor(point).alpha() > 0:
                    return name
        return None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)

        button = self._button_at(event.position().toPoint())
        if button:
            self.active_button = button
            self.pressed_button = button
            self.update()
        else:
            self.active_button = None
            self.drag_start = event.globalPosition().toPoint()
            self.window_start = self.pos()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.drag_start is not None and event.buttons() & Qt.LeftButton:
            self.move(self.window_start + event.globalPosition().toPoint() - self.drag_start)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)

        button = self.active_button
        self.active_button = None
        self.drag_start = None
        self.window_start = None
        if button:
            QTimer.singleShot(
                self.PRESS_DURATION_MS,
                lambda pressed=button: self._release_button(pressed),
            )
            if button == "left":
                self.selected_index = (self.selected_index - 1) % len(self.OPTIONS)
            elif button == "right":
                self.selected_index = (self.selected_index + 1) % len(self.OPTIONS)
            else:
                self.spawn_selected_object()
            self.update()
        event.accept()

    def _release_button(self, button):
        if self.pressed_button == button:
            self.pressed_button = None
            self.update()

    def spawn_selected_object(self):
        if self.active_object is not None:
            self.active_object.close()
            self.active_object.deleteLater()

        item = TaskbarObject(
            self.object_paths[self.selected_option],
            tama_window=self.tama_window,
            y_offset=self.OBJECT_Y_OFFSETS[self.selected_option],
        )
        item.place_on_taskbar(QApplication.screenAt(self.frameGeometry().center()))
        item.show()
        item.keep_behind_tama()
        QTimer.singleShot(0, item.keep_behind_tama)
        self.active_object = item
        return item
