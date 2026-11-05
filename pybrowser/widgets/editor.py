from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSettings, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QKeyEvent, QPainter, QSyntaxHighlighter, QTextCharFormat,
    QTextCursor, QTextFormat,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from ..appearance import apply_code_font


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        definitions = [
            (r"\b(?:False|None|True|and|as|assert|async|await|break|case|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|match|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b", "#569cd6", True),
            (r"\b(?:self|cls)\b", "#9cdcfe", False),
            (r"#[^\n]*", "#6a9955", False),
            (r"\b\d+(?:\.\d+)?\b", "#b5cea8", False),
            (r"(?:[rubfRUBF]*)(?:'[^'\\]*(?:\\.[^'\\]*)*'|\"[^\"\\]*(?:\\.[^\"\\]*)*\")", "#ce9178", False),
        ]
        for pattern, color, bold in definitions:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            fmt.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
            self.rules.append((re.compile(pattern), fmt))

    def highlightBlock(self, text):
        for regex, fmt in self.rules:
            for match in regex.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class Editor(QPlainTextEdit):
    DEDENT_WORDS = {"return", "raise", "break", "continue", "pass"}
    PAIRS = {"(": ")", "[": "]", "{": "}"}

    def __init__(self):
        super().__init__()
        apply_code_font(self)
        settings = QSettings("PyBrowser", "PyBrowser")
        family = settings.value("editor/fontFamily", "0xProto Nerd Font", str)
        size = settings.value("editor/fontSize", 11, int)
        font = QFont(family, size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self.tab_width = settings.value("editor/tabWidth", 4, int)
        self.show_whitespace = settings.value("editor/showWhitespace", False, bool)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._update_extra_selections)
        self.setLineWrapMode(self.LineWrapMode.NoWrap)
        self.set_tab_width(self.tab_width)
        self.set_show_whitespace(self.show_whitespace)
        self.update_line_number_area_width()
        self.highlighter = PythonHighlighter(self.document())

    def set_tab_width(self, width):
        self.tab_width = max(1, int(width))
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * self.tab_width)

    def set_show_whitespace(self, enabled):
        self.show_whitespace = bool(enabled)
        option = self.document().defaultTextOption()
        flags = option.flags()
        whitespace_flags = option.Flag.ShowTabsAndSpaces | option.Flag.ShowLineAndParagraphSeparators
        option.setFlags(flags | whitespace_flags if enabled else flags & ~whitespace_flags)
        self.document().setDefaultTextOption(option)
        self.viewport().update()

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _count=0):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        contents = self.contentsRect()
        self.line_number_area.setGeometry(QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height()))

    def paint_line_numbers(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), self.palette().window())
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                color = self.palette().highlight().color() if block == self.textCursor().block() else self.palette().mid().color()
                painter.setPen(color)
                painter.drawText(0, top, self.line_number_area.width() - 6, height, Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            number += 1
            top += height

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            if event.key() == Qt.Key.Key_Backtab or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._indent_selection(False)
            else:
                self._indent_selection(True)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._smart_newline()
            return
        if event.key() == Qt.Key.Key_Slash and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.toggle_comment()
            return
        text = event.text()
        if text in self.PAIRS and not self.textCursor().hasSelection():
            cursor = self.textCursor()
            cursor.insertText(text + self.PAIRS[text])
            cursor.movePosition(QTextCursor.MoveOperation.Left)
            self.setTextCursor(cursor)
            return
        if text in self.PAIRS.values() and not self.textCursor().hasSelection():
            cursor = self.textCursor()
            if self.document().characterAt(cursor.position()) == text:
                cursor.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cursor)
                return
        super().keyPressEvent(event)

    def _selected_blocks(self):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if end > start and self.document().characterAt(end - 1) == "\u2029":
            end -= 1
        first = self.document().findBlock(start)
        last = self.document().findBlock(end)
        blocks = []
        block = first
        while block.isValid():
            blocks.append(block)
            if block == last:
                break
            block = block.next()
        return blocks

    def _indent_selection(self, indent):
        cursor = self.textCursor()
        if not cursor.hasSelection() and indent:
            column = cursor.positionInBlock()
            spaces = self.tab_width - (column % self.tab_width)
            cursor.insertText(" " * spaces)
            return
        cursor.beginEditBlock()
        for block in self._selected_blocks():
            line_cursor = QTextCursor(block)
            if indent:
                line_cursor.insertText(" " * self.tab_width)
            else:
                text = block.text()
                remove = min(len(text) - len(text.lstrip(" ")), self.tab_width)
                if remove:
                    line_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, remove)
                    line_cursor.removeSelectedText()
                elif text.startswith("\t"):
                    line_cursor.deleteChar()
        cursor.endEditBlock()

    def _smart_newline(self):
        cursor = self.textCursor()
        line = cursor.block().text()
        leading = line[: len(line) - len(line.lstrip())]
        before = line[:cursor.positionInBlock()].rstrip()
        indent = leading
        if before.endswith(":"):
            indent += " " * self.tab_width
        stripped = before.strip()
        first_word = stripped.split(None, 1)[0] if stripped else ""
        if first_word in self.DEDENT_WORDS and len(indent) >= self.tab_width:
            indent = indent[:-self.tab_width]
        cursor.insertText("\n" + indent)
        self.setTextCursor(cursor)

    def toggle_comment(self):
        cursor = self.textCursor()
        blocks = self._selected_blocks()
        meaningful = [block for block in blocks if block.text().strip()]
        uncomment = bool(meaningful) and all(block.text().lstrip().startswith("#") for block in meaningful)
        cursor.beginEditBlock()
        for block in blocks:
            text = block.text()
            if not text.strip():
                continue
            leading = len(text) - len(text.lstrip())
            line_cursor = QTextCursor(block)
            line_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, leading)
            if uncomment:
                line_cursor.deleteChar()
                if self.document().characterAt(line_cursor.position()) == " ":
                    line_cursor.deleteChar()
            else:
                line_cursor.insertText("# ")
        cursor.endEditBlock()

    def _update_extra_selections(self):
        selections = []
        current = QTextEdit.ExtraSelection()
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        current.format.setBackground(QColor("#24272b"))
        current.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selections.append(current)
        selections.extend(self._bracket_selections())
        self.setExtraSelections(selections)
        self.line_number_area.update()

    def _bracket_selections(self):
        cursor = self.textCursor()
        text = self.toPlainText()
        position = cursor.position()
        candidate = None
        if position > 0 and text[position - 1:position] in "()[]{}":
            candidate = position - 1
        elif position < len(text) and text[position:position + 1] in "()[]{}":
            candidate = position
        if candidate is None:
            return []
        match = self._matching_bracket(text, candidate)
        if match is None:
            return []
        selections = []
        for offset in (candidate, match):
            item = QTextEdit.ExtraSelection()
            item.cursor = QTextCursor(self.document())
            item.cursor.setPosition(offset)
            item.cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
            item.format.setBackground(QColor("#5a4d00"))
            item.format.setForeground(QColor("#ffffff"))
            selections.append(item)
        return selections

    @staticmethod
    def _matching_bracket(text, position):
        opening = "([{"
        closing = ")] }".replace(" ", "")
        char = text[position]
        if char in opening:
            target = closing[opening.index(char)]
            depth = 0
            for index in range(position, len(text)):
                if text[index] == char:
                    depth += 1
                elif text[index] == target:
                    depth -= 1
                    if depth == 0:
                        return index
        elif char in closing:
            target = opening[closing.index(char)]
            depth = 0
            for index in range(position, -1, -1):
                if text[index] == char:
                    depth += 1
                elif text[index] == target:
                    depth -= 1
                    if depth == 0:
                        return index
        return None
