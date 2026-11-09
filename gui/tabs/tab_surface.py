"""
tab_surface.py — Aba de Mapeamento de Superfície em PySide6 com Edição Manual de Pontos.

Funcionalidades:
- Auto-limitação dos eixos X e Y calculados diretamente do G-Code
- Margem de segurança configurável (offset)
- Visualização e atualização da malha de probe no visualizador PyVista 3D
- Point Picking interativo: selecione o ponto clicando no 3D ou na tabela
- Edição manual direta da cota Z com botões de micro-ajuste (±0.01mm, ±0.05mm)
- Tabela interativa com todos os pontos de probe
- Exportação dos pontos editados em TXT (Mach3) ou CSV
- Aplicação da compensação de superfície Z no G-Code
"""

import os
from typing import Callable, List, Optional, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QGroupBox, QScrollArea, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from core.surface_map import (
    HeightMap, apply_surface_map, generate_probe_gcode, generate_probe_points,
)
from core.gcode_parser import get_bounding_box
from gui.theme import set_role, update_role


class SurfaceTab(QWidget):
    """Aba de Mapeamento de Superfície com seleção e edição manual de pontos."""

    def __init__(self, get_blocks_fn: Callable, set_blocks_fn: Callable,
                 preview_widget=None, parent=None):
        super().__init__(parent)
        self._get_blocks = get_blocks_fn
        self._set_blocks = set_blocks_fn
        self._preview = preview_widget
        self._heightmap: Optional[HeightMap] = None

        self._selected_idx: Optional[int] = None
        self._is_updating_table = False

        # Pontos planejados do padrão de varredura (permite exclusões)
        self._pattern_points: List[Tuple[float, float]] = []
        self._pattern_total = 0
        self._pattern_signature = None
        self._selected_pattern_idx: Optional[int] = None

        self._setup_ui()
        if self._preview is not None:
            self._connect_preview_signals()

    def set_preview_widget(self, preview):
        self._preview = preview
        if self._preview is not None:
            self._connect_preview_signals()

    def _connect_preview_signals(self):
        try:
            self._preview.point_selected.connect(self._on_viewer_point_selected)
        except Exception:
            pass
        try:
            self._preview.pattern_point_selected.connect(
                self._on_pattern_point_selected
            )
        except Exception:
            pass
        try:
            target = "pattern" if self._chk_pick_pattern.isChecked() else "measured"
            self._preview.set_pick_target(target)
        except Exception:
            pass

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)

        # ---------------- 1. Limites X / Y da Área de Probing ----------------
        grp_bounds = QGroupBox("📐 Área de Probing (Limites Automáticos X e Y)")
        grp_bounds_layout = QVBoxLayout(grp_bounds)

        lbl_desc = QLabel(
            "Limites calculados automaticamente a partir da peça carregada. "
            "Você pode ajustar ou definir uma margem adicional de folga."
        )
        lbl_desc.setWordWrap(True)
        set_role(lbl_desc, "muted")
        lbl_desc.setStyleSheet("font-size: 11px;")
        grp_bounds_layout.addWidget(lbl_desc)

        grid_bounds = QGridLayout()
        grid_bounds.setSpacing(6)

        grid_bounds.addWidget(QLabel("X Mín (mm):"), 0, 0)
        self._xmin_edit = QLineEdit("0.0")
        self._xmin_edit.textChanged.connect(self._on_grid_param_changed)
        grid_bounds.addWidget(self._xmin_edit, 0, 1)

        grid_bounds.addWidget(QLabel("X Máx (mm):"), 0, 2)
        self._xmax_edit = QLineEdit("100.0")
        self._xmax_edit.textChanged.connect(self._on_grid_param_changed)
        grid_bounds.addWidget(self._xmax_edit, 0, 3)

        grid_bounds.addWidget(QLabel("Y Mín (mm):"), 1, 0)
        self._ymin_edit = QLineEdit("0.0")
        self._ymin_edit.textChanged.connect(self._on_grid_param_changed)
        grid_bounds.addWidget(self._ymin_edit, 1, 1)

        grid_bounds.addWidget(QLabel("Y Máx (mm):"), 1, 2)
        self._ymax_edit = QLineEdit("100.0")
        self._ymax_edit.textChanged.connect(self._on_grid_param_changed)
        grid_bounds.addWidget(self._ymax_edit, 1, 3)

        grid_bounds.addWidget(QLabel("Margem extra (mm):"), 2, 0)
        self._margin_edit = QLineEdit("0.0")
        self._margin_edit.textChanged.connect(self._on_margin_changed)
        grid_bounds.addWidget(self._margin_edit, 2, 1)

        self._btn_reset_bounds = QPushButton("🎯 Limitar ao G-Code")
        self._btn_reset_bounds.setToolTip("Restaura os limites exatos da peça carregada")
        self._btn_reset_bounds.clicked.connect(self._reset_bounds_from_current_gcode)
        grid_bounds.addWidget(self._btn_reset_bounds, 2, 2, 1, 2)

        grp_bounds_layout.addLayout(grid_bounds)
        layout.addWidget(grp_bounds)

        # ---------------- 2. Parâmetros de Sondagem e Geração ----------------
        grp_probe = QGroupBox("🔧 Parâmetros de Sondagem (Probe Routine)")
        grp_probe_layout = QVBoxLayout(grp_probe)

        grid_params = QGridLayout()
        grid_params.setSpacing(6)

        grid_params.addWidget(QLabel("Controlador:"), 0, 0)
        self._cmb_controller = QComboBox()
        self._cmb_controller.addItems(["Mach3 / G-Code Ripper (G31)", "GRBL (G38.2)"])
        grid_params.addWidget(self._cmb_controller, 0, 1)

        grid_params.addWidget(QLabel("Padrão de Varredura:"), 1, 0)
        self._cmb_pattern = QComboBox()
        self._cmb_pattern.addItems([
            "Raster (Unidirecional)",
            "Serpentina (Zig-Zag)",
            "Circular (Anéis Concêntricos)",
        ])
        self._cmb_pattern.setToolTip(
            "Circular: anéis concêntricos inscritos na área delimitada.\n"
            "Em áreas quadradas gera círculos perfeitos; os pontos ficam\n"
            "sempre dentro dos limites X/Y informados."
        )
        self._cmb_pattern.currentIndexChanged.connect(self._on_grid_param_changed)
        grid_params.addWidget(self._cmb_pattern, 1, 1)

        grid_params.addWidget(QLabel("Grid X (pontos):"), 2, 0)
        self._nx_edit = QLineEdit("8")
        self._nx_edit.textChanged.connect(self._on_grid_param_changed)
        grid_params.addWidget(self._nx_edit, 2, 1)

        grid_params.addWidget(QLabel("Grid Y (pontos):"), 3, 0)
        self._ny_edit = QLineEdit("5")
        self._ny_edit.textChanged.connect(self._on_grid_param_changed)
        grid_params.addWidget(self._ny_edit, 3, 1)

        grid_params.addWidget(QLabel("Z Seguro (mm):"), 4, 0)
        self._safe_z_edit = QLineEdit("5.0")
        self._safe_z_edit.textChanged.connect(self._on_grid_param_changed)
        grid_params.addWidget(self._safe_z_edit, 4, 1)

        grid_params.addWidget(QLabel("Z Probing (mm):"), 5, 0)
        self._probe_z_edit = QLineEdit("-5.0")
        grid_params.addWidget(self._probe_z_edit, 5, 1)

        grid_params.addWidget(QLabel("Feed Probe (mm/min):"), 6, 0)
        self._feed_probe_edit = QLineEdit("50.0")
        grid_params.addWidget(self._feed_probe_edit, 6, 1)

        grid_params.addWidget(QLabel("Feed Deslocamento:"), 7, 0)
        self._feed_travel_edit = QLineEdit("1000.0")
        grid_params.addWidget(self._feed_travel_edit, 7, 1)

        grp_probe_layout.addLayout(grid_params)

        self._chk_pick_pattern = QCheckBox("Selecionar pontos do padrão no 3D")
        self._chk_pick_pattern.setToolTip(
            "Quando marcado, o clique no visualizador 3D seleciona um ponto "
            "amarelo do padrão de varredura (em vez de um ponto medido da "
            "tabela). Use para excluir pontos que não devem ser sondados."
        )
        self._chk_pick_pattern.toggled.connect(self._on_pick_target_changed)
        grp_probe_layout.addWidget(self._chk_pick_pattern)

        self._lbl_pattern_status = QLabel("")
        set_role(self._lbl_pattern_status, "muted")
        self._lbl_pattern_status.setStyleSheet("font-size: 11px;")
        self._lbl_pattern_status.setWordWrap(True)
        grp_probe_layout.addWidget(self._lbl_pattern_status)

        h_pattern_btns = QHBoxLayout()
        h_pattern_btns.setSpacing(4)

        self._btn_delete_pattern = QPushButton("🗑️ Excluir Ponto do Padrão")
        set_role(self._btn_delete_pattern, "danger")
        self._btn_delete_pattern.setEnabled(False)
        self._btn_delete_pattern.clicked.connect(self._delete_pattern_point)
        h_pattern_btns.addWidget(self._btn_delete_pattern)

        self._btn_restore_pattern = QPushButton("↺ Restaurar Padrão")
        set_role(self._btn_restore_pattern, "neutral")
        self._btn_restore_pattern.setToolTip(
            "Recria todos os pontos do padrão de varredura, desfazendo as exclusões."
        )
        self._btn_restore_pattern.clicked.connect(self._restore_pattern)
        h_pattern_btns.addWidget(self._btn_restore_pattern)

        grp_probe_layout.addLayout(h_pattern_btns)

        self._btn_generate_probe = QPushButton("📄 Gerar Rotina de Probing")
        set_role(self._btn_generate_probe, "primary")
        self._btn_generate_probe.clicked.connect(self._generate_probe)
        grp_probe_layout.addWidget(self._btn_generate_probe)

        layout.addWidget(grp_probe)

        # ---------------- 3. Importação de Pontos ----------------
        grp_map = QGroupBox("🗺️ Pontos Medidos (Probing Data)")
        grp_map_layout = QVBoxLayout(grp_map)

        self._lbl_points_path = QLabel("Nenhum arquivo de pontos carregado")
        set_role(self._lbl_points_path, "muted")
        self._lbl_points_path.setStyleSheet("font-size: 11px;")
        self._lbl_points_path.setWordWrap(True)
        grp_map_layout.addWidget(self._lbl_points_path)

        h_btn_pts = QHBoxLayout()
        self._btn_import_points = QPushButton("📂 Importar Pontos (TXT / CSV)")
        set_role(self._btn_import_points, "purple")
        self._btn_import_points.clicked.connect(self._import_points)
        h_btn_pts.addWidget(self._btn_import_points)

        self._btn_export_points = QPushButton("💾 Exportar Pontos...")
        set_role(self._btn_export_points, "neutral")
        self._btn_export_points.clicked.connect(self._export_points)
        h_btn_pts.addWidget(self._btn_export_points)
        grp_map_layout.addLayout(h_btn_pts)

        self._lbl_points_info = QLabel("")
        set_role(self._lbl_points_info, "muted")
        self._lbl_points_info.setStyleSheet("font-size: 11px;")
        self._lbl_points_info.setWordWrap(True)
        grp_map_layout.addWidget(self._lbl_points_info)

        layout.addWidget(grp_map)

        # ---------------- 4. Edição Manual do Ponto Selecionado ----------------
        grp_edit = QGroupBox("🎯 Edição Manual do Ponto Selecionado")
        grp_edit_layout = QVBoxLayout(grp_edit)

        lbl_edit_hint = QLabel("💡 Clique sobre um ponto no modelo 3D ou selecione na tabela abaixo.")
        set_role(lbl_edit_hint, "warning")
        lbl_edit_hint.setStyleSheet("font-size: 11px;")
        grp_edit_layout.addWidget(lbl_edit_hint)

        grid_edit = QGridLayout()
        grid_edit.setSpacing(6)

        grid_edit.addWidget(QLabel("Ponto Selecionado:"), 0, 0)
        self._lbl_sel_name = QLabel("Nenhum ponto selecionado")
        set_role(self._lbl_sel_name, "accent")
        grid_edit.addWidget(self._lbl_sel_name, 0, 1)

        grid_edit.addWidget(QLabel("Coordenadas X / Y:"), 1, 0)
        self._lbl_sel_xy = QLabel("X: --  |  Y: --")
        grid_edit.addWidget(self._lbl_sel_xy, 1, 1)

        grid_edit.addWidget(QLabel("Compensação Z (mm):"), 2, 0)
        self._edit_sel_z = QLineEdit("0.0000")
        set_role(self._edit_sel_z, "success")
        self._edit_sel_z.setStyleSheet("font-size: 13px;")
        grid_edit.addWidget(self._edit_sel_z, 2, 1)

        grp_edit_layout.addLayout(grid_edit)

        # Botões de Micro-Ajuste
        h_adjust = QHBoxLayout()
        h_adjust.setSpacing(4)
        for val, txt in [(-0.05, "-0.05"), (-0.01, "-0.01"), (+0.01, "+0.01"), (+0.05, "+0.05")]:
            btn_adj = QPushButton(txt)
            set_role(btn_adj, "subtle")
            btn_adj.clicked.connect(lambda _, delta=val: self._adjust_current_z(delta))
            h_adjust.addWidget(btn_adj)
        grp_edit_layout.addLayout(h_adjust)

        self._btn_save_point = QPushButton("💾 Atualizar Compensação Z deste Ponto")
        set_role(self._btn_save_point, "teal")
        self._btn_save_point.clicked.connect(self._apply_manual_point_edit)
        grp_edit_layout.addWidget(self._btn_save_point)

        layout.addWidget(grp_edit)

        # ---------------- 5. Tabela de Todos os Pontos ----------------
        grp_table = QGroupBox("📋 Tabela de Pontos de Probing")
        grp_table_layout = QVBoxLayout(grp_table)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["#", "X (mm)", "Y (mm)", "Z (mm)"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setMaximumHeight(180)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self._table.itemChanged.connect(self._on_table_item_changed)
        grp_table_layout.addWidget(self._table)

        lbl_table_hint = QLabel(
            "💡 Use Ctrl+clique ou Shift+clique para selecionar vários pontos. "
            "Pressione Delete para excluir os selecionados."
        )
        set_role(lbl_table_hint, "muted")
        lbl_table_hint.setStyleSheet("font-size: 11px;")
        lbl_table_hint.setWordWrap(True)
        grp_table_layout.addWidget(lbl_table_hint)

        self._btn_delete_points = QPushButton("🗑️ Excluir Pontos Selecionados")
        set_role(self._btn_delete_points, "danger")
        self._btn_delete_points.setToolTip(
            "Remove da tabela, do heightmap e da visualização 3D os pontos "
            "selecionados. A exclusão vale para a exportação e para a "
            "compensação Z aplicada ao G-Code."
        )
        self._btn_delete_points.clicked.connect(self._delete_selected_points)
        grp_table_layout.addWidget(self._btn_delete_points)

        self._shortcut_delete = QShortcut(QKeySequence.Delete, self._table)
        self._shortcut_delete.setContext(Qt.WidgetWithChildrenShortcut)
        self._shortcut_delete.activated.connect(self._delete_selected_points)

        layout.addWidget(grp_table)

        # ---------------- 6. Botão Aplicar Nivelamento Z ao G-Code ----------------
        self._btn_apply = QPushButton("✅ Aplicar Compensação Z ao G-Code")
        set_role(self._btn_apply, "success")
        self._btn_apply.setStyleSheet("font-size: 13px;")
        self._btn_apply.clicked.connect(self._apply_map)
        layout.addWidget(self._btn_apply)

        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    # ------------------------------------------------------------------
    # Atualização Automática de Limites do G-Code
    # ------------------------------------------------------------------

    def update_bounds_from_gcode(self, blocks: list):
        if not blocks:
            return

        x_min, x_max, y_min, y_max = get_bounding_box(blocks)
        margin = self._get_float(self._margin_edit, 0.0)

        x_min -= margin
        x_max += margin
        y_min -= margin
        y_max += margin

        self._xmin_edit.setText(f"{x_min:.3f}")
        self._xmax_edit.setText(f"{x_max:.3f}")
        self._ymin_edit.setText(f"{y_min:.3f}")
        self._ymax_edit.setText(f"{y_max:.3f}")

        self._update_preview_probe_grid()

    def _reset_bounds_from_current_gcode(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.information(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return
        self.update_bounds_from_gcode(blocks)

    def _on_margin_changed(self):
        blocks = self._get_blocks()
        if blocks:
            self.update_bounds_from_gcode(blocks)
        else:
            self._update_preview_probe_grid()

    def _on_grid_param_changed(self):
        self._update_preview_probe_grid()

    def _pattern_params(self):
        """Lê os parâmetros atuais do padrão ou retorna None se inválidos."""
        try:
            return (
                float(self._xmin_edit.text()),
                float(self._xmax_edit.text()),
                float(self._ymin_edit.text()),
                float(self._ymax_edit.text()),
                max(2, int(self._nx_edit.text())),
                max(2, int(self._ny_edit.text())),
                self._current_pattern(),
            )
        except ValueError:
            return None

    def _ensure_pattern_points(self):
        """Gera/atualiza os pontos do padrão, preservando exclusões."""
        params = self._pattern_params()
        if params is None:
            return

        if params != self._pattern_signature:
            xmin, xmax, ymin, ymax, nx, ny, pattern = params
            self._pattern_points = generate_probe_points(
                xmin, xmax, ymin, ymax, nx, ny, pattern
            )
            self._pattern_total = len(self._pattern_points)
            self._pattern_signature = params
            self._selected_pattern_idx = None
            self._btn_delete_pattern.setEnabled(False)

        self._update_pattern_status()

    def _update_pattern_status(self):
        """Mostra a quantidade de pontos ativos do padrão no painel."""
        if not self._pattern_points:
            self._lbl_pattern_status.setText(
                "Padrão de varredura: nenhum ponto ativo."
            )
            return

        text = (f"Padrão de varredura: {len(self._pattern_points)} de "
                f"{self._pattern_total} pontos ativos")
        idx = self._selected_pattern_idx
        if idx is not None and 0 <= idx < len(self._pattern_points):
            x, y = self._pattern_points[idx]
            text += f" — selecionado: #{idx + 1} (X: {x:.3f}, Y: {y:.3f})"
        self._lbl_pattern_status.setText(text)

    def _on_pick_target_changed(self, active: bool):
        """Alterna o alvo do clique 3D entre pontos medidos e do padrão."""
        if self._preview is not None:
            try:
                self._preview.set_pick_target("pattern" if active else "measured")
            except Exception:
                pass

        if not active:
            self._selected_pattern_idx = None
            self._btn_delete_pattern.setEnabled(False)
            self._update_pattern_status()

    def _on_pattern_point_selected(self, index: int, x: float, y: float):
        """Recebe o ponto do padrão selecionado no visualizador 3D."""
        if index < 0 or index >= len(self._pattern_points):
            return
        self._selected_pattern_idx = index
        self._btn_delete_pattern.setEnabled(True)
        self._update_pattern_status()

    def _delete_pattern_point(self):
        """Remove do padrão o ponto planejado atualmente selecionado."""
        idx = self._selected_pattern_idx
        if idx is None or idx < 0 or idx >= len(self._pattern_points):
            QMessageBox.information(
                self, "Aviso",
                "Marque 'Selecionar pontos do padrão no 3D', clique em um "
                "ponto amarelo e depois exclua."
            )
            return

        del self._pattern_points[idx]
        self._selected_pattern_idx = None
        self._btn_delete_pattern.setEnabled(False)
        self._update_pattern_status()
        self._update_preview_probe_grid()

    def _restore_pattern(self):
        """Recria todos os pontos do padrão, desfazendo as exclusões."""
        self._pattern_signature = None
        self._selected_pattern_idx = None
        self._btn_delete_pattern.setEnabled(False)
        self._update_preview_probe_grid()

    def _update_preview_probe_grid(self):
        self._ensure_pattern_points()

        if self._preview is None:
            return

        params = self._pattern_params()
        if params is None:
            return

        try:
            xmin, xmax, ymin, ymax, nx, ny, pattern = params
            safe_z = self._get_float(self._safe_z_edit, 5.0)
            probe_z = self._get_float(self._probe_z_edit, -5.0)

            self._preview.set_probe_grid(
                x_min=xmin, x_max=xmax, y_min=ymin, y_max=ymax,
                nx=nx, ny=ny, safe_z=safe_z, probe_z=probe_z,
                pattern=pattern, points=self._pattern_points
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Importação e Tabela de Pontos
    # ------------------------------------------------------------------

    def _import_points(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar Arquivo de Pontos de Probing (Mach3 / TXT / CSV)",
            "",
            "Arquivos de Pontos (*.txt *.csv *.dat *.xyz);;Todos os Arquivos (*.*)"
        )
        if not path:
            return

        try:
            self._heightmap = HeightMap.from_file(path)
            if not self._heightmap.is_valid():
                QMessageBox.warning(self, "Aviso",
                    "O arquivo foi lido mas possui poucos pontos válidos (mínimo de 3 pontos X, Y, Z).")
                return

            self._lbl_points_path.setText(f"📄 {os.path.basename(path)}")
            update_role(self._lbl_points_path, "success")

            n = len(self._heightmap.points_x)

            # Preencher tabela, resumo e visualizador 3D
            self._populate_table()
            self._refresh_points_summary()

            QMessageBox.information(self, "Sucesso",
                f"{n} pontos de probe importados com sucesso!\n"
                f"Clique em qualquer ponto no modelo 3D ou na tabela para ajustar a compensação Z.")
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Importar Pontos", str(e))

    def _populate_table(self):
        """Preenche a tabela com todos os pontos do heightmap."""
        if self._heightmap is None:
            self._table.setRowCount(0)
            return

        self._is_updating_table = True
        n = len(self._heightmap.points_x)
        self._table.setRowCount(n)

        for i in range(n):
            x = self._heightmap.points_x[i]
            y = self._heightmap.points_y[i]
            z = self._heightmap.points_z[i]

            item_id = QTableWidgetItem(f"#{i + 1}")
            item_id.setFlags(item_id.flags() & ~Qt.ItemIsEditable)

            item_x = QTableWidgetItem(f"{x:.3f}")
            item_x.setFlags(item_x.flags() & ~Qt.ItemIsEditable)

            item_y = QTableWidgetItem(f"{y:.3f}")
            item_y.setFlags(item_y.flags() & ~Qt.ItemIsEditable)

            item_z = QTableWidgetItem(f"{z:.4f}")
            # Z é editável diretamente na célula!

            self._table.setItem(i, 0, item_id)
            self._table.setItem(i, 1, item_x)
            self._table.setItem(i, 2, item_y)
            self._table.setItem(i, 3, item_z)

        self._is_updating_table = False

    def _refresh_points_summary(self):
        """Atualiza o resumo dos pontos e a visualização 3D após edições."""
        if self._heightmap is None or len(self._heightmap.points_x) == 0:
            self._lbl_points_info.setText("Nenhum ponto de probe carregado.")
            if self._preview is not None:
                self._preview.set_measured_points([])
            return

        bounds = self._heightmap.bounds
        n = len(self._heightmap.points_x)
        z_min = float(self._heightmap.points_z.min())
        z_max = float(self._heightmap.points_z.max())

        self._lbl_points_info.setText(
            f"✅ {n} pontos carregados!\n"
            f"X: {bounds[0]:.2f} → {bounds[1]:.2f} mm\n"
            f"Y: {bounds[2]:.2f} → {bounds[3]:.2f} mm\n"
            f"Z: {z_min:.3f} → {z_max:.3f} mm (ΔZ: {z_max - z_min:.3f} mm)"
        )

        if self._preview is not None:
            pts_list = list(zip(
                self._heightmap.points_x,
                self._heightmap.points_y,
                self._heightmap.points_z
            ))
            self._preview.set_measured_points(pts_list)

    def _delete_selected_points(self):
        """Exclui da tabela, do heightmap e do 3D os pontos selecionados."""
        if self._heightmap is None or len(self._heightmap.points_x) == 0:
            QMessageBox.information(self, "Aviso", "Nenhum ponto de probe carregado.")
            return

        rows = sorted({
            index.row()
            for index in self._table.selectionModel().selectedRows()
        })
        if not rows and self._selected_idx is not None:
            rows = [self._selected_idx]
        if not rows:
            QMessageBox.information(
                self, "Aviso",
                "Selecione um ou mais pontos na tabela "
                "(Ctrl+clique ou Shift+clique) para excluir."
            )
            return

        n = len(rows)
        answer = QMessageBox.question(
            self, "Excluir Pontos",
            f"Excluir {n} ponto(s) selecionado(s)?\n\n"
            "A exclusão afeta a exportação dos pontos e a compensação Z "
            "aplicada ao G-Code.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return

        removed = self._heightmap.remove_points(rows)
        if removed == 0:
            return

        # Limpar o painel de edição do ponto selecionado
        self._selected_idx = None
        self._lbl_sel_name.setText("Nenhum ponto selecionado")
        self._lbl_sel_xy.setText("X: --  |  Y: --")
        self._edit_sel_z.setText("0.0000")

        self._populate_table()
        self._refresh_points_summary()

        remaining = len(self._heightmap.points_x)
        if self._heightmap.is_valid():
            QMessageBox.information(
                self, "Pontos Excluídos",
                f"{removed} ponto(s) removido(s). Restam {remaining} ponto(s)."
            )
        else:
            QMessageBox.warning(
                self, "Pontos Insuficientes",
                f"{removed} ponto(s) removido(s). Restam {remaining} ponto(s);\n"
                "são necessários pelo menos 3 pontos para aplicar a compensação."
            )

    # ------------------------------------------------------------------
    # Seleção e Edição Manual de Pontos
    # ------------------------------------------------------------------

    def _on_viewer_point_selected(self, index: int, x: float, y: float, z: float):
        """Chamado quando o usuário clica sobre um ponto no visualizador PyVista 3D."""
        if self._heightmap is None:
            return

        self._selected_idx = index
        self._lbl_sel_name.setText(f"Ponto #{index + 1} (de {len(self._heightmap.points_x)})")
        self._lbl_sel_xy.setText(f"X: {x:.3f} mm  |  Y: {y:.3f} mm")
        self._edit_sel_z.setText(f"{z:.4f}")

        # Sincronizar seleção na tabela
        self._is_updating_table = True
        if index < self._table.rowCount():
            self._table.selectRow(index)
            self._table.scrollToItem(self._table.item(index, 0))
        self._is_updating_table = False

    def _on_table_selection_changed(self):
        """Quando o usuário clica em uma linha da tabela, destaca no 3D."""
        if self._is_updating_table or self._heightmap is None:
            return

        selected_rows = self._table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        self._selected_idx = row
        x = float(self._heightmap.points_x[row])
        y = float(self._heightmap.points_y[row])
        z = float(self._heightmap.points_z[row])

        self._lbl_sel_name.setText(f"Ponto #{row + 1}")
        self._lbl_sel_xy.setText(f"X: {x:.3f} mm  |  Y: {y:.3f} mm")
        self._edit_sel_z.setText(f"{z:.4f}")

        # Destacar no PyVista 3D
        if self._preview is not None:
            self._preview.select_point_by_index(row)

    def _on_table_item_changed(self, item: QTableWidgetItem):
        """Permite editar o valor Z diretamente na célula da tabela."""
        if self._is_updating_table or self._heightmap is None or item.column() != 3:
            return

        row = item.row()
        try:
            new_z = float(item.text())
        except ValueError:
            return

        self._update_point_value(row, new_z)

    def _adjust_current_z(self, delta: float):
        """Ajusta o valor de Z com os botões de passo rápido (+0.01, -0.01, etc.)."""
        try:
            cur_z = float(self._edit_sel_z.text())
            new_z = cur_z + delta
            self._edit_sel_z.setText(f"{new_z:.4f}")
            self._apply_manual_point_edit()
        except ValueError:
            pass

    def _apply_manual_point_edit(self):
        """Aplica o valor de Z editado manualmente no campo de texto."""
        if self._heightmap is None or self._selected_idx is None:
            QMessageBox.information(self, "Aviso", "Selecione um ponto de probe primeiro.")
            return

        try:
            new_z = float(self._edit_sel_z.text())
        except ValueError:
            QMessageBox.critical(self, "Erro", "Valor de Z inválido.")
            return

        self._update_point_value(self._selected_idx, new_z)

    def _update_point_value(self, index: int, new_z: float):
        """Atualiza no HeightMap, na tabela e no visualizador PyVista 3D."""
        if self._heightmap is None or index < 0 or index >= len(self._heightmap.points_z):
            return

        # 1. Atualizar no HeightMap e recalcular interpolador
        self._heightmap.update_point_z(index, new_z)

        # 2. Atualizar na tabela
        self._is_updating_table = True
        item = self._table.item(index, 3)
        if item:
            item.setText(f"{new_z:.4f}")
        self._is_updating_table = False

        # 3. Atualizar no visualizador PyVista 3D
        if self._preview is not None:
            self._preview.update_measured_point_z(index, new_z)

    def _export_points(self):
        """Exporta os pontos (com edições manuais) em TXT ou CSV."""
        if self._heightmap is None or len(self._heightmap.points_x) == 0:
            QMessageBox.warning(self, "Aviso", "Nenhum ponto de probe para exportar.")
            return

        path, flt = QFileDialog.getSaveFileName(
            self,
            "Exportar Pontos de Probe",
            "pontos_editados.txt",
            "Arquivo de Texto Mach3 (*.txt);;CSV (*.csv);;Todos os Arquivos (*.*)"
        )
        if not path:
            return

        fmt = "csv" if path.lower().endswith(".csv") else "mach3"
        try:
            self._heightmap.save_to_file(path, format_type=fmt)
            QMessageBox.information(self, "Salvo", f"Pontos de probe salvos em:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Exportar", str(e))

    # ------------------------------------------------------------------
    # Geração de Probe e Aplicação ao G-Code
    # ------------------------------------------------------------------

    def _generate_probe(self):
        try:
            xmin = float(self._xmin_edit.text())
            xmax = float(self._xmax_edit.text())
            ymin = float(self._ymin_edit.text())
            ymax = float(self._ymax_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Erro", "Limites X ou Y inválidos.")
            return

        nx = self._get_int(self._nx_edit, 8)
        ny = self._get_int(self._ny_edit, 5)
        safe_z = self._get_float(self._safe_z_edit, 5.0)
        probe_z = self._get_float(self._probe_z_edit, -5.0)
        feed_probe = self._get_float(self._feed_probe_edit, 50.0)
        feed_travel = self._get_float(self._feed_travel_edit, 1000.0)

        ctrl_choice = self._cmb_controller.currentText()
        controller = "mach3" if "Mach" in ctrl_choice else "grbl"

        pattern = self._current_pattern()

        self._ensure_pattern_points()
        if not self._pattern_points:
            QMessageBox.warning(
                self, "Aviso",
                "O padrão de varredura não possui pontos ativos. "
                "Use 'Restaurar Padrão' ou ajuste os parâmetros."
            )
            return

        try:
            gcode_str = generate_probe_gcode(
                x_min=xmin, x_max=xmax, y_min=ymin, y_max=ymax,
                nx=nx, ny=ny, safe_z=safe_z, probe_z=probe_z,
                feed_probe=feed_probe, feed_travel=feed_travel,
                controller=controller, pattern=pattern,
                points=self._pattern_points
            )
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e))
            return

        default_name = "probe_mach3.gcode" if controller == "mach3" else "probe_grbl.gcode"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Rotina de Probing",
            default_name,
            "Arquivos G-Code (*.gcode *.nc *.tap);;Todos os Arquivos (*.*)"
        )
        if save_path:
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(gcode_str)
            QMessageBox.information(self, "Salvo", f"Rotina de probing salva com sucesso em:\n{save_path}")

    def _apply_map(self):
        blocks = self._get_blocks()
        if not blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        if self._heightmap is None or not self._heightmap.is_valid():
            QMessageBox.warning(self, "Aviso", "Carregue um arquivo de pontos de probe válido primeiro.")
            return

        try:
            result = apply_surface_map(blocks, self._heightmap)
            self._set_blocks(result, "Compensação de superfície Z aplicada com pontos atualizados")
            QMessageBox.information(self, "Sucesso",
                "Compensação de superfície aplicada com sucesso!\n"
                "As alturas de corte do G-Code foram corrigidas de acordo com o relevo editado.\n"
                "Salve o arquivo final pela barra de ferramentas.")
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Aplicar Compensação", str(e))

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------

    def _current_pattern(self) -> str:
        """Converte a opção da interface no padrão aceito pelo núcleo."""
        choice = self._cmb_pattern.currentText()
        if "Raster" in choice:
            return "raster"
        if "Serpentina" in choice:
            return "serpentine"
        return "circular"

    def _get_float(self, edit: QLineEdit, default=0.0):
        try:
            return float(edit.text())
        except ValueError:
            return default

    def _get_int(self, edit: QLineEdit, default=1):
        try:
            return max(1, int(edit.text()))
        except ValueError:
            return default
