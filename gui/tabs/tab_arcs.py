"""
tab_arcs.py — Aba de Conversão de Arcos G2/G3 em PySide6.
"""

from typing import Callable
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox, QGroupBox, QScrollArea, QFrame
)
from core.arc_converter import arc_to_lines


class ArcsTab(QWidget):
    """Aba de Conversão de Arcos (G2/G3) para Segmentos Lineares (G1)."""

    def __init__(self, get_blocks_fn: Callable, set_blocks_fn: Callable, parent=None):
        super().__init__(parent)
        self._get_blocks = get_blocks_fn
        self._set_blocks = set_blocks_fn

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)

        lbl_desc = QLabel(
            "Converte todos os comandos G2 e G3 (arcos circulares) em sequências de "
            "movimentos lineares G1.\n\n"
            "Essencial para controladores que não suportam interpolação circular nativa, "
            "ou antes de aplicar transformações como o 4º eixo (rotary wrap) e auto-leveling."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        layout.addWidget(lbl_desc)

        grp_cfg = QGroupBox("⚙️ Configurações de Precisão")
        grid = QGridLayout(grp_cfg)
        grid.setSpacing(6)

        grid.addWidget(QLabel("Tolerância de corda (mm):"), 0, 0)
        self._edit_tol = QLineEdit("0.01")
        grid.addWidget(self._edit_tol, 0, 1)

        lbl_tip = QLabel("Menor valor = maior precisão e mais segmentos (padrão: 0.01mm).")
        lbl_tip.setStyleSheet("color: #757575; font-size: 10px;")
        grid.addWidget(lbl_tip, 1, 0, 1, 2)

        layout.addWidget(grp_cfg)

        btn_apply = QPushButton("〰️ Converter G2 / G3 → G1")
        btn_apply.setStyleSheet("background-color: #e65100; font-weight: bold; font-size: 13px; padding: 10px;")
        btn_apply.clicked.connect(self._apply)
        layout.addWidget(btn_apply)

        self._lbl_result = QLabel("")
        self._lbl_result.setStyleSheet("color: #81c784; font-size: 11px;")
        self._lbl_result.setWordWrap(True)
        layout.addWidget(self._lbl_result)

        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _apply(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        try:
            tol = float(self._edit_tol.text())
        except ValueError:
            tol = 0.01

        arcs_before = sum(1 for b in blocks if b.command and b.command.upper() in ('G2', 'G02', 'G3', 'G03'))

        try:
            result = arc_to_lines(blocks, tolerance_mm=tol)
            self._set_blocks(result, f"Arcos convertidos: {arcs_before} arcos → segmentos G1 (tol={tol}mm)")
            self._lbl_result.setText(
                f"✅ {arcs_before} arco(s) convertido(s) com sucesso!\n"
                f"Total de linhas no arquivo: {len(result)}"
            )
            QMessageBox.information(self, "Sucesso",
                f"{arcs_before} arcos foram convertidos em segmentos G1 com tolerância de {tol} mm.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))
