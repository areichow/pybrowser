from PySide6.QtGui import QFont

CODE_FONT_FAMILY = "0xProto Nerd Font"
CODE_FONT_SIZE = 11


def code_font():
    font = QFont(CODE_FONT_FAMILY, CODE_FONT_SIZE)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font


def apply_code_font(widget):
    widget.setFont(code_font())
