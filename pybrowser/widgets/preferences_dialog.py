from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFontComboBox, QSpinBox, QVBoxLayout,
)


class PreferencesDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PyBrowser Preferences")
        self.font_family = QFontComboBox()
        self.font_family.setCurrentFont(QFont(preferences["font_family"]))
        self.font_size = QSpinBox()
        self.font_size.setRange(7, 32)
        self.font_size.setValue(preferences["font_size"])
        self.tab_width = QSpinBox()
        self.tab_width.setRange(1, 12)
        self.tab_width.setValue(preferences["tab_width"])
        self.show_whitespace = QCheckBox()
        self.show_whitespace.setChecked(preferences["show_whitespace"])
        self.dedent_members = QCheckBox()
        self.dedent_members.setChecked(preferences.get("dedent_members", True))
        self.recovery_max_transactions = QSpinBox(); self.recovery_max_transactions.setRange(10, 10000); self.recovery_max_transactions.setValue(preferences.get("recovery_max_transactions", 200))
        self.recovery_min_days = QSpinBox(); self.recovery_min_days.setRange(0, 3650); self.recovery_min_days.setValue(preferences.get("recovery_min_days", 30))
        self.recovery_max_megabytes = QSpinBox(); self.recovery_max_megabytes.setRange(10, 100000); self.recovery_max_megabytes.setValue(preferences.get("recovery_max_megabytes", 500))
        self.theme = QComboBox()
        self.theme.addItems(["Dark", "Light"])
        self.theme.setCurrentText(preferences["theme"].title())
        form = QFormLayout()
        form.addRow("Code font:", self.font_family)
        form.addRow("Font size:", self.font_size)
        form.addRow("Tab width:", self.tab_width)
        form.addRow("Show whitespace:", self.show_whitespace)
        form.addRow("Dedent Member editor:", self.dedent_members)
        form.addRow("Recent completed transactions:", self.recovery_max_transactions)
        form.addRow("Minimum retention days:", self.recovery_min_days)
        form.addRow("Recovery limit (MB):", self.recovery_max_megabytes)
        form.addRow("Theme:", self.theme)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self):
        return {
            "font_family": self.font_family.currentFont().family(),
            "font_size": self.font_size.value(),
            "tab_width": self.tab_width.value(),
            "show_whitespace": self.show_whitespace.isChecked(),
            "dedent_members": self.dedent_members.isChecked(),
            "recovery_max_transactions": self.recovery_max_transactions.value(),
            "recovery_min_days": self.recovery_min_days.value(),
            "recovery_max_megabytes": self.recovery_max_megabytes.value(),
            "theme": self.theme.currentText().lower(),
        }
