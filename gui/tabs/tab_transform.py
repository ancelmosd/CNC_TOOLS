"""
tab_transform.py — Aba de Transformações Geométricas em PySide6.
"""

from typing import Callable
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox, QMessageBox, QScrollArea, QFrame
)
from core import transforms
from gui.theme import set_role


class TransformTab(QWidget):
    """Aba de Transformações Geométricas (Escala, Translação, Espelhamento e Rotação)."""

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

        # ---------------- 1. Escala ----------------
        grp_scale = QGroupBox("📐 Escala (Redimensionar)")
        grp_scale_layout = QGridLayout(grp_scale)

        grp_scale_layout.addWidget(QLabel("Fator X:"), 0, 0)
        self._scale_x = QLineEdit("1.0")
        grp_scale_layout.addWidget(self._scale_x, 0, 1)

        grp_scale_layout.addWidget(QLabel("Fator Y:"), 0, 2)
        self._scale_y = QLineEdit("1.0")
        grp_scale_layout.addWidget(self._scale_y, 0, 3)

        grp_scale_layout.addWidget(QLabel("Fator Z:"), 0, 4)
        self._scale_z = QLineEdit("1.0")
        grp_scale_layout.addWidget(self._scale_z, 0, 5)

        btn_scale = QPushButton("Aplicar Escala")
        set_role(btn_scale, "primary")
        btn_scale.clicked.connect(self._apply_scale)
        grp_scale_layout.addWidget(btn_scale, 1, 0, 1, 6)

        layout.addWidget(grp_scale)

        # ---------------- 2. Translação ----------------
        grp_trans = QGroupBox("↔️ Translação (Mover Origem)")
        grp_trans_layout = QGridLayout(grp_trans)

        grp_trans_layout.addWidget(QLabel("ΔX (mm):"), 0, 0)
        self._trans_x = QLineEdit("0.0")
        grp_trans_layout.addWidget(self._trans_x, 0, 1)

        grp_trans_layout.addWidget(QLabel("ΔY (mm):"), 0, 2)
        self._trans_y = QLineEdit("0.0")
        grp_trans_layout.addWidget(self._trans_y, 0, 3)

        grp_trans_layout.addWidget(QLabel("ΔZ (mm):"), 0, 4)
        self._trans_z = QLineEdit("0.0")
        grp_trans_layout.addWidget(self._trans_z, 0, 5)

        btn_trans = QPushButton("Aplicar Translação")
        set_role(btn_trans, "primary")
        btn_trans.clicked.connect(self._apply_translate)
        grp_trans_layout.addWidget(btn_trans, 1, 0, 1, 6)

        layout.addWidget(grp_trans)

        # ---------------- 3. Espelhamento e Rotação ----------------
        h_layout = QHBoxLayout()

        # Espelho
        grp_mirror = QGroupBox("🪞 Espelhar")
        grp_mirror_layout = QVBoxLayout(grp_mirror)

        btn_mirror_x = QPushButton("Espelhar em X")
        set_role(btn_mirror_x, "purple")
        btn_mirror_x.clicked.connect(lambda: self._apply_mirror('x'))
        grp_mirror_layout.addWidget(btn_mirror_x)

        btn_mirror_y = QPushButton("Espelhar em Y")
        set_role(btn_mirror_y, "purple")
        btn_mirror_y.clicked.connect(lambda: self._apply_mirror('y'))
        grp_mirror_layout.addWidget(btn_mirror_y)

        h_layout.addWidget(grp_mirror)

        # Rotação
        grp_rot = QGroupBox("🔄 Rotação")
        grp_rot_layout = QGridLayout(grp_rot)

        grp_rot_layout.addWidget(QLabel("Ângulo (°):"), 0, 0)
        self._rot_angle = QLineEdit("0.0")
        grp_rot_layout.addWidget(self._rot_angle, 0, 1)

        grp_rot_layout.addWidget(QLabel("Centro X:"), 1, 0)
        self._rot_cx = QLineEdit("0.0")
        grp_rot_layout.addWidget(self._rot_cx, 1, 1)

        grp_rot_layout.addWidget(QLabel("Centro Y:"), 2, 0)
        self._rot_cy = QLineEdit("0.0")
        grp_rot_layout.addWidget(self._rot_cy, 2, 1)

        btn_rotate = QPushButton("Aplicar Rotação")
        set_role(btn_rotate, "teal")
        btn_rotate.clicked.connect(self._apply_rotate)
        grp_rot_layout.addWidget(btn_rotate, 3, 0, 1, 2)

        h_layout.addWidget(grp_rot)
        layout.addLayout(h_layout)

        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _get_float(self, edit: QLineEdit, default=0.0):
        try:
            return float(edit.text())
        except ValueError:
            return default

    def _apply_scale(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        sx = self._get_float(self._scale_x, 1.0)
        sy = self._get_float(self._scale_y, 1.0)
        sz = self._get_float(self._scale_z, 1.0)

        try:
            result = transforms.scale(blocks, sx, sy, sz)
            self._set_blocks(result, f"Escala aplicada: X={sx}, Y={sy}, Z={sz}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))

    def _apply_translate(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        dx = self._get_float(self._trans_x)
        dy = self._get_float(self._trans_y)
        dz = self._get_float(self._trans_z)

        try:
            result = transforms.translate(blocks, dx, dy, dz)
            self._set_blocks(result, f"Translação aplicada: ΔX={dx}, ΔY={dy}, ΔZ={dz}")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))

    def _apply_mirror(self, axis: str):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        try:
            if axis == 'x':
                result = transforms.mirror_x(blocks)
            else:
                result = transforms.mirror_y(blocks)
            self._set_blocks(result, f"Espelhamento em {axis.upper()} aplicado")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))

    def _apply_rotate(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        angle = self._get_float(self._rot_angle)
        cx = self._get_float(self._rot_cx)
        cy = self._get_float(self._rot_cy)

        try:
            result = transforms.rotate(blocks, angle, cx, cy)
            self._set_blocks(result, f"Rotação de {angle}° em torno de ({cx}, {cy})")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))
