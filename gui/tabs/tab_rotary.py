"""
tab_rotary.py — Aba de 4º Eixo (Rotary Wrapper) com visualização em cilindro 3D.
"""

from typing import Callable, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QGroupBox,
    QMessageBox, QScrollArea, QFrame, QHBoxLayout
)
from core.rotary_wrap import (
    wrap_to_rotary,
    estimate_cylinder_dimensions,
    extract_rotary_trajectories_3d
)


class RotaryTab(QWidget):
    """Aba do Wrapper de 4º Eixo Rotativo com renderização em cilindro 3D."""

    def __init__(self, get_blocks_fn: Callable, set_blocks_fn: Callable,
                 preview_widget=None, parent=None):
        super().__init__(parent)
        self._get_blocks = get_blocks_fn
        self._set_blocks = set_blocks_fn
        self._preview = preview_widget

        self._setup_ui()

    def set_preview_widget(self, preview):
        self._preview = preview

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
            "Converte G-Code plano XY para usinagem em torno / 4º eixo rotativo A.\n"
            "O percurso é enrolado na casca de um cilindro 3D com o diâmetro configurado.\n\n"
            "⚠️ Dica: Se o arquivo tiver comandos G2/G3, converta arcos para G1 antes de aplicar."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        layout.addWidget(lbl_desc)

        # Botão de Estimativa
        btn_est = QPushButton("🔍 Estimar Diâmetro Ideal pelo G-Code")
        btn_est.setStyleSheet("background-color: #37474f; font-weight: bold; padding: 6px;")
        btn_est.clicked.connect(self._estimate)
        layout.addWidget(btn_est)

        self._lbl_est_info = QLabel("")
        self._lbl_est_info.setStyleSheet("color: #80cbc4; font-size: 11px;")
        layout.addWidget(self._lbl_est_info)

        # Configurações do Cilindro
        grp_cfg = QGroupBox("⚙️ Parâmetros do Tarugo Cilíndrico")
        grid = QGridLayout(grp_cfg)
        grid.setSpacing(6)

        grid.addWidget(QLabel("Diâmetro do cilindro (mm):"), 0, 0)
        self._diam_edit = QLineEdit("50.0")
        grid.addWidget(self._diam_edit, 0, 1)

        grid.addWidget(QLabel("Offset angular inicial (°):"), 1, 0)
        self._offset_edit = QLineEdit("0.0")
        grid.addWidget(self._offset_edit, 1, 1)

        grid.addWidget(QLabel("Mapeamento do Eixo:"), 2, 0)
        self._cmb_axis = QComboBox()
        self._cmb_axis.addItems([
            "Y → A (Cilindro no Eixo X - Padrão)",
            "X → A (Cilindro no Eixo Y)"
        ])
        grid.addWidget(self._cmb_axis, 2, 1)

        grid.addWidget(QLabel("Origem do Z:"), 3, 0)
        self._cmb_z_ref = QComboBox()
        self._cmb_z_ref.addItems([
            "Superfície do Tarugo (Z=0 no Raio Externo)",
            "Centro do Eixo (Z=0 no Eixo de Rotação)"
        ])
        grid.addWidget(self._cmb_z_ref, 3, 1)

        layout.addWidget(grp_cfg)

        # Botões de Ação
        h_btn_layout = QHBoxLayout()

        self._btn_preview_rotary = QPushButton("👁️ Pré-visualizar no Cilindro 3D")
        self._btn_preview_rotary.setStyleSheet("background-color: #1565c0; font-weight: bold; font-size: 12px; padding: 10px;")
        self._btn_preview_rotary.clicked.connect(self._preview_rotary)
        h_btn_layout.addWidget(self._btn_preview_rotary)

        layout.addLayout(h_btn_layout)

        self._btn_apply = QPushButton("🔄 Aplicar Wrapper de 4º Eixo ao G-Code")
        self._btn_apply.setStyleSheet("background-color: #00695c; font-weight: bold; font-size: 13px; padding: 12px;")
        self._btn_apply.clicked.connect(self._apply)
        layout.addWidget(self._btn_apply)

        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def _estimate(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        # A estimativa depende do mapeamento selecionado: Y→A enrola o Y,
        # X→A enrola o X. Usar o eixo errado faz o percurso dar mais de uma
        # volta e sobrepor as linhas no cilindro.
        y_to_a = "Y → A" in self._cmb_axis.currentText()
        info = estimate_cylinder_dimensions(blocks, y_to_a=y_to_a)

        axis_name = "X" if y_to_a else "Y"
        wrap_name = "Y" if y_to_a else "X"
        mapping_txt = "Y → A" if y_to_a else "X → A"

        self._lbl_est_info.setText(
            f"Mapeamento: {mapping_txt}\n"
            f"Comprimento da peça no eixo {axis_name}: {info['axis_length']:.2f} mm\n"
            f"Percurso linear {wrap_name} (vira A): {info['wrap_travel']:.2f} mm\n"
            f"Diâmetro mínimo sugerido: {info['suggested_diameter']:.2f} mm"
        )
        self._diam_edit.setText(f"{info['suggested_diameter']:.2f}")

    def _get_params(self):
        try:
            diam = float(self._diam_edit.text())
            if diam <= 0:
                raise ValueError()
        except ValueError:
            QMessageBox.critical(self, "Erro", "Diâmetro do cilindro deve ser um número positivo maior que zero.")
            return None

        try:
            offset = float(self._offset_edit.text())
        except ValueError:
            offset = 0.0

        y_to_a = "Y → A" in self._cmb_axis.currentText()
        zero_at_surface = "Superfície" in self._cmb_z_ref.currentText()

        return diam, offset, y_to_a, zero_at_surface

    def _preview_rotary(self):
        """Renderiza as trajetórias enroladas no cilindro 3D sem modificar o G-Code ainda."""
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        params = self._get_params()
        if not params:
            return
        diam, offset, y_to_a, zero_at_surface = params

        try:
            rotary_data = extract_rotary_trajectories_3d(
                blocks=blocks,
                diameter_mm=diam,
                y_to_a=y_to_a,
                zero_at_surface=zero_at_surface,
                a_offset=offset
            )

            if self._preview is not None:
                self._preview.load_rotary_trajectories(rotary_data)
                axis_name = "X" if y_to_a else "Y"
                QMessageBox.information(self, "Visualização 3D do 4º Eixo",
                    f"O percurso foi enrolado em um cilindro 3D com sucesso!\n\n"
                    f"• Diâmetro: {diam:.2f} mm\n"
                    f"• Eixo Central: Eixo {axis_name}\n"
                    f"• Altura Z: {'Superfície Externa' if zero_at_surface else 'Centro do Eixo'}\n\n"
                    f"Você pode orbitar em 3D para inspecionar o corte ao redor do tarugo.")
        except Exception as e:
            QMessageBox.critical(self, "Erro na Visualização 3D", str(e))

    def _apply(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        params = self._get_params()
        if not params:
            return
        diam, offset, y_to_a, zero_at_surface = params

        try:
            result = wrap_to_rotary(blocks, diameter_mm=diam, y_to_a=y_to_a,
                                    a_offset=offset, zero_at_surface=zero_at_surface)
            axis_txt = "Y→A" if y_to_a else "X→A"
            # O visualizador detecta os metadados do wrap e reconstrói o
            # cilindro automaticamente em _set_blocks → load_blocks.
            self._set_blocks(result, f"Wrapper 4º eixo aplicado: Ø={diam}mm, {axis_txt}, offset={offset}°")

            QMessageBox.information(self, "Sucesso",
                f"G-Code convertido para 4º eixo com sucesso!\n\n"
                f"• Diâmetro: {diam:.2f} mm\n"
                f"• Mapeamento: {axis_txt}\n"
                f"• Offset: {offset}°\n\n"
                f"O percurso está visualizado enrolado no tarugo 3D. Salve o arquivo final pela barra de ferramentas.")
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))
