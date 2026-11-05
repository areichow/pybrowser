from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication


def install_window_commands(window, file_menu=None):
    """Install consistent close-window and quit-application actions."""
    close_action = QAction("Close Window", window)
    close_action.setShortcut(QKeySequence.StandardKey.Close)  # Ctrl+W
    close_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    close_action.triggered.connect(window.close)

    quit_action = QAction("Quit PyBrowser", window)
    quit_action.setShortcut(QKeySequence.StandardKey.Quit)  # Ctrl+Q
    quit_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    quit_action.triggered.connect(QApplication.instance().closeAllWindows)

    window.addActions([close_action, quit_action])
    if file_menu is not None:
        file_menu.addSeparator()
        file_menu.addAction(close_action)
        file_menu.addAction(quit_action)
    return close_action, quit_action
