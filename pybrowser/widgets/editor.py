from PySide6.QtGui import QColor,QFont,QSyntaxHighlighter,QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit
from ..appearance import apply_code_font
import re
class Highlighter(QSyntaxHighlighter):
    def __init__(self,doc):
        super().__init__(doc);self.rules=[]
        for pattern,color,bold in [(r"\b(?:False|None|True|and|as|assert|async|await|break|case|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|match|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b","#569cd6",True),(r"#[^\n]*","#6a9955",False),(r"\b\d+(?:\.\d+)?\b","#b5cea8",False)]:
            f=QTextCharFormat();f.setForeground(QColor(color));f.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal);self.rules.append((re.compile(pattern),f))
    def highlightBlock(self,text):
        for regex,fmt in self.rules:
            for m in regex.finditer(text):self.setFormat(m.start(),m.end()-m.start(),fmt)
class Editor(QPlainTextEdit):
    def __init__(self):
        super().__init__();apply_code_font(self);self.setLineWrapMode(self.LineWrapMode.NoWrap);self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ")*4);self.highlighter=Highlighter(self.document())
