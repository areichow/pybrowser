from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout


class TypeCheckPreferencesDialog(QDialog):
    def __init__(self, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Type Checker Settings")
        self.checker = QComboBox()
        self.checker.addItems(["auto", "basedpyright", "pyright"])
        self.checker.setCurrentText(values["checker"])
        self.executable = QLineEdit(values["executable"])
        browse_exe = QPushButton("Browse...")
        browse_exe.clicked.connect(self._browse_executable)
        exe_row = QHBoxLayout(); exe_row.addWidget(self.executable); exe_row.addWidget(browse_exe)
        self.python_path = QLineEdit(values["python_path"])
        browse_python = QPushButton("Browse...")
        browse_python.clicked.connect(self._browse_python)
        py_row = QHBoxLayout(); py_row.addWidget(self.python_path); py_row.addWidget(browse_python)
        form = QFormLayout(); form.addRow("Checker:", self.checker); form.addRow("Executable override:", exe_row); form.addRow("Python interpreter:", py_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self); layout.addLayout(form); layout.addWidget(buttons)

    def _browse_executable(self):
        value, _ = QFileDialog.getOpenFileName(self, "Select Pyright executable")
        if value: self.executable.setText(value)

    def _browse_python(self):
        value, _ = QFileDialog.getOpenFileName(self, "Select Python interpreter")
        if value: self.python_path.setText(value)

    def values(self):
        return {"checker": self.checker.currentText(), "executable": self.executable.text().strip(), "python_path": self.python_path.text().strip()}
