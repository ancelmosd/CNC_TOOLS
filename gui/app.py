"""
app.py — Janela principal do GCode Tools em PySide6 + PyVista / VTK.

Interface Desktop profissional com aceleração 3D por GPU (OpenGL).
"""

import os
from typing import List, Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTabWidget, QToolBar, QLabel, QFileDialog,
    QMessageBox, QSplitter, QStatusBar, QPushButton
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from core.gcode_parser import GCodeBlock, parse_file, write_file
from gui.widgets.pyvista_viewer import PyVistaGCodeViewer
from gui.tabs.tab_surface import SurfaceTab
from gui.tabs.tab_rotary import RotaryTab
from gui.tabs.tab_transform import TransformTab
from gui.tabs.tab_splitter import SplitterTab
from gui.tabs.tab_arcs import ArcsTab
from gui.tabs.tab_info import InfoTab
from gui.tabs.tab_editor import EditorTab

APP_NAME = "GCode Tools"
APP_VERSION = "2.0.0"

# Estilo QSS Dark Moderno
DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #121212;
    color: #e0e0e0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}

QToolBar {
    background-color: #1e1e1e;
    border-bottom: 1px solid #2d2d2d;
    padding: 4px;
    spacing: 6px;
}

QPushButton {
    background-color: #2a2a2a;
    color: #ffffff;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 6px 12px;
}

QPushButton:hover {
    background-color: #383838;
    border-color: #555555;
}

QPushButton:pressed {
    background-color: #1a1a1a;
}

QLineEdit, QComboBox {
    background-color: #1e1e1e;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    padding: 5px 8px;
    color: #ffffff;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #00e5ff;
}

QGroupBox {
    border: 1px solid #2d2d2d;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: bold;
    color: #00e5ff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
}

QTabWidget::pane {
    border: 1px solid #2d2d2d;
    background-color: #181818;
    border-radius: 4px;
}

QTabBar::tab {
    background-color: #1e1e1e;
    color: #aaaaaa;
    padding: 8px 12px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #282828;
    color: #00e5ff;
    font-weight: bold;
    border-bottom: 2px solid #00e5ff;
}

QTabBar::tab:hover {
    background-color: #242424;
    color: #ffffff;
}

QScrollBar:vertical {
    border: none;
    background-color: #181818;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #383838;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #4fc3f7;
}

QStatusBar {
    background-color: #181818;
    border-top: 1px solid #2d2d2d;
    color: #888888;
}
"""


class MainWindow(QMainWindow):
    """Janela Principal da Aplicação."""

    def __init__(self):
        super().__init__()

        self._blocks: List[GCodeBlock] = []
        self._source_path: Optional[str] = None
        self._history: List[List[GCodeBlock]] = []
        self._settings = QSettings("GCodeToolsTeam", "GCodeTools")

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — PyVista / VTK GPU 3D")
        self.resize(1400, 880)
        self.setMinimumSize(960, 640)
        self.setStyleSheet(DARK_STYLE)

        # Habilitar arrastar e soltar arquivos (Drag & Drop)
        self.setAcceptDrops(True)

        self._setup_ui()
        self._restore_settings()

    def _setup_ui(self):
        # ---------------- Barra de Ferramentas Superior ----------------
        toolbar = QToolBar("Principal")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Logotipo / Título
        lbl_brand = QLabel(f"  ⚙️ {APP_NAME} ")
        lbl_brand.setStyleSheet("font-size: 15px; font-weight: bold; color: #00e5ff;")
        toolbar.addWidget(lbl_brand)

        toolbar.addSeparator()

        # Botão Abrir
        btn_open = QPushButton("📂 Abrir G-Code")
        btn_open.setStyleSheet("background-color: #1565c0; font-weight: bold;")
        btn_open.clicked.connect(self._open_file)
        toolbar.addWidget(btn_open)

        # Botão Salvar
        btn_save = QPushButton("💾 Salvar")
        btn_save.setStyleSheet("background-color: #2e7d32; font-weight: bold;")
        btn_save.clicked.connect(self._save_file)
        toolbar.addWidget(btn_save)

        # Botão Salvar Como
        btn_save_as = QPushButton("💾 Salvar Como...")
        btn_save_as.setStyleSheet("background-color: #1b5e20;")
        btn_save_as.clicked.connect(self._save_as)
        toolbar.addWidget(btn_save_as)

        # Botão Exportar 3D
        btn_export_3d = QPushButton("📤 Exportar 3D...")
        btn_export_3d.setStyleSheet("background-color: #4a148c; font-weight: bold;")
        btn_export_3d.setToolTip("Exportar malha e percursos 3D em STL, PLY, VTK ou OBJ")
        btn_export_3d.clicked.connect(self._export_3d)
        toolbar.addWidget(btn_export_3d)

        # Botão Desfazer
        btn_undo = QPushButton("↩️ Desfazer")
        btn_undo.setStyleSheet("background-color: #37474f;")
        btn_undo.clicked.connect(self._undo)
        toolbar.addWidget(btn_undo)

        toolbar.addSeparator()

        # Rótulo do Arquivo Atual
        self._lbl_file = QLabel("Nenhum arquivo carregado (arraste um arquivo .gcode aqui)")
        self._lbl_file.setStyleSheet("color: #aaaaaa; font-style: italic; margin-left: 10px;")
        toolbar.addWidget(self._lbl_file)

        # ---------------- Área Central (Splitter: Visualizador 3D + Abas) ----------------
        central_widget = QWidget()
        central_layout = QHBoxLayout(central_widget)
        central_layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Horizontal)

        # Coluna Esquerda: Visualizador 3D PyVista
        self._viewer = PyVistaGCodeViewer(self)
        splitter.addWidget(self._viewer)

        # Coluna Direita: Abas de Operações
        tabs_container = QWidget()
        tabs_layout = QVBoxLayout(tabs_container)
        tabs_layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # 1. Aba de Estatísticas e Simulação 3D
        self._info_tab = InfoTab(
            get_blocks_fn=self._get_blocks,
            preview_widget=self._viewer,
            parent=self
        )
        self._tabs.addTab(self._info_tab, "📊 Estatísticas & Simulação")

        # 2. Aba de Superfície (Auto-leveling)
        self._surface_tab = SurfaceTab(
            get_blocks_fn=self._get_blocks,
            set_blocks_fn=self._set_blocks,
            preview_widget=self._viewer,
            parent=self
        )
        self._tabs.addTab(self._surface_tab, "🗺️ Superfície")

        # 3. Aba de 4º Eixo
        self._rotary_tab = RotaryTab(
            get_blocks_fn=self._get_blocks,
            set_blocks_fn=self._set_blocks,
            preview_widget=self._viewer,
            parent=self
        )
        self._tabs.addTab(self._rotary_tab, "🔄 4º Eixo")

        # 4. Aba de Transformações
        self._transform_tab = TransformTab(
            get_blocks_fn=self._get_blocks,
            set_blocks_fn=self._set_blocks,
            parent=self
        )
        self._tabs.addTab(self._transform_tab, "↔️ Transformar")

        # 5. Aba de Divisão
        self._splitter_tab = SplitterTab(
            get_blocks_fn=self._get_blocks,
            parent=self
        )
        self._tabs.addTab(self._splitter_tab, "✂️ Dividir")

        # 6. Aba de Arcos
        self._arcs_tab = ArcsTab(
            get_blocks_fn=self._get_blocks,
            set_blocks_fn=self._set_blocks,
            parent=self
        )
        self._tabs.addTab(self._arcs_tab, "〰️ Arcos")

        # 7. Aba de Editor de Texto G-Code
        self._editor_tab = EditorTab(
            get_blocks_fn=self._get_blocks,
            set_blocks_fn=self._set_blocks,
            parent=self
        )
        self._tabs.addTab(self._editor_tab, "📝 Editor G-Code")

        tabs_layout.addWidget(self._tabs)
        splitter.addWidget(tabs_container)

        # Proporção inicial (62% visualizador 3D, 38% abas)
        splitter.setStretchFactor(0, 62)
        splitter.setStretchFactor(1, 38)

        central_layout.addWidget(splitter)
        self.setCentralWidget(central_widget)

        # ---------------- Barra de Status ----------------
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._status_msg = QLabel("Pronto. Abra ou arraste um arquivo G-Code para começar.")
        self._status_msg.setStyleSheet("color: #b0bec5;")
        self._status_bar.addWidget(self._status_msg, 1)

        self._lines_label = QLabel("")
        self._lines_label.setStyleSheet("color: #888888; font-weight: bold; margin-right: 12px;")
        self._status_bar.addPermanentWidget(self._lines_label)

    # ------------------------------------------------------------------
    # Drag and Drop (Arrastar e Soltar)
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(url.toLocalFile().lower().endswith(('.gcode', '.nc', '.tap', '.ngc', '.cnc', '.txt')) for url in urls):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return

        filepath = urls[0].toLocalFile()
        if os.path.isfile(filepath):
            self._load_gcode_from_path(filepath)
            event.acceptProposedAction()

    # ------------------------------------------------------------------
    # Estado Global e Undo
    # ------------------------------------------------------------------

    def _get_blocks(self) -> List[GCodeBlock]:
        return self._blocks

    def _set_blocks(self, blocks: List[GCodeBlock], operation: str = ""):
        """Atualiza a lista de blocos, registra no histórico de desfazer e sincroniza todos os componentes."""
        if self._blocks:
            self._history.append(self._blocks)
            if len(self._history) > 20:
                self._history.pop(0)

        self._blocks = blocks
        self._update_viewer()

        # Sincronizar abas dependentes
        self._info_tab.refresh_stats()
        self._editor_tab.update_from_blocks(self._blocks)

        if operation:
            self._status_msg.setText(f"✅ {operation}")

    def _undo(self):
        if not self._history:
            self._status_msg.setText("Nenhuma operação anterior para desfazer.")
            return

        self._blocks = self._history.pop()
        self._update_viewer()
        self._info_tab.refresh_stats()
        self._editor_tab.update_from_blocks(self._blocks)
        self._status_msg.setText("↩️ Operação desfeita com sucesso.")

    def _update_viewer(self):
        """Atualiza o visualizador PyVista e os limites da aba de superfície."""
        if self._blocks:
            self._viewer.load_blocks(self._blocks)
            self._lines_label.setText(f"{len(self._blocks)} linhas")
            self._surface_tab.update_bounds_from_gcode(self._blocks)
        else:
            self._viewer.clear()
            self._lines_label.setText("")

    def _on_tab_changed(self, index: int):
        """Ao alternar abas, atualiza dados das abas sob demanda."""
        if index == 0:  # Aba de Estatísticas
            self._info_tab.refresh_stats()
        elif index == 6:  # Aba de Editor de Texto
            self._editor_tab.update_from_blocks(self._blocks)

    # ------------------------------------------------------------------
    # Operações de Arquivo e Exportação
    # ------------------------------------------------------------------

    def _get_last_dir(self) -> str:
        return self._settings.value("last_dir", "")

    def _set_last_dir(self, path: str):
        if path:
            self._settings.setValue("last_dir", os.path.dirname(os.path.abspath(path)))

    def _open_file(self):
        initial_dir = self._get_last_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir Arquivo G-Code",
            initial_dir,
            "Arquivos G-Code (*.gcode *.nc *.tap *.ngc *.cnc *.txt);;Todos os Arquivos (*.*)"
        )
        if not path:
            return

        self._load_gcode_from_path(path)

    def _load_gcode_from_path(self, path: str):
        try:
            blocks = parse_file(path)
            self._source_path = path
            self._set_last_dir(path)
            self._blocks = blocks
            self._history.clear()
            self._update_viewer()

            fname = os.path.basename(path)
            self._lbl_file.setText(f"📄 {fname}")
            self._lbl_file.setStyleSheet("color: #00e5ff; font-weight: bold;")

            # Sincronizar abas
            self._info_tab.refresh_stats()
            self._editor_tab.update_from_blocks(self._blocks)

            n_moves = sum(1 for b in blocks if b.is_move)
            self._status_msg.setText(f"Arquivo carregado: {fname} — {len(blocks)} linhas, {n_moves} movimentos de usinagem.")
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Abrir Arquivo", str(e))

    def _save_file(self):
        if not self._blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado para salvar.")
            return

        if self._source_path:
            try:
                write_file(self._blocks, self._source_path)
                self._status_msg.setText(f"💾 Arquivo salvo com sucesso: {os.path.basename(self._source_path)}")
            except Exception as e:
                QMessageBox.critical(self, "Erro ao Salvar", str(e))
        else:
            self._save_as()

    def _save_as(self):
        if not self._blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado.")
            return

        initial_name = os.path.join(self._get_last_dir(), "modificado.gcode") if self._get_last_dir() else "modificado.gcode"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar G-Code Como",
            initial_name,
            "Arquivos G-Code (*.gcode *.nc *.tap);;Todos os Arquivos (*.*)"
        )
        if not path:
            return

        try:
            write_file(self._blocks, path)
            self._source_path = path
            self._set_last_dir(path)
            fname = os.path.basename(path)
            self._lbl_file.setText(f"📄 {fname}")
            self._status_msg.setText(f"💾 Arquivo salvo como: {fname}")
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Salvar", str(e))

    def _export_3d(self):
        """Exporta os percursos e relevos 3D em arquivos de malha."""
        if not self._blocks:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo G-Code carregado para exportação 3D.")
            return

        initial_name = os.path.join(self._get_last_dir(), "modelo_3d.stl") if self._get_last_dir() else "modelo_3d.stl"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar Malha 3D",
            initial_name,
            "Stereolithography (*.stl);;Polygon File Format (*.ply);;VTK PolyData (*.vtk);;Wavefront OBJ (*.obj)"
        )
        if not path:
            return

        try:
            self._viewer.export_mesh(path)
            self._set_last_dir(path)
            QMessageBox.information(self, "Exportação 3D Concluída",
                f"Malha 3D exportada com sucesso em:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Erro na Exportação 3D", str(e))

    # ------------------------------------------------------------------
    # Persistência de Preferências
    # ------------------------------------------------------------------

    def _restore_settings(self):
        geometry = self._settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event):
        self._settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)
