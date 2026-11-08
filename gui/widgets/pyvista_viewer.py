"""
pyvista_viewer.py — Visualizador 3D acelerado por hardware (GPU / OpenGL) com seleção de pontos.

Recursos:
- Renderização de percursos G-Code (G1 / G0) a 60 FPS na GPU
- Grade de sondagem planejada
- Pontos medidos em 3D com mapa de cores por altitude Z e malha de superfície
- Point Picking interativo: clique no ponto de probe na cena 3D para selecioná-lo e editá-lo
- Destaque visual do ponto selecionado com marcadores e rótulos 3D
"""

from typing import List, Tuple, Optional
import math
import numpy as np
import pyvista as pv
import vtk
from pyvistaqt import QtInteractor

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QCheckBox, QLabel, QFrame
)
from PySide6.QtCore import Qt, Signal

from core.gcode_parser import GCodeBlock, get_bounding_box_3d
from core.surface_map import generate_probe_points
from core.rotary_wrap import (
    extract_rotary_trajectories_3d,
    rotary_config_from_blocks,
    rotary_workpiece_matrix,
)


class PyVistaGCodeViewer(QWidget):
    """Widget de visualização 3D de G-Code e Probing acelerado por GPU com seleção interativa."""

    # Sinal emitido ao clicar em um ponto medido: (index, x, y, z)
    point_selected = Signal(int, float, float, float)
    # Sinal emitido ao clicar em um ponto planejado do padrão: (index, x, y)
    pattern_point_selected = Signal(int, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._blocks: List[GCodeBlock] = []
        self._bbox = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        # Dados salvos para controle de visibilidade
        self._poly_g1: Optional[pv.PolyData] = None
        self._poly_g0: Optional[pv.PolyData] = None
        self._poly_probe_grid: Optional[pv.PolyData] = None
        self._poly_probe_pts: Optional[pv.PolyData] = None
        self._poly_measured: Optional[pv.PolyData] = None
        self._poly_surface: Optional[pv.PolyData] = None
        self._poly_cylinder: Optional[pv.PolyData] = None
        self._poly_axis_line: Optional[pv.PolyData] = None

        # Ponto atualmente selecionado
        self._selected_index: Optional[int] = None
        self._picking_enabled = False
        # Alvo do clique 3D: "measured" (tabela) ou "pattern" (padrão)
        self._pick_target = "measured"

        # Estado do 4º eixo / simulação
        self._rotary_active = False
        self._rotary_config: Optional[dict] = None
        self._rotary_data: Optional[dict] = None
        self._rotary_motion_mode = "tool"   # "tool" | "workpiece"
        self._rotary_user_matrix: Optional[vtk.vtkMatrix4x4] = None
        self._rotary_actor_names = (
            "g1_cuts", "g0_rapids",
            "rotary_cylinder_mesh", "rotary_center_axis",
        )
        self._last_tool_tip: Optional[Tuple[float, float, float]] = None
        self._last_tool_dir: Tuple[float, float, float] = (0.0, 0.0, -1.0)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # ---------------- Barra Superior de Ferramentas ----------------
        top_bar = QFrame()
        top_bar.setStyleSheet("background-color: #202020; border-radius: 4px; padding: 2px;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(6, 4, 6, 4)
        top_layout.setSpacing(6)

        # Botões de Câmera
        self._btn_iso = QPushButton("3D Iso")
        self._btn_iso.setToolTip("Visualização 3D Isométrica")
        self._btn_iso.clicked.connect(self.view_isometric)
        top_layout.addWidget(self._btn_iso)

        self._btn_top = QPushButton("Topo (XY)")
        self._btn_top.setToolTip("Visualização Superior Plana")
        self._btn_top.clicked.connect(self.view_top)
        top_layout.addWidget(self._btn_top)

        self._btn_front = QPushButton("Frente (XZ)")
        self._btn_front.setToolTip("Visualização Frontal das Alturas Z")
        self._btn_front.clicked.connect(self.view_front)
        top_layout.addWidget(self._btn_front)

        self._btn_side = QPushButton("Lado (YZ)")
        self._btn_side.setToolTip("Visualização Lateral")
        self._btn_side.clicked.connect(self.view_side)
        top_layout.addWidget(self._btn_side)

        self._btn_reset = QPushButton("⊡ Enquadrar")
        self._btn_reset.setToolTip("Enquadrar e Centralizar a Peça")
        self._btn_reset.setStyleSheet("background-color: #1565c0; font-weight: bold;")
        self._btn_reset.clicked.connect(self.reset_camera)
        top_layout.addWidget(self._btn_reset)

        top_layout.addSpacing(10)

        # Botão Modo Seleção de Ponto de Probe
        self._btn_pick_mode = QPushButton("🎯 Clicar Ponto")
        self._btn_pick_mode.setCheckable(True)
        self._btn_pick_mode.setChecked(True)
        self._btn_pick_mode.setToolTip("Quando ativo, clique em um ponto de probe no modelo 3D para selecioná-lo")
        self._btn_pick_mode.setStyleSheet("background-color: #6a1b9a; font-weight: bold;")
        self._btn_pick_mode.toggled.connect(self._toggle_picking_mode)
        top_layout.addWidget(self._btn_pick_mode)

        top_layout.addStretch()

        # Dica de navegação 3D
        hint = QLabel("💡 Clique no ponto para selecionar e editar compensação Z")
        hint.setStyleSheet("color: #ffd54f; font-size: 11px;")
        top_layout.addWidget(hint)

        layout.addWidget(top_bar)

        # ---------------- Área Central: Interactor PyVista / VTK ----------------
        self.plotter = QtInteractor(self)
        self.plotter.set_background("#141414")
        self.plotter.add_axes()
        layout.addWidget(self.plotter.interactor, stretch=1)

        # Ativar picking nativo de pontos
        self._enable_point_picking()

        # ---------------- Barra Inferior de Camadas e Medidas ----------------
        bot_bar = QFrame()
        bot_bar.setStyleSheet("background-color: #1e1e1e; border-radius: 4px; padding: 2px;")
        bot_layout = QHBoxLayout(bot_bar)
        bot_layout.setContentsMargins(8, 3, 8, 3)
        bot_layout.setSpacing(12)

        self._chk_g1 = QCheckBox("Corte (G1)")
        self._chk_g1.setChecked(True)
        self._chk_g1.setStyleSheet("color: #00e5ff; font-weight: bold;")
        self._chk_g1.stateChanged.connect(self._update_visibility)
        bot_layout.addWidget(self._chk_g1)

        self._chk_color_z = QCheckBox("Gradiente Z")
        self._chk_color_z.setChecked(False)
        self._chk_color_z.setStyleSheet("color: #ba68c8; font-weight: bold;")
        self._chk_color_z.setToolTip("Colorir os cortes G1 com gradiente de cores por altitude Z")
        self._chk_color_z.stateChanged.connect(self._refresh_plotter)
        bot_layout.addWidget(self._chk_color_z)

        self._chk_g0 = QCheckBox("Rápidos (G0)")
        self._chk_g0.setChecked(True)
        self._chk_g0.setStyleSheet("color: #ff5252;")
        self._chk_g0.stateChanged.connect(self._update_visibility)
        bot_layout.addWidget(self._chk_g0)

        self._chk_grid = QCheckBox("Grade Probe")
        self._chk_grid.setChecked(True)
        self._chk_grid.setStyleSheet("color: #ffd54f;")
        self._chk_grid.stateChanged.connect(self._update_visibility)
        bot_layout.addWidget(self._chk_grid)

        self._chk_measured = QCheckBox("Pontos Medidos")
        self._chk_measured.setChecked(True)
        self._chk_measured.setStyleSheet("color: #69f0ae; font-weight: bold;")
        self._chk_measured.stateChanged.connect(self._update_visibility)
        bot_layout.addWidget(self._chk_measured)

        self._chk_box = QCheckBox("Caixa 3D")
        self._chk_box.setChecked(True)
        self._chk_box.setStyleSheet("color: #b0bec5;")
        self._chk_box.stateChanged.connect(self._update_visibility)
        bot_layout.addWidget(self._chk_box)

        self._chk_cylinder = QCheckBox("Tarugo 4º Eixo")
        self._chk_cylinder.setChecked(True)
        self._chk_cylinder.setStyleSheet("color: #ffb74d; font-weight: bold;")
        self._chk_cylinder.stateChanged.connect(self._update_visibility)
        self._chk_cylinder.setVisible(False)
        bot_layout.addWidget(self._chk_cylinder)

        bot_layout.addStretch()

        self._dim_label = QLabel("Dimensões: X: 0.0mm | Y: 0.0mm | Z: 0.0mm")
        self._dim_label.setStyleSheet("color: #e0e0e0; font-weight: bold; font-size: 11px;")
        bot_layout.addWidget(self._dim_label)

        layout.addWidget(bot_bar)

    # ------------------------------------------------------------------
    # Câmeras e Vistas
    # ------------------------------------------------------------------

    def view_isometric(self):
        self.plotter.view_isometric()
        self.plotter.render()

    def view_top(self):
        self.plotter.view_xy()
        self.plotter.render()

    def view_front(self):
        self.plotter.view_xz()
        self.plotter.render()

    def view_side(self):
        self.plotter.view_yz()
        self.plotter.render()

    def reset_camera(self):
        self.plotter.reset_camera()
        self.plotter.render()

    # ------------------------------------------------------------------
    # Point Picking e Seleção de Pontos
    # ------------------------------------------------------------------

    def _enable_point_picking(self):
        """Ativa o picking de pontos no interactor PyVista."""
        try:
            self.plotter.enable_point_picking(
                callback=self._on_point_picked,
                show_message=False,
                show_point=False,
                pickable_window=False
            )
            self._picking_enabled = True
        except Exception:
            self._picking_enabled = False

    def _toggle_picking_mode(self, active: bool):
        if active:
            self._enable_point_picking()
            self._btn_pick_mode.setStyleSheet("background-color: #6a1b9a; font-weight: bold;")
        else:
            try:
                self.plotter.disable_picking()
            except Exception:
                pass
            self._picking_enabled = False
            self._btn_pick_mode.setStyleSheet("background-color: #37474f;")

    def set_pick_target(self, target: str):
        """Define se o clique 3D seleciona pontos medidos ou do padrão."""
        self._pick_target = "pattern" if target == "pattern" else "measured"

    def _on_point_picked(self, point):
        """Chamado pelo PyVista quando o usuário clica sobre um ponto no 3D."""
        picked_xyz = np.array(point, dtype=np.float32)

        if self._pick_target == "pattern":
            if self._poly_probe_pts is None or len(self._poly_probe_pts.points) == 0:
                return
            pts = self._poly_probe_pts.points
            closest_idx = int(np.argmin(np.linalg.norm(pts - picked_xyz, axis=1)))
            pt = pts[closest_idx]
            x, y = float(pt[0]), float(pt[1])
            self._draw_highlight_marker(
                closest_idx, x, y, 0.0, label_prefix="Padrão"
            )
            self.pattern_point_selected.emit(closest_idx, x, y)
            return

        if self._poly_measured is None or len(self._poly_measured.points) == 0:
            return

        pts = self._poly_measured.points

        # Encontrar o ponto medido mais próximo
        dists = np.linalg.norm(pts - picked_xyz, axis=1)
        closest_idx = int(np.argmin(dists))

        # Selecionar e destacar
        self.select_point_by_index(closest_idx)

    def select_point_by_index(self, index: int):
        """Destaca o ponto pelo índice e emite o sinal point_selected."""
        if self._poly_measured is None or index < 0 or index >= len(self._poly_measured.points):
            return

        self._selected_index = index
        pt = self._poly_measured.points[index]
        x, y, z = float(pt[0]), float(pt[1]), float(pt[2])

        # Destacar visualmente no PyVista
        self._draw_highlight_marker(index, x, y, z)

        # Emitir sinal Qt para a aba de Superfície
        self.point_selected.emit(index, x, y, z)

    def _draw_highlight_marker(self, index: int, x: float, y: float, z: float,
                               label_prefix: str = "Ponto"):
        """Desenha anel e esfera branca no ponto selecionado com etiqueta de cota Z."""
        self.plotter.remove_actor("selected_probe_highlight", reset_camera=False)
        self.plotter.remove_actor("selected_probe_label", reset_camera=False)

        highlight_poly = pv.PolyData(np.array([[x, y, z]], dtype=np.float32))

        self.plotter.add_mesh(
            highlight_poly,
            color="#ffffff",
            point_size=26,
            render_points_as_spheres=True,
            name="selected_probe_highlight",
            reset_camera=False
        )

        label_txt = [f"{label_prefix} #{index + 1}\nZ: {z:+.4f} mm"]
        self.plotter.add_point_labels(
            highlight_poly,
            label_txt,
            point_color="#ffff00",
            point_size=12,
            text_color="#ffffff",
            font_size=12,
            name="selected_probe_label",
            always_visible=True,
            reset_camera=False
        )
        self.plotter.render()

    def update_measured_point_z(self, index: int, new_z: float):
        """Atualiza a cota Z de um ponto medido e atualiza a cena 3D."""
        if self._poly_measured is None or index < 0 or index >= len(self._poly_measured.points):
            return

        # Atualizar coordenadas
        pts = self._poly_measured.points.copy()
        pts[index, 2] = new_z
        self._poly_measured.points = pts
        self._poly_measured["Offset Z (mm)"] = pts[:, 2]

        # Recalcular malha de superfície 3D
        if len(pts) >= 4:
            try:
                self._poly_surface = self._poly_measured.delaunay_2d()
            except Exception:
                self._poly_surface = None

        # Re-renderizar
        self._refresh_plotter()

        # Manter marcador de destaque no ponto com novo Z
        x, y = float(pts[index, 0]), float(pts[index, 1])
        self._draw_highlight_marker(index, x, y, new_z)

    # ------------------------------------------------------------------
    # Carregamento de G-Code
    # ------------------------------------------------------------------

    def load_blocks(self, blocks: List[GCodeBlock]):
        """Carrega e renderiza o percurso de G-Code com aceleração por GPU."""
        self._blocks = blocks
        self._last_tool_tip = None
        if not blocks:
            self.clear()
            return

        # Se o G-Code já passou pelo wrapper de 4º eixo, reconstrói
        # automaticamente o cilindro e o percurso enrolado.
        rotary_cfg = rotary_config_from_blocks(blocks)
        if rotary_cfg is not None:
            rotary_data = extract_rotary_trajectories_3d(
                blocks,
                diameter_mm=rotary_cfg.get("diameter_mm", 0.0),
                y_to_a=rotary_cfg.get("y_to_a", True),
                zero_at_surface=rotary_cfg.get("zero_at_surface", True),
                a_offset=rotary_cfg.get("a_offset", 0.0),
            )
            self.load_rotary_trajectories(rotary_data)
            return

        # Modo plano normal
        self._rotary_active = False
        self._rotary_config = None
        self._rotary_data = None
        self._rotary_user_matrix = None

        self._bbox = get_bounding_box_3d(blocks)
        xmin, xmax, ymin, ymax, zmin, zmax = self._bbox
        dx = xmax - xmin
        dy = ymax - ymin
        dz = zmax - zmin
        self._dim_label.setText(f"Peça: X: {dx:.2f}mm  |  Y: {dy:.2f}mm  |  Z: {dz:.2f}mm")

        g1_lines = []
        g0_lines = []

        cur_x, cur_y, cur_z = 0.0, 0.0, 0.0

        for b in blocks:
            if not b.is_move:
                continue

            nx = b.x if b.x is not None else cur_x
            ny = b.y if b.y is not None else cur_y
            nz = b.z if b.z is not None else cur_z

            seg = [(cur_x, cur_y, cur_z), (nx, ny, nz)]
            if b.is_rapid:
                g0_lines.append(seg)
            else:
                g1_lines.append(seg)

            cur_x, cur_y, cur_z = nx, ny, nz

        # PolyData G1
        if g1_lines:
            pts_g1 = []
            cells_g1 = []
            idx = 0
            for p1, p2 in g1_lines:
                pts_g1.extend([p1, p2])
                cells_g1.extend([2, idx, idx + 1])
                idx += 2
            self._poly_g1 = pv.PolyData(np.array(pts_g1, dtype=np.float32), lines=np.array(cells_g1))
        else:
            self._poly_g1 = None

        # PolyData G0
        if g0_lines:
            pts_g0 = []
            cells_g0 = []
            idx = 0
            for p1, p2 in g0_lines:
                pts_g0.extend([p1, p2])
                cells_g0.extend([2, idx, idx + 1])
                idx += 2
            self._poly_g0 = pv.PolyData(np.array(pts_g0, dtype=np.float32), lines=np.array(cells_g0))
        else:
            self._poly_g0 = None

        # Limpar cilindro no modo plano normal
        self._poly_cylinder = None
        self._poly_axis_line = None
        self._chk_cylinder.setVisible(False)

        self._refresh_plotter()
        self.plotter.reset_camera()

    def load_rotary_trajectories(self, rotary_data: dict):
        """
        Carrega e renderiza o tarugo cilíndrico 3D com as trajetórias
        de usinagem perfeitamente enroladas na casca do cilindro.
        """
        g1_lines = rotary_data.get("g1_lines", [])
        g0_lines = rotary_data.get("g0_lines", [])
        cyl_info = rotary_data.get("cylinder", {})

        self._rotary_active = True
        self._rotary_config = dict(rotary_data.get("config", {}))
        self._rotary_data = rotary_data
        self._rotary_user_matrix = None
        self._last_tool_tip = None

        # 1. PolyData de Cortes G1 enrolados
        if g1_lines:
            pts_g1 = []
            cells_g1 = []
            idx = 0
            for p1, p2 in g1_lines:
                pts_g1.extend([p1, p2])
                cells_g1.extend([2, idx, idx + 1])
                idx += 2
            self._poly_g1 = pv.PolyData(np.array(pts_g1, dtype=np.float32), lines=np.array(cells_g1))
        else:
            self._poly_g1 = None

        # 2. PolyData de Rápidos G0 enrolados
        if g0_lines:
            pts_g0 = []
            cells_g0 = []
            idx = 0
            for p1, p2 in g0_lines:
                pts_g0.extend([p1, p2])
                cells_g0.extend([2, idx, idx + 1])
                idx += 2
            self._poly_g0 = pv.PolyData(np.array(pts_g0, dtype=np.float32), lines=np.array(cells_g0))
        else:
            self._poly_g0 = None

        # 3. Gerar o Tarugo Cilíndrico 3D
        center = cyl_info.get("center", (0.0, 0.0, 0.0))
        direction = cyl_info.get("direction", (1.0, 0.0, 0.0))
        radius = cyl_info.get("radius", 25.0)
        height = cyl_info.get("height", 100.0)
        axis_name = cyl_info.get("axis", "X")

        self._poly_cylinder = pv.Cylinder(
            center=center,
            direction=direction,
            radius=radius,
            height=height,
            resolution=72,
            capping=True
        )

        # 4. Linha central do eixo de giro
        half_h = height / 2.0
        if axis_name == "X":
            p_start = (center[0] - half_h, 0.0, 0.0)
            p_end = (center[0] + half_h, 0.0, 0.0)
        else:
            p_start = (0.0, center[1] - half_h, 0.0)
            p_end = (0.0, center[1] + half_h, 0.0)

        self._poly_axis_line = pv.Line(p_start, p_end)

        # Atualizar labels e opções visuais
        diam = radius * 2.0
        self._dim_label.setText(
            f"Tarugo 4º Eixo: Diâmetro: {diam:.2f}mm | Comprimento: {height:.2f}mm | Eixo Central: {axis_name}"
        )
        self._chk_cylinder.setVisible(True)
        self._chk_cylinder.setChecked(True)

        self._refresh_plotter()
        self.plotter.view_isometric()
        self.plotter.reset_camera()

    # ------------------------------------------------------------------
    # Grade de Probing e Pontos Medidos
    # ------------------------------------------------------------------

    def set_probe_grid(self, x_min: float, x_max: float, y_min: float, y_max: float,
                       nx: int, ny: int, safe_z: float = 5.0, probe_z: float = -5.0,
                       pattern: str = "raster",
                       points: Optional[List[Tuple[float, float]]] = None):
        """Define a grade/trajetória planejada de probe conforme o padrão."""
        if nx <= 0 or ny <= 0 or (x_min == x_max and y_min == y_max):
            self._poly_probe_grid = None
            self._poly_probe_pts = None
            self._refresh_plotter()
            return

        if points is not None:
            # Pontos explícitos (permite excluir pontos do padrão).
            probe_pts = [(float(x), float(y)) for x, y in points]
            pts = [[x, y, 0.0] for x, y in probe_pts]
            cells = []
            for i in range(len(pts) - 1):
                cells.extend([2, i, i + 1])
        elif pattern == "circular":
            # Desenha a trajetória real (centro + anéis) na ordem de sondagem.
            probe_pts = generate_probe_points(
                x_min, x_max, y_min, y_max, nx, ny, pattern
            )
            pts = [[x, y, 0.0] for x, y in probe_pts]
            cells = []
            for i in range(len(pts) - 1):
                cells.extend([2, i, i + 1])
        else:
            xs = np.linspace(x_min, x_max, nx)
            ys = np.linspace(y_min, y_max, ny)

            pts = []
            cells = []
            idx = 0

            for y in ys:
                pts.extend([[x_min, y, 0.0], [x_max, y, 0.0]])
                cells.extend([2, idx, idx + 1])
                idx += 2

            for x in xs:
                pts.extend([[x, y_min, 0.0], [x, y_max, 0.0]])
                cells.extend([2, idx, idx + 1])
                idx += 2

            probe_pts = [(x, y) for y in ys for x in xs]

        if not probe_pts:
            self._poly_probe_grid = None
            self._poly_probe_pts = None
            self._refresh_plotter()
            return

        lines = np.array(cells) if cells else None
        self._poly_probe_grid = pv.PolyData(np.array(pts, dtype=np.float32), lines=lines)

        touch_pts = [[float(x), float(y), 0.0] for x, y in probe_pts]
        self._poly_probe_pts = pv.PolyData(np.array(touch_pts, dtype=np.float32))

        self._refresh_plotter()

    def set_measured_points(self, points: List[Tuple[float, float, float]]):
        """Carrega e exibe os pontos tocados pelo probe em 3D com mapa de cores pela cota Z."""
        self._selected_index = None

        if not points or len(points) == 0:
            self._poly_measured = None
            self._poly_surface = None
            self._refresh_plotter()
            return

        arr = np.array(points, dtype=np.float32)
        poly = pv.PolyData(arr)
        poly["Offset Z (mm)"] = arr[:, 2]
        self._poly_measured = poly

        if len(arr) >= 4:
            try:
                self._poly_surface = poly.delaunay_2d()
            except Exception:
                self._poly_surface = None
        else:
            self._poly_surface = None

        self._refresh_plotter()

    # ------------------------------------------------------------------
    # Renderização e Visibilidade
    # ------------------------------------------------------------------

    def _refresh_plotter(self):
        """Atualiza todas as malhas renderizadas no PyVista."""
        self.plotter.clear()
        self.plotter.add_axes()

        # 1. Cortes G1 (Ciano vibrante)
        if self._poly_g1 is not None and self._chk_g1.isChecked():
            self.plotter.add_mesh(
                self._poly_g1,
                color="#00e5ff",
                line_width=2.5,
                name="g1_cuts",
                render_lines_as_tubes=False,
                reset_camera=False
            )

        # 2. Rápidos G0 (Vermelho com transparência)
        if self._poly_g0 is not None and self._chk_g0.isChecked():
            self.plotter.add_mesh(
                self._poly_g0,
                color="#ff5252",
                line_width=1.0,
                opacity=0.6,
                name="g0_rapids",
                reset_camera=False
            )

        # 3. Grade planejada de probe (Amarelo ouro)
        if hasattr(self, '_poly_probe_grid') and self._poly_probe_grid is not None and self._chk_grid.isChecked():
            self.plotter.add_mesh(
                self._poly_probe_grid,
                color="#f57f17",
                line_width=1.5,
                name="probe_grid_lines",
                reset_camera=False
            )
            if hasattr(self, '_poly_probe_pts') and self._poly_probe_pts is not None:
                self.plotter.add_mesh(
                    self._poly_probe_pts,
                    color="#ffd54f",
                    point_size=10,
                    render_points_as_spheres=True,
                    name="probe_grid_pts",
                    reset_camera=False
                )

        # 4. Superfície 3D interpolada do relevo (se houver pontos medidos)
        if self._poly_surface is not None and self._chk_measured.isChecked():
            self.plotter.add_mesh(
                self._poly_surface,
                scalars="Offset Z (mm)",
                cmap="turbo",
                opacity=0.45,
                show_edges=True,
                edge_color="#ffffff",
                name="surface_mesh",
                reset_camera=False
            )

        # 5. Pontos medidos reais de Probing (Esferas 3D coloridas)
        if self._poly_measured is not None and self._chk_measured.isChecked():
            self.plotter.add_mesh(
                self._poly_measured,
                scalars="Offset Z (mm)",
                cmap="turbo",
                point_size=16,
                render_points_as_spheres=True,
                name="measured_spheres",
                reset_camera=False,
                scalar_bar_args={
                    "title": "Offset Z (mm)",
                    "color": "#ffffff",
                    "label_font_size": 10,
                    "title_font_size": 11
                }
            )

        # 6. Bounding Box 3D da peça (apenas no modo plano)
        if self._chk_box.isChecked() and self._blocks and self._poly_cylinder is None:
            xmin, xmax, ymin, ymax, zmin, zmax = self._bbox
            box_mesh = pv.Box(bounds=(xmin, xmax, ymin, ymax, zmin, zmax))
            self.plotter.add_mesh(
                box_mesh,
                style="wireframe",
                color="#444444",
                line_width=1.0,
                name="bbox_wireframe",
                reset_camera=False
            )

        # 7. Tarugo Cilíndrico do 4º Eixo (Cilindro 3D Translúcido)
        if self._poly_cylinder is not None and self._chk_cylinder.isChecked():
            self.plotter.add_mesh(
                self._poly_cylinder,
                color="#455a64",
                opacity=0.35,
                show_edges=True,
                edge_color="#607d8b",
                name="rotary_cylinder_mesh",
                reset_camera=False
            )
            if self._poly_axis_line is not None:
                self.plotter.add_mesh(
                    self._poly_axis_line,
                    color="#ffb74d",
                    line_width=2.5,
                    name="rotary_center_axis",
                    reset_camera=False
                )

        # Reaplica a transformação do modo "peça se move" (o clear() acima
        # recria os atores e perde a matriz de usuário).
        self._apply_rotary_actor_matrix()

        # Restaura a ferramenta da simulação, se estava visível.
        if self._last_tool_tip is not None:
            self._place_tool(self._last_tool_tip, self._last_tool_dir, render=False)

        self.plotter.render()

    def _update_visibility(self):
        """Alterna a visibilidade dos atores sem precisar recriar a cena do zero."""
        actors = self.plotter.actors

        needs_full_refresh = False

        if "g1_cuts" in actors:
            actors["g1_cuts"].SetVisibility(self._chk_g1.isChecked())
        elif self._poly_g1 is not None and self._chk_g1.isChecked():
            needs_full_refresh = True

        if "g0_rapids" in actors:
            actors["g0_rapids"].SetVisibility(self._chk_g0.isChecked())
        elif self._poly_g0 is not None and self._chk_g0.isChecked():
            needs_full_refresh = True

        if "probe_grid_lines" in actors:
            actors["probe_grid_lines"].SetVisibility(self._chk_grid.isChecked())
        if "probe_grid_pts" in actors:
            actors["probe_grid_pts"].SetVisibility(self._chk_grid.isChecked())

        if "surface_mesh" in actors:
            actors["surface_mesh"].SetVisibility(self._chk_measured.isChecked())
        if "measured_spheres" in actors:
            actors["measured_spheres"].SetVisibility(self._chk_measured.isChecked())

        if "bbox_wireframe" in actors:
            actors["bbox_wireframe"].SetVisibility(self._chk_box.isChecked())
        elif self._chk_box.isChecked() and self._blocks and self._poly_cylinder is None:
            needs_full_refresh = True

        if "rotary_cylinder_mesh" in actors:
            actors["rotary_cylinder_mesh"].SetVisibility(self._chk_cylinder.isChecked())
        if "rotary_center_axis" in actors:
            actors["rotary_center_axis"].SetVisibility(self._chk_cylinder.isChecked())

        if needs_full_refresh:
            self._refresh_plotter()
        else:
            self.plotter.render()

    # ------------------------------------------------------------------
    # Simulação: ferramenta / peça em movimento
    # ------------------------------------------------------------------

    def get_rotary_config(self) -> Optional[dict]:
        """Parâmetros do 4º eixo atualmente exibidos (ou None no modo plano)."""
        if not self._rotary_active or not self._rotary_config:
            return None
        return dict(self._rotary_config)

    def set_sim_motion_mode(self, mode: str):
        """Define quem se move na simulação: 'tool' ou 'workpiece'."""
        if mode not in ("tool", "workpiece"):
            mode = "tool"
        previous = self._rotary_motion_mode
        self._rotary_motion_mode = mode

        # Ao entrar no modo "peça se move", centraliza a câmera no ponto
        # de contato fixo (topo do cilindro) para que a ferramenta pareça
        # realmente parada enquanto o tarugo gira/translada.
        if (mode == "workpiece" and previous != "workpiece"
                and self._rotary_active and self._rotary_config):
            self._focus_camera_on_contact()

    def _focus_camera_on_contact(self):
        """Mantém o ponto de contato fixo no centro da vista 3D."""
        try:
            radius = float(self._rotary_config.get("diameter_mm", 2.0)) / 2.0
        except (TypeError, ValueError):
            radius = 0.0

        cam = self.plotter.camera
        focal = cam.focal_point
        pos = cam.position
        new_focal = (0.0, 0.0, radius)
        cam.position = (
            new_focal[0] + (pos[0] - focal[0]),
            new_focal[1] + (pos[1] - focal[1]),
            new_focal[2] + (pos[2] - focal[2]),
        )
        cam.focal_point = new_focal
        self.plotter.render()

    @staticmethod
    def _to_vtk_matrix(matrix) -> vtk.vtkMatrix4x4:
        """Converte uma matriz 4x4 (listas/numpy) em vtkMatrix4x4."""
        vtk_mat = vtk.vtkMatrix4x4()
        for i in range(4):
            for j in range(4):
                vtk_mat.SetElement(i, j, float(matrix[i][j]))
        return vtk_mat

    def _apply_rotary_actor_matrix(self):
        """Aplica (ou remove) a transformação de corpo rígido aos atores do 4º eixo."""
        if not self._rotary_active:
            return
        for name in self._rotary_actor_names:
            actor = self.plotter.actors.get(name)
            if actor is not None:
                actor.SetUserMatrix(self._rotary_user_matrix)
                actor.Modified()

    def _place_tool(self, tip: Tuple[float, float, float],
                    direction: Tuple[float, float, float],
                    tool_radius: float = 2.0, tool_length: float = 12.0,
                    render: bool = True):
        """Posiciona o cone da fresa com a ponta em `tip`, apontando para `direction`."""
        dx, dy, dz = direction
        norm = math.sqrt(dx * dx + dy * dy + dz * dz)
        if norm < 1e-9:
            dx, dy, dz = 0.0, 0.0, -1.0
            norm = 1.0
        ux, uy, uz = dx / norm, dy / norm, dz / norm

        self._last_tool_tip = tuple(tip)
        self._last_tool_dir = (ux, uy, uz)

        # A ponta do cone fica em `tip`; o centro recua meio comprimento.
        cx = tip[0] - ux * tool_length / 2.0
        cy = tip[1] - uy * tool_length / 2.0
        cz = tip[2] - uz * tool_length / 2.0

        tool_cone = pv.Cone(
            center=(cx, cy, cz),
            direction=(ux, uy, uz),
            height=tool_length,
            radius=tool_radius,
            resolution=20
        )
        self.plotter.add_mesh(
            tool_cone,
            color="#ffeb3b",
            opacity=0.85,
            name="sim_tool_cutter",
            reset_camera=False
        )
        if render:
            self.plotter.render()

    def update_sim_position(self, point: Tuple[float, float, float],
                            rotary_state: Optional[dict] = None,
                            motion_mode: Optional[str] = None):
        """
        Atualiza a simulação com a posição 3D do contato da ferramenta.

        Args:
            point: (x, y, z) do contato — já enrolado no cilindro no modo
                   rotativo.
            rotary_state: dicionário opcional com ``machine`` = (x, y, A, z)
                   e ``config`` do 4º eixo.
            motion_mode: 'tool' (peça parada, ferramenta percorre o caminho)
                   ou 'workpiece' (ferramenta parada, peça gira/translada).
        """
        if motion_mode in ("tool", "workpiece"):
            self._rotary_motion_mode = motion_mode

        if not self._rotary_active or not rotary_state:
            # Modo plano normal: ferramenta desce em Z.
            self._rotary_user_matrix = None
            self._apply_rotary_actor_matrix()
            self._place_tool(point, (0.0, 0.0, -1.0))
            return

        cfg = rotary_state.get("config") or self._rotary_config or {}
        y_to_a = bool(cfg.get("y_to_a", True))
        machine = rotary_state.get("machine")
        if not machine:
            self._place_tool(point, (0.0, 0.0, -1.0))
            return
        mx, my, ma, mz = machine

        if self._rotary_motion_mode == "workpiece":
            # A peça e o percurso sofrem a transformação inversa; a
            # ferramenta permanece no topo do cilindro, acompanhando
            # apenas a profundidade Z.
            matrix = rotary_workpiece_matrix(mx, my, ma, y_to_a=y_to_a)
            self._rotary_user_matrix = self._to_vtk_matrix(matrix)
            self._apply_rotary_actor_matrix()

            if y_to_a:
                r_eff = math.hypot(point[1], point[2])
            else:
                r_eff = math.hypot(point[0], point[2])
            contact = (0.0, 0.0, max(0.01, r_eff))
            self._place_tool(contact, (0.0, 0.0, -1.0))
        else:
            # Peça parada: a ferramenta percorre o percurso enrolado e
            # aponta radialmente para o eixo do cilindro.
            self._rotary_user_matrix = None
            self._apply_rotary_actor_matrix()

            if y_to_a:
                inward = (0.0, -point[1], -point[2])
            else:
                inward = (-point[0], 0.0, -point[2])
            self._place_tool(point, inward)

    def update_tool_position(self, x: float, y: float, z: float,
                             tool_radius: float = 2.0, tool_length: float = 12.0):
        """Atualiza a posição da fresa 3D (compatibilidade com o modo plano)."""
        self._rotary_user_matrix = None
        self._apply_rotary_actor_matrix()
        self._place_tool((x, y, z), (0.0, 0.0, -1.0),
                         tool_radius=tool_radius,
                         tool_length=tool_length)

    def hide_tool(self):
        """Remove a ferramenta de corte da simulação da cena 3D."""
        self._last_tool_tip = None
        if "sim_tool_cutter" in self.plotter.actors:
            self.plotter.remove_actor("sim_tool_cutter", reset_camera=False)
            self.plotter.render()

    def export_mesh(self, filepath: str) -> bool:
        """Exporta os percursos e malhas 3D para STL, PLY, VTK ou OBJ."""
        meshes = []
        if self._poly_surface is not None:
            meshes.append(self._poly_surface)
        if self._poly_g1 is not None:
            tubes = self._poly_g1.tube(radius=0.4, n_sides=6)
            meshes.append(tubes)
        if self._poly_cylinder is not None:
            meshes.append(self._poly_cylinder)

        if not meshes:
            raise ValueError("Nenhum percurso ou malha carregada para exportação.")

        combined = meshes[0]
        for m in meshes[1:]:
            combined = combined.merge(m)

        combined.save(filepath)
        return True

    def clear(self):
        self._blocks = []
        self._poly_g1 = None
        self._poly_g0 = None
        self._poly_probe_grid = None
        self._poly_probe_pts = None
        self._poly_measured = None
        self._poly_surface = None
        self._poly_cylinder = None
        self._poly_axis_line = None
        self._rotary_active = False
        self._rotary_config = None
        self._rotary_data = None
        self._rotary_user_matrix = None
        self._last_tool_tip = None
        self._chk_cylinder.setVisible(False)
        self._selected_index = None
        self._dim_label.setText("Dimensões: X: 0.0mm | Y: 0.0mm | Z: 0.0mm")
        self.plotter.clear()
        self.plotter.add_axes()
        self.plotter.render()
