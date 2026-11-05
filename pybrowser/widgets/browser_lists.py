from PySide6.QtCore import QByteArray, QDataStream, QIODevice, Qt, Signal
from PySide6.QtWidgets import QListWidget

MIME = "application/x-pybrowser-member"


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

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME): event.acceptProposedAction()
        else: super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME): event.acceptProposedAction()
        else: super().dragMoveEvent(event)

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return
        try: row = int(bytes(event.mimeData().data(MIME)).decode("ascii"))
        except ValueError: return
        self.member_dropped.emit(row, item.data(Qt.ItemDataRole.UserRole + 2) or item.text())
        event.acceptProposedAction()
