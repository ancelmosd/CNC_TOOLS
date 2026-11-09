"""
tab_splitter.py — Aba de Divisão de Arquivos G-Code em PySide6.
"""

import os
from typing import Callable
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QButtonGroup,
    QFileDialog, QMessageBox, QGroupBox, QScrollArea, QFrame
)
from core.splitter import split_by_lines, split_by_tool_change, split_by_layer, save_parts
from gui.theme import set_role


class SplitterTab(QWidget):
    """Aba de Divisão de Arquivos G-Code por Linhas, Troca de Ferramenta (M6) ou Camada Z."""

    def __init__(self, get_blocks_fn: Callable, parent=None):
        super().__init__(parent)
        self._get_blocks = get_blocks_fn

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

        # ---------------- Modo de Divisão ----------------
        grp_mode = QGroupBox("✂️ Modo de Divisão")
        mode_layout = QVBoxLayout(grp_mode)

        self._btn_group = QButtonGroup(self)

        self._rad_lines = QRadioButton("Por número máximo de linhas")
        self._rad_lines.setChecked(True)
        self._rad_lines.toggled.connect(self._on_mode_change)
        self._btn_group.addButton(self._rad_lines)
        mode_layout.addWidget(self._rad_lines)

        self._rad_tool = QRadioButton("Por troca de ferramenta (M6)")
        self._rad_tool.toggled.connect(self._on_mode_change)
        self._btn_group.addButton(self._rad_tool)
        mode_layout.addWidget(self._rad_tool)

        self._rad_layer = QRadioButton("Por camada / profundidade Z")
        self._rad_layer.toggled.connect(self._on_mode_change)
        self._btn_group.addButton(self._rad_layer)
        mode_layout.addWidget(self._rad_layer)

        layout.addWidget(grp_mode)

        # ---------------- Parâmetros ----------------
        grp_params = QGroupBox("⚙️ Opções")
        params_layout = QGridLayout(grp_params)

        self._lbl_lines = QLabel("Linhas por parte:")
        params_layout.addWidget(self._lbl_lines, 0, 0)
        self._edit_lines = QLineEdit("1000")
        params_layout.addWidget(self._edit_lines, 0, 1)

        self._lbl_tol = QLabel("Tolerância Z (mm):")
        params_layout.addWidget(self._lbl_tol, 1, 0)
        self._edit_tol = QLineEdit("0.001")
        params_layout.addWidget(self._edit_tol, 1, 1)
        self._lbl_tol.setVisible(False)
        self._edit_tol.setVisible(False)

        params_layout.addWidget(QLabel("Prefixo do arquivo:"), 2, 0)
        self._edit_prefix = QLineEdit("parte")
        params_layout.addWidget(self._edit_prefix, 2, 1)

        layout.addWidget(grp_params)

        # Botão Dividir
        btn_split = QPushButton("✂️ Dividir e Salvar Partes...")
        set_role(btn_split, "pink")
        btn_split.setStyleSheet("font-size: 13px;")
        btn_split.clicked.connect(self._apply)
        layout.addWidget(btn_split)

        self._lbl_result = QLabel("")
        set_role(self._lbl_result, "muted")
        self._lbl_result.setStyleSheet("font-size: 11px;")
        self._lbl_result.setWordWrap(True)
        layout.addWidget(self._lbl_result)

        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _on_mode_change(self):
        is_lines = self._rad_lines.isChecked()
        is_layer = self._rad_layer.isChecked()

        self._lbl_lines.setVisible(is_lines)
        self._edit_lines.setVisible(is_lines)
        self._lbl_tol.setVisible(is_layer)
        self._edit_tol.setVisible(is_layer)

    def _apply(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Selecione a Pasta de Destino")
        if not out_dir:
            return

        prefix = self._edit_prefix.text().strip() or "parte"

        try:
            if self._rad_lines.isChecked():
                max_l = max(1, int(self._edit_lines.text()))
                parts = split_by_lines(blocks, max_l)
            elif self._rad_tool.isChecked():
                parts = split_by_tool_change(blocks)
            else:
                tol = float(self._edit_tol.text())
                layer_data = split_by_layer(blocks, tol)
                parts = [blks for _, blks in layer_data]

            saved = save_parts(parts, out_dir, prefix)
            self._lbl_result.setText(f"✅ {len(saved)} arquivos salvos com sucesso em:\n{out_dir}")
            QMessageBox.information(self, "Concluído",
                f"{len(saved)} partes geradas e salvas em:\n{out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Dividir", str(e))
