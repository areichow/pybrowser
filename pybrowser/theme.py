from PySide6.QtGui import QColor, QPalette

def apply_dark_theme(app):
    app.setStyle("Fusion"); p=QPalette()
    colors={QPalette.ColorRole.Window:"#1e1f22",QPalette.ColorRole.WindowText:"#e6e6e6",QPalette.ColorRole.Base:"#17181a",QPalette.ColorRole.AlternateBase:"#232529",QPalette.ColorRole.Text:"#e6e6e6",QPalette.ColorRole.Button:"#2b2d31",QPalette.ColorRole.ButtonText:"#e6e6e6",QPalette.ColorRole.Highlight:"#245f9e",QPalette.ColorRole.HighlightedText:"#ffffff",QPalette.ColorRole.PlaceholderText:"#8a8d91"}
    for role,color in colors.items():p.setColor(role,QColor(color))
    app.setPalette(p);app.setStyleSheet("QMenuBar,QMenu,QStatusBar{background:#25272b;color:#e6e6e6} QListWidget,QPlainTextEdit{background:#17181a;color:#e6e6e6;border:1px solid #3a3d42;selection-background-color:#245f9e} QListWidget::item{padding:3px 5px} QSplitter::handle{background:#34363b} QLabel{color:#d9d9da}")
