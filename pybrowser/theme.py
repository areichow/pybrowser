from PySide6.QtGui import QColor, QPalette


def apply_theme(app, name="dark"):
    app.setStyle("Fusion")
    palette = QPalette()
    if name == "light":
        colors = {
            QPalette.ColorRole.Window: "#f2f2f2",
            QPalette.ColorRole.WindowText: "#202124",
            QPalette.ColorRole.Base: "#ffffff",
            QPalette.ColorRole.AlternateBase: "#e9ecef",
            QPalette.ColorRole.Text: "#202124",
            QPalette.ColorRole.Button: "#e5e7ea",
            QPalette.ColorRole.ButtonText: "#202124",
            QPalette.ColorRole.Highlight: "#2f69a8",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.PlaceholderText: "#6f7378",
        }
        stylesheet = "QListWidget,QPlainTextEdit,QTreeWidget{background:#ffffff;color:#202124;border:1px solid #b8bcc2;selection-background-color:#2f69a8} QSplitter::handle{background:#c7cbd0}"
    else:
        colors = {
            QPalette.ColorRole.Window: "#1e1f22",
            QPalette.ColorRole.WindowText: "#e6e6e6",
            QPalette.ColorRole.Base: "#17181a",
            QPalette.ColorRole.AlternateBase: "#232529",
            QPalette.ColorRole.Text: "#e6e6e6",
            QPalette.ColorRole.Button: "#2b2d31",
            QPalette.ColorRole.ButtonText: "#e6e6e6",
            QPalette.ColorRole.Highlight: "#245f9e",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.PlaceholderText: "#8a8d91",
        }
        stylesheet = "QMenuBar,QMenu,QStatusBar{background:#25272b;color:#e6e6e6} QListWidget,QPlainTextEdit,QTreeWidget{background:#17181a;color:#e6e6e6;border:1px solid #3a3d42;selection-background-color:#245f9e} QSplitter::handle{background:#34363b} QLabel{color:#d9d9da}"
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet + " QListWidget::item{padding:3px 5px}")


def apply_dark_theme(app):
    apply_theme(app, "dark")
