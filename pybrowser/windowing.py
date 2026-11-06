from __future__ import annotations

from PySide6.QtCore import QObject, QEvent, Qt, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
from shiboken6 import isValid


class MenuKeyboardFilter(QObject):
    """Guarantee conventional keyboard navigation for application menus."""

    def eventFilter(self, watched, event):
        if isinstance(watched, QMenu) and event.type() == QEvent.Type.KeyPress:
            actions = [action for action in watched.actions() if action.isVisible() and not action.isSeparator()]
            enabled = [action for action in actions if action.isEnabled()]
            if not enabled:
                return False
            active = watched.activeAction()
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                try:
                    index = enabled.index(active)
                except ValueError:
                    index = -1 if event.key() == Qt.Key.Key_Down else 0
                delta = 1 if event.key() == Qt.Key.Key_Down else -1
                watched.setActiveAction(enabled[(index + delta) % len(enabled)])
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                if active and active.isEnabled():
                    active.trigger()
                    watched.close()
                    return True
            text = event.text()
            if text.isdigit():
                number = int(text)
                if number == 0:
                    number = 10
                for action in enabled:
                    if action.property("window_number") == number:
                        action.trigger()
                        watched.close()
                        return True
        return False


def install_menu_keyboard_navigation(menu_bar, owner):
    filter_object = MenuKeyboardFilter(owner)
    owner._menu_keyboard_filter = filter_object
    for menu in menu_bar.findChildren(QMenu):
        menu.installEventFilter(filter_object)
    menu_bar.triggered.connect(lambda _action: None)
    return filter_object


def add_window_menu(menu_bar, window, workspace):
    menu = menu_bar.addMenu("&Window")
    menu.setObjectName("windowMenu")

    @Slot()
    def rebuild():
        if not isValid(window) or not isValid(menu):
            return
        menu.clear()
        for number, target in enumerate(workspace.open_windows(), 1):
            if not isValid(target):
                continue
            prefix = f"&{number} " if number <= 9 else f"{number} "
            title = target.windowTitle().replace("[*]", "").strip() or target.__class__.__name__
            action = menu.addAction(prefix + title)
            action.setCheckable(True)
            action.setChecked(target is window)
            action.setProperty("window_number", number)
            action.triggered.connect(lambda checked=False, item=target: workspace.activate_window(item))

    def disconnect_rebuild(_object=None):
        try: workspace.windows_changed.disconnect(rebuild)
        except (RuntimeError, TypeError): pass

    menu.aboutToShow.connect(rebuild)
    workspace.windows_changed.connect(rebuild)
    window.destroyed.connect(disconnect_rebuild)
    rebuild()
    return menu


def install_window_commands(window, workspace, file_menu=None):
    close_action = QAction("Close Window", window)
    close_action.setShortcut(QKeySequence("Ctrl+W"))
    close_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)

    def close_current():
        if getattr(window, "window_kind", "") == "browser" and workspace.browser_count() == 1:
            answer = QMessageBox.question(
                window,
                "Quit PyBrowser?",
                "This is the last Browser window. Do you want to quit PyBrowser?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                workspace.quit_application()
            return
        window.close()

    close_action.triggered.connect(close_current)

    quit_action = QAction("Quit PyBrowser", window)
    quit_action.setShortcut(QKeySequence("Ctrl+Q"))
    quit_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    quit_action.triggered.connect(workspace.quit_application)

    window.addActions([close_action, quit_action])
    if file_menu is not None:
        file_menu.addSeparator()
        file_menu.addAction(close_action)
        file_menu.addAction(quit_action)

    add_window_menu(window.menuBar(), window, workspace)
    install_menu_keyboard_navigation(window.menuBar(), window)
    return close_action, quit_action
