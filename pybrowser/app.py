from __future__ import annotations
import argparse,sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from .main_window import MainWindow
from .theme import apply_dark_theme
def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument("file",nargs="?",type=Path);args=parser.parse_args(argv);app=QApplication(sys.argv[:1]);apply_dark_theme(app);window=MainWindow(args.file);window.show();return app.exec()
