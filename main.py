"""
main.py — Ponto de entrada do GCode Tools (PySide6 + PyVista / VTK).
"""

import sys
import os

# Adicionar raiz do projeto ao path de busca
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from gui.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GCode Tools")
    app.setOrganizationName("GCode Tools Team")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
