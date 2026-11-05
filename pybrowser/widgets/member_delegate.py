from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QStyledItemDelegate, QStyle


class MemberDelegate(QStyledItemDelegate):
    PARAM_COLOR = QColor("#f4e3bc")

    def paint(self, painter, option, index):
        painter.save()
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else None
        if style:
            style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = option.rect.adjusted(5, 0, -4, 0)
        duplicate = index.data(Qt.ItemDataRole.UserRole + 1) == "duplicate-definition"
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        foreground_color = foreground.color() if foreground else None
        unsaved = foreground_color is not None and foreground_color.name().casefold() == "#ffd166"
        if option.state & QStyle.StateFlag.State_Selected:
            base_color = option.palette.highlightedText().color()
        elif unsaved:
            base_color = foreground_color
        elif duplicate:
            base_color = QColor("#dca8ac")
        else:
            base_color = foreground_color or option.palette.text().color()
        painter.setFont(option.font)
        marker = text.find("  (")
        if marker < 0:
            painter.setPen(base_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        else:
            name = text[:marker]
            tail = text[marker:]
            painter.setPen(base_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            x = rect.left() + QFontMetrics(option.font).horizontalAdvance(name)
            if option.state & QStyle.StateFlag.State_Selected:
                parameter_color = QColor("#fff1c9")
            elif unsaved:
                parameter_color = foreground_color
            elif duplicate:
                parameter_color = QColor("#dca8ac")
            else:
                parameter_color = self.PARAM_COLOR
            painter.setPen(parameter_color)
            tail_rect = rect.adjusted(x - rect.left(), 0, 0, 0)
            painter.drawText(tail_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, tail)
        painter.restore()
