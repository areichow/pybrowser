from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QListWidget

MIME = "application/x-pybrowser-member"
DROP_ROLE = Qt.ItemDataRole.UserRole + 20


class MemberListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(self.DragDropMode.DragOnly)

    def mimeData(self, items):
        data = super().mimeData(items)
        if items:
            data.setData(MIME, QByteArray.number(self.row(items[0])))
        return data


class CategoryListWidget(QListWidget):
    member_dropped = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(self.DragDropMode.DropOnly)
        self._drop_target = None

    def _set_drop_target(self, item):
        if item is self._drop_target:
            return
        if self._drop_target is not None:
            original = self._drop_target.data(DROP_ROLE)
            self._drop_target.setBackground(original if original is not None else QBrush())
            self._drop_target.setData(DROP_ROLE, None)
        self._drop_target = item
        if item is not None:
            item.setData(DROP_ROLE, item.background())
            item.setBackground(QBrush(QColor("#2f78c4")))
        self.viewport().update()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            self._set_drop_target(self.itemAt(event.position().toPoint()))
            event.acceptProposedAction()
        else:
            self._set_drop_target(None)
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._set_drop_target(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        try:
            row = int(bytes(event.mimeData().data(MIME)).decode("ascii"))
        except ValueError:
            self._set_drop_target(None)
            return
        if item is not None:
            category = item.data(Qt.ItemDataRole.UserRole + 2) or item.text()
            self.member_dropped.emit(row, category)
            event.acceptProposedAction()
        self._set_drop_target(None)
