"""
tab_info.py — Aba de Estatísticas, Estimativa de Tempo e Simulação 3D de Percurso.
"""

from typing import Callable, Optional, List, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QScrollArea, QFrame, QSlider,
    QComboBox, QProgressBar
)
from PySide6.QtCore import Qt, QTimer

from core.statistics import analyze_gcode, format_duration


class InfoTab(QWidget):
    """Aba de Informações, Estatísticas e Simulação do G-Code."""

    def __init__(self, get_blocks_fn: Callable, preview_widget=None, parent=None):
        super().__init__(parent)
        self._get_blocks = get_blocks_fn
        self._preview = preview_widget

        # Estado da Simulação
        self._sim_points: List[Tuple[float, float, float, bool, float, int]] = []
        self._sim_rotary: List[Optional[Tuple[float, float, float, float]]] = []
        self._rotary_config: Optional[dict] = None
        self._motion_mode = "tool"   # "tool" | "workpiece"
        self._current_sim_idx = 0
        self._is_playing = False
        self._sim_timer = QTimer(self)
        self._sim_timer.timeout.connect(self._on_sim_step)

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

        # ---------------- 1. Painel de Simulação ----------------
        grp_sim = QGroupBox("🎮 Simulação e Animação do Percurso 3D")
        grp_sim_layout = QVBoxLayout(grp_sim)
        grp_sim_layout.setSpacing(8)

        # Coordenadas e Linha Atual
        h_info = QHBoxLayout()
        self._lbl_sim_pos = QLabel("Posição: X: 0.000 | Y: 0.000 | Z: 0.000 mm")
        self._lbl_sim_pos.setStyleSheet("color: #00e5ff; font-weight: bold; font-size: 12px;")
        h_info.addWidget(self._lbl_sim_pos)

        self._lbl_sim_line = QLabel("Linha: #0")
        self._lbl_sim_line.setStyleSheet("color: #ffd54f; font-weight: bold; font-size: 12px;")
        h_info.addWidget(self._lbl_sim_line, alignment=Qt.AlignRight)
        grp_sim_layout.addLayout(h_info)

        # Slider de Progresso
        self._sim_slider = QSlider(Qt.Horizontal)
        self._sim_slider.setRange(0, 1000)
        self._sim_slider.setValue(0)
        self._sim_slider.sliderMoved.connect(self._on_slider_moved)
        grp_sim_layout.addWidget(self._sim_slider)

        # Barra de Progresso visual
        self._prog_bar = QProgressBar()
        self._prog_bar.setRange(0, 1000)
        self._prog_bar.setValue(0)
        self._prog_bar.setTextVisible(False)
        self._prog_bar.setFixedHeight(6)
        grp_sim_layout.addWidget(self._prog_bar)

        # Controles Play / Pause / Reset / Velocidade
        h_ctrls = QHBoxLayout()

        self._btn_play = QPushButton("▶ Iniciar")
        self._btn_play.setStyleSheet("background-color: #2e7d32; font-weight: bold; font-size: 12px; padding: 6px 14px;")
        self._btn_play.clicked.connect(self._toggle_play)
        h_ctrls.addWidget(self._btn_play)

        self._btn_reset = QPushButton("⏹ Reiniciar")
        self._btn_reset.setStyleSheet("background-color: #37474f; font-weight: bold; padding: 6px 12px;")
        self._btn_reset.clicked.connect(self._reset_sim)
        h_ctrls.addWidget(self._btn_reset)

        h_ctrls.addSpacing(12)
        h_ctrls.addWidget(QLabel("Velocidade:"))

        self._cmb_speed = QComboBox()
        self._cmb_speed.addItems(["1x", "2x", "5x", "10x", "25x", "50x", "100x"])
        self._cmb_speed.setCurrentText("10x")
        self._cmb_speed.currentTextChanged.connect(self._update_timer_speed)
        h_ctrls.addWidget(self._cmb_speed)

        h_ctrls.addStretch()
        grp_sim_layout.addLayout(h_ctrls)

        # Modo de movimento (peça x ferramenta) — habilitado no 4º eixo
        h_motion = QHBoxLayout()
        h_motion.addWidget(QLabel("Movimento na Simulação:"))

        self._cmb_motion = QComboBox()
        self._cmb_motion.addItems([
            "🛠️ Ferramenta se move (peça fixa)",
            "🔄 Peça se move (ferramenta fixa)",
        ])
        self._cmb_motion.setToolTip(
            "Escolha o referencial da animação no 4º eixo.\n"
            "No modo plano (sem eixo A) esta opção fica desabilitada."
        )
        self._cmb_motion.currentIndexChanged.connect(self._on_motion_mode_changed)
        self._cmb_motion.setEnabled(False)
        h_motion.addWidget(self._cmb_motion)

        self._lbl_motion_badge = QLabel("(modo plano)")
        self._lbl_motion_badge.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        h_motion.addWidget(self._lbl_motion_badge)

        h_motion.addStretch()
        grp_sim_layout.addLayout(h_motion)

        layout.addWidget(grp_sim)

        # ---------------- 2. Estimativa de Tempo ----------------
        grp_time = QGroupBox("⏱️ Estimativa de Tempo de Usinagem")
        grid_time = QGridLayout(grp_time)
        grid_time.setSpacing(6)

        grid_time.addWidget(QLabel("Tempo Total Estimado:"), 0, 0)
        self._lbl_total_time = QLabel("--")
        self._lbl_total_time.setStyleSheet("color: #69f0ae; font-weight: bold; font-size: 13px;")
        grid_time.addWidget(self._lbl_total_time, 0, 1)

        grid_time.addWidget(QLabel("Tempo em Corte (G1/G2/G3):"), 1, 0)
        self._lbl_cut_time = QLabel("--")
        self._lbl_cut_time.setStyleSheet("color: #00e5ff; font-weight: bold;")
        grid_time.addWidget(self._lbl_cut_time, 1, 1)

        grid_time.addWidget(QLabel("Tempo em Rápidos (G0):"), 2, 0)
        self._lbl_rapid_time = QLabel("--")
        self._lbl_rapid_time.setStyleSheet("color: #ff5252;")
        grid_time.addWidget(self._lbl_rapid_time, 2, 1)

        layout.addWidget(grp_time)

        # ---------------- 3. Distâncias e Percursos ----------------
        grp_dist = QGroupBox("📏 Percurso e Distâncias")
        grid_dist = QGridLayout(grp_dist)
        grid_dist.setSpacing(6)

        grid_dist.addWidget(QLabel("Distância Total:"), 0, 0)
        self._lbl_total_dist = QLabel("--")
        self._lbl_total_dist.setStyleSheet("font-weight: bold; color: #ffffff;")
        grid_dist.addWidget(self._lbl_total_dist, 0, 1)

        grid_dist.addWidget(QLabel("Percurso de Corte:"), 1, 0)
        self._lbl_cut_dist = QLabel("--")
        self._lbl_cut_dist.setStyleSheet("color: #00e5ff;")
        grid_dist.addWidget(self._lbl_cut_dist, 1, 1)

        grid_dist.addWidget(QLabel("Percurso de Rápidos:"), 2, 0)
        self._lbl_rapid_dist = QLabel("--")
        self._lbl_rapid_dist.setStyleSheet("color: #ff5252;")
        grid_dist.addWidget(self._lbl_rapid_dist, 2, 1)

        layout.addWidget(grp_dist)

        # ---------------- 4. Dimensões Físicas (Bounding Box) ----------------
        grp_dim = QGroupBox("📐 Dimensões do Modelo (Envelope de Trabalho)")
        grid_dim = QGridLayout(grp_dim)
        grid_dim.setSpacing(6)

        self._lbl_bbox_x_title = QLabel("Eixo X:")
        grid_dim.addWidget(self._lbl_bbox_x_title, 0, 0)
        self._lbl_bbox_x = QLabel("--")
        grid_dim.addWidget(self._lbl_bbox_x, 0, 1)

        self._lbl_bbox_y_title = QLabel("Eixo Y:")
        grid_dim.addWidget(self._lbl_bbox_y_title, 1, 0)
        self._lbl_bbox_y = QLabel("--")
        grid_dim.addWidget(self._lbl_bbox_y, 1, 1)

        grid_dim.addWidget(QLabel("Eixo Z:"), 2, 0)
        self._lbl_bbox_z = QLabel("--")
        grid_dim.addWidget(self._lbl_bbox_z, 2, 1)

        layout.addWidget(grp_dim)

        # ---------------- 5. Parâmetros de Usinagem e Ferramentas ----------------
        grp_params = QGroupBox("⚙️ Parâmetros Operacionais")
        grid_params = QGridLayout(grp_params)
        grid_params.setSpacing(6)

        grid_params.addWidget(QLabel("Total de Linhas:"), 0, 0)
        self._lbl_total_lines = QLabel("--")
        grid_params.addWidget(self._lbl_total_lines, 0, 1)

        grid_params.addWidget(QLabel("Avanço (F) Mín / Máx:"), 1, 0)
        self._lbl_feed_range = QLabel("--")
        grid_params.addWidget(self._lbl_feed_range, 1, 1)

        grid_params.addWidget(QLabel("Rotação Spindle (S):"), 2, 0)
        self._lbl_spindle_range = QLabel("--")
        grid_params.addWidget(self._lbl_spindle_range, 2, 1)

        grid_params.addWidget(QLabel("Ferramentas Detectadas:"), 3, 0)
        self._lbl_tools = QLabel("--")
        self._lbl_tools.setStyleSheet("color: #ffd54f;")
        grid_params.addWidget(self._lbl_tools, 3, 1)

        layout.addWidget(grp_params)

        layout.addStretch()

        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def refresh_stats(self):
        """Atualiza todas as estatísticas e recarrega os pontos de simulação."""
        blocks = self._get_blocks()
        if not blocks:
            self._clear_stats()
            return

        # Em pré-visualização rotativa os blocos ainda estão planos, mas o
        # visualizador já conhece o cilindro. Usamos essa configuração para
        # simular o percurso enrolado antes mesmo de aplicar o wrapper.
        rotary = None
        has_meta = any(b.is_move and getattr(b, "rotary", None) for b in blocks)
        if not has_meta and self._preview is not None and hasattr(self._preview, "get_rotary_config"):
            rotary = self._preview.get_rotary_config()

        data = analyze_gcode(blocks, rotary=rotary)
        rotary_cfg = data.get("rotary_config")

        self._lbl_total_time.setText(format_duration(data["total_time_sec"]))
        self._lbl_cut_time.setText(format_duration(data["cut_time_sec"]))
        self._lbl_rapid_time.setText(format_duration(data["rapid_time_sec"]))

        self._lbl_total_dist.setText(f"{data['total_distance']:.2f} mm")
        self._lbl_cut_dist.setText(f"{data['cut_distance']:.2f} mm")
        self._lbl_rapid_dist.setText(f"{data['rapid_distance']:.2f} mm")

        bbox = data["bbox"]
        x_text = f"{bbox['xmin']:.2f} → {bbox['xmax']:.2f} mm (ΔX: {bbox['dx']:.2f} mm)"
        y_text = f"{bbox['ymin']:.2f} → {bbox['ymax']:.2f} mm (ΔY: {bbox['dy']:.2f} mm)"
        z_text = f"{bbox['zmin']:.2f} → {bbox['zmax']:.2f} mm (ΔZ: {bbox['dz']:.2f} mm)"

        if rotary_cfg:
            a_vals = [m[2] for m in data.get("sim_rotary", []) if m]
            if a_vals:
                a_text = (f"{min(a_vals):.2f}° → {max(a_vals):.2f}° "
                          f"(ΔA: {max(a_vals) - min(a_vals):.2f}°)")
            else:
                a_text = "--"

            if rotary_cfg.get("y_to_a", True):
                self._lbl_bbox_x_title.setText("Eixo X:")
                self._lbl_bbox_y_title.setText("Eixo A:")
                self._lbl_bbox_x.setText(x_text)
                self._lbl_bbox_y.setText(a_text)
            else:
                self._lbl_bbox_x_title.setText("Eixo A:")
                self._lbl_bbox_y_title.setText("Eixo Y:")
                self._lbl_bbox_x.setText(a_text)
                self._lbl_bbox_y.setText(y_text)
        else:
            self._lbl_bbox_x_title.setText("Eixo X:")
            self._lbl_bbox_y_title.setText("Eixo Y:")
            self._lbl_bbox_x.setText(x_text)
            self._lbl_bbox_y.setText(y_text)

        self._lbl_bbox_z.setText(z_text)

        self._lbl_total_lines.setText(f"{data['total_lines']} comandos")
        self._lbl_feed_range.setText(f"{data['min_feed']:.1f} → {data['max_feed']:.1f} mm/min (Méd: {data['avg_feed']:.1f})")

        if data["max_spindle"] > 0:
            self._lbl_spindle_range.setText(f"{data['min_spindle']:.0f} → {data['max_spindle']:.0f} RPM")
        else:
            self._lbl_spindle_range.setText("Não especificado")

        if data["tools"]:
            self._lbl_tools.setText(", ".join(data["tools"]))
        else:
            self._lbl_tools.setText("Padrão (sem troca M6)")

        # Preparar pontos da simulação
        self._sim_points = data["sim_points"]
        self._sim_rotary = data.get("sim_rotary", [])
        self._rotary_config = rotary_cfg
        self._current_sim_idx = 0
        self._update_motion_controls()
        self._update_sim_ui(0)

    def _update_motion_controls(self):
        """Habilita o seletor peça/ferramenta apenas quando há 4º eixo."""
        is_rotary = self._rotary_config is not None

        self._cmb_motion.blockSignals(True)
        if is_rotary:
            self._cmb_motion.setEnabled(True)
            self._cmb_motion.setCurrentIndex(1 if self._motion_mode == "workpiece" else 0)
            self._lbl_motion_badge.setText("(4º eixo detectado)")
            self._lbl_motion_badge.setStyleSheet("color: #80cbc4; font-size: 11px;")
        else:
            self._motion_mode = "tool"
            self._cmb_motion.setCurrentIndex(0)
            self._cmb_motion.setEnabled(False)
            self._lbl_motion_badge.setText("(modo plano)")
            self._lbl_motion_badge.setStyleSheet("color: #9e9e9e; font-size: 11px;")
        self._cmb_motion.blockSignals(False)

        if self._preview is not None and hasattr(self._preview, "set_sim_motion_mode"):
            self._preview.set_sim_motion_mode(self._motion_mode)

    def _on_motion_mode_changed(self, index: int):
        """Troca entre 'ferramenta se move' e 'peça se move'."""
        self._motion_mode = "workpiece" if index == 1 else "tool"
        if self._preview is not None and hasattr(self._preview, "set_sim_motion_mode"):
            self._preview.set_sim_motion_mode(self._motion_mode)

        # Reaplica a posição atual para atualizar a cena imediatamente.
        if self._sim_points:
            self._update_sim_ui(self._current_sim_idx)

    def _clear_stats(self):
        self._lbl_total_time.setText("--")
        self._lbl_cut_time.setText("--")
        self._lbl_rapid_time.setText("--")
        self._lbl_total_dist.setText("--")
        self._lbl_cut_dist.setText("--")
        self._lbl_rapid_dist.setText("--")
        self._lbl_bbox_x.setText("--")
        self._lbl_bbox_y.setText("--")
        self._lbl_bbox_z.setText("--")
        self._lbl_total_lines.setText("--")
        self._lbl_feed_range.setText("--")
        self._lbl_spindle_range.setText("--")
        self._lbl_tools.setText("--")
        self._lbl_bbox_x_title.setText("Eixo X:")
        self._lbl_bbox_y_title.setText("Eixo Y:")
        self._sim_points = []
        self._sim_rotary = []
        self._rotary_config = None
        self._current_sim_idx = 0
        self._update_motion_controls()
        if self._preview:
            self._preview.hide_tool()

    # ------------------------------------------------------------------
    # Controles de Simulação
    # ------------------------------------------------------------------

    def _toggle_play(self):
        if not self._sim_points:
            self.refresh_stats()
            if not self._sim_points:
                return

        if self._is_playing:
            self._pause_sim()
        else:
            self._start_sim()

    def _start_sim(self):
        self._is_playing = True
        self._btn_play.setText("⏸ Pausar")
        self._btn_play.setStyleSheet("background-color: #f57f17; font-weight: bold; font-size: 12px; padding: 6px 14px;")
        self._update_timer_speed()
        self._sim_timer.start()

    def _pause_sim(self):
        self._is_playing = False
        self._btn_play.setText("▶ Continuar")
        self._btn_play.setStyleSheet("background-color: #2e7d32; font-weight: bold; font-size: 12px; padding: 6px 14px;")
        self._sim_timer.stop()

    def _reset_sim(self):
        self._pause_sim()
        self._btn_play.setText("▶ Iniciar")
        self._current_sim_idx = 0
        self._update_sim_ui(0)
        if self._preview:
            self._preview.hide_tool()

    def _update_timer_speed(self):
        txt = self._cmb_speed.currentText().replace("x", "")
        try:
            mult = float(txt)
        except ValueError:
            mult = 1.0

        # Intervalo base de 30ms com passos pulados para velocidades altas
        self._sim_step_size = max(1, int(mult / 2.0))
        interval_ms = max(10, int(40.0 / (mult if mult < 5 else 5)))
        if self._is_playing:
            self._sim_timer.setInterval(interval_ms)

    def _on_sim_step(self):
        if not self._sim_points or self._current_sim_idx >= len(self._sim_points) - 1:
            self._pause_sim()
            self._btn_play.setText("▶ Reiniciar")
            return

        self._current_sim_idx += getattr(self, '_sim_step_size', 1)
        if self._current_sim_idx >= len(self._sim_points):
            self._current_sim_idx = len(self._sim_points) - 1

        self._update_sim_ui(self._current_sim_idx)

    def _on_slider_moved(self, val: int):
        if not self._sim_points:
            return
        idx = int((val / 1000.0) * (len(self._sim_points) - 1))
        self._current_sim_idx = idx
        self._update_sim_ui(idx)

    def _update_sim_ui(self, idx: int):
        if not self._sim_points:
            return

        pt = self._sim_points[idx]
        x, y, z, is_rapid, feed, line_no = pt

        machine = None
        if self._rotary_config is not None and idx < len(self._sim_rotary):
            machine = self._sim_rotary[idx]

        if machine is not None:
            mx, my, ma, mz = machine
            if self._rotary_config.get("y_to_a", True):
                pos_txt = f"Posição: X: {mx:.3f} | A: {ma:.3f}° | Z: {mz:.3f} mm"
            else:
                pos_txt = f"Posição: Y: {my:.3f} | A: {ma:.3f}° | Z: {mz:.3f} mm"
        else:
            pos_txt = f"Posição: X: {x:.3f} | Y: {y:.3f} | Z: {z:.3f} mm"

        self._lbl_sim_pos.setText(pos_txt)
        self._lbl_sim_line.setText(f"Linha: #{line_no} ({'G0 Rápido' if is_rapid else f'G1 F={feed:.0f}'})")

        # Atualizar slider e progresso
        ratio = idx / max(1, len(self._sim_points) - 1)
        val = int(ratio * 1000)
        self._sim_slider.blockSignals(True)
        self._sim_slider.setValue(val)
        self._sim_slider.blockSignals(False)
        self._prog_bar.setValue(val)

        # Atualizar a cena 3D (ferramenta e/ou peça)
        if self._preview:
            rotary_state = None
            if machine is not None:
                rotary_state = {
                    "machine": machine,
                    "config": self._rotary_config,
                }

            if hasattr(self._preview, "update_sim_position"):
                self._preview.update_sim_position(
                    (x, y, z),
                    rotary_state=rotary_state,
                    motion_mode=self._motion_mode,
                )
            else:  # compatibilidade
                self._preview.update_tool_position(x, y, z)

