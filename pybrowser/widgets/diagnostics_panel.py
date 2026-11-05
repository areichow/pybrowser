from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget


class DiagnosticsPanel(QWidget):
    activated = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.summary = QLabel("Type checking has not run")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Severity", "Location", "Rule", "Message"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemActivated.connect(self._activated)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree)

    def set_result(self, result):
        self.tree.clear()
        if result.fatal_error:
            self.summary.setText(f"{result.checker or 'Type checker'}: {result.fatal_error}")
            return
        self.summary.setText(f"{result.checker} {result.version}: {result.files_analyzed} file(s), {result.error_count} error(s), {result.warning_count} warning(s), {result.information_count} information message(s), {result.elapsed_seconds:.2f}s")
        colors = {"error": QColor("#ff6b6b"), "warning": QColor("#ffd166"), "information": QColor("#6cb6ff")}
        for diagnostic in result.diagnostics:
            item = QTreeWidgetItem([diagnostic.severity, f"{diagnostic.file.name}:{diagnostic.line}:{diagnostic.column}", diagnostic.rule, diagnostic.message.replace("\n", " ")])
            item.setData(0, Qt.ItemDataRole.UserRole, diagnostic)
            color = colors.get(diagnostic.severity)
            if color:
                item.setForeground(0, color)
            self.tree.addTopLevelItem(item)
        for column in range(3):
            self.tree.resizeColumnToContents(column)

    def _activated(self, item):
        diagnostic = item.data(0, Qt.ItemDataRole.UserRole)
        if diagnostic:
            self.activated.emit(diagnostic)
