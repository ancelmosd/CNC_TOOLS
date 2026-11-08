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
from typing import Callable, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QFileDialog, QMessageBox, QGroupBox, QScrollArea, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt

from core.surface_map import HeightMap, apply_surface_map, generate_probe_gcode
from core.gcode_parser import get_bounding_box


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
        lbl_desc.setStyleSheet("color: #9e9e9e; font-size: 11px;")
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

        self._btn_generate_probe = QPushButton("📄 Gerar Rotina de Probing")
        self._btn_generate_probe.setStyleSheet("background-color: #1565c0; font-weight: bold; padding: 6px;")
        self._btn_generate_probe.clicked.connect(self._generate_probe)
        grp_probe_layout.addWidget(self._btn_generate_probe)

        layout.addWidget(grp_probe)

        # ---------------- 3. Importação de Pontos ----------------
        grp_map = QGroupBox("🗺️ Pontos Medidos (Probing Data)")
        grp_map_layout = QVBoxLayout(grp_map)

        self._lbl_points_path = QLabel("Nenhum arquivo de pontos carregado")
        self._lbl_points_path.setStyleSheet("color: #888888; font-size: 11px;")
        self._lbl_points_path.setWordWrap(True)
        grp_map_layout.addWidget(self._lbl_points_path)

        h_btn_pts = QHBoxLayout()
        self._btn_import_points = QPushButton("📂 Importar Pontos (TXT / CSV)")
        self._btn_import_points.setStyleSheet("background-color: #6a1b9a; font-weight: bold; padding: 6px;")
        self._btn_import_points.clicked.connect(self._import_points)
        h_btn_pts.addWidget(self._btn_import_points)

        self._btn_export_points = QPushButton("💾 Exportar Pontos...")
        self._btn_export_points.setStyleSheet("background-color: #37474f; padding: 6px;")
        self._btn_export_points.clicked.connect(self._export_points)
        h_btn_pts.addWidget(self._btn_export_points)
        grp_map_layout.addLayout(h_btn_pts)

        self._lbl_points_info = QLabel("")
        self._lbl_points_info.setStyleSheet("color: #b0bec5; font-size: 11px;")
        self._lbl_points_info.setWordWrap(True)
        grp_map_layout.addWidget(self._lbl_points_info)

        layout.addWidget(grp_map)

        # ---------------- 4. Edição Manual do Ponto Selecionado ----------------
        grp_edit = QGroupBox("🎯 Edição Manual do Ponto Selecionado")
        grp_edit_layout = QVBoxLayout(grp_edit)

        lbl_edit_hint = QLabel("💡 Clique sobre um ponto no modelo 3D ou selecione na tabela abaixo.")
        lbl_edit_hint.setStyleSheet("color: #ffd54f; font-size: 11px;")
        grp_edit_layout.addWidget(lbl_edit_hint)

        grid_edit = QGridLayout()
        grid_edit.setSpacing(6)

        grid_edit.addWidget(QLabel("Ponto Selecionado:"), 0, 0)
        self._lbl_sel_name = QLabel("Nenhum ponto selecionado")
        self._lbl_sel_name.setStyleSheet("color: #00e5ff; font-weight: bold;")
        grid_edit.addWidget(self._lbl_sel_name, 0, 1)

        grid_edit.addWidget(QLabel("Coordenadas X / Y:"), 1, 0)
        self._lbl_sel_xy = QLabel("X: --  |  Y: --")
        self._lbl_sel_xy.setStyleSheet("color: #e0e0e0;")
        grid_edit.addWidget(self._lbl_sel_xy, 1, 1)

        grid_edit.addWidget(QLabel("Compensação Z (mm):"), 2, 0)
        self._edit_sel_z = QLineEdit("0.0000")
        self._edit_sel_z.setStyleSheet("font-size: 13px; font-weight: bold; color: #69f0ae;")
        grid_edit.addWidget(self._edit_sel_z, 2, 1)

        grp_edit_layout.addLayout(grid_edit)

        # Botões de Micro-Ajuste
        h_adjust = QHBoxLayout()
        h_adjust.setSpacing(4)
        for val, txt in [(-0.05, "-0.05"), (-0.01, "-0.01"), (+0.01, "+0.01"), (+0.05, "+0.05")]:
            btn_adj = QPushButton(txt)
            btn_adj.setStyleSheet("background-color: #2a2a2a; padding: 4px;")
            btn_adj.clicked.connect(lambda _, delta=val: self._adjust_current_z(delta))
            h_adjust.addWidget(btn_adj)
        grp_edit_layout.addLayout(h_adjust)

        self._btn_save_point = QPushButton("💾 Atualizar Compensação Z deste Ponto")
        self._btn_save_point.setStyleSheet("background-color: #00695c; font-weight: bold; padding: 8px;")
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
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self._table.itemChanged.connect(self._on_table_item_changed)
        grp_table_layout.addWidget(self._table)

        layout.addWidget(grp_table)

        # ---------------- 6. Botão Aplicar Nivelamento Z ao G-Code ----------------
        self._btn_apply = QPushButton("✅ Aplicar Compensação Z ao G-Code")
        self._btn_apply.setStyleSheet("background-color: #2e7d32; font-weight: bold; font-size: 13px; padding: 10px;")
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

    def _update_preview_probe_grid(self):
        if self._preview is None:
            return

        try:
            xmin = float(self._xmin_edit.text())
            xmax = float(self._xmax_edit.text())
            ymin = float(self._ymin_edit.text())
            ymax = float(self._ymax_edit.text())
            nx = max(2, int(self._nx_edit.text()))
            ny = max(2, int(self._ny_edit.text()))
            safe_z = self._get_float(self._safe_z_edit, 5.0)
            probe_z = self._get_float(self._probe_z_edit, -5.0)

            self._preview.set_probe_grid(
                x_min=xmin, x_max=xmax, y_min=ymin, y_max=ymax,
                nx=nx, ny=ny, safe_z=safe_z, probe_z=probe_z
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
            self._lbl_points_path.setStyleSheet("color: #81c784; font-weight: bold;")

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

            # Preencher tabela
            self._populate_table()

            # Enviar para o PyVista 3D
            if self._preview is not None:
                pts_list = list(zip(
                    self._heightmap.points_x,
                    self._heightmap.points_y,
                    self._heightmap.points_z
                ))
                self._preview.set_measured_points(pts_list)

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

        pattern_choice = self._cmb_pattern.currentText()
        if "Raster" in pattern_choice:
            pattern = "raster"
        elif "Serpentina" in pattern_choice:
            pattern = "serpentine"
        else:
            pattern = "circular"

        try:
            gcode_str = generate_probe_gcode(
                x_min=xmin, x_max=xmax, y_min=ymin, y_max=ymax,
                nx=nx, ny=ny, safe_z=safe_z, probe_z=probe_z,
                feed_probe=feed_probe, feed_travel=feed_travel,
                controller=controller, pattern=pattern
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
