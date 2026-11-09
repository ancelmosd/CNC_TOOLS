"""
theme.py — Paletas e folhas de estilo dos temas claro e escuro.

As cores são centralizadas aqui e aplicadas via QSS usando o atributo
dinâmico ``role`` dos widgets (ex.: ``QLabel[role="accent"]``), evitando
estilos inline espalhados pelas abas.
"""

from string import Template

from PySide6.QtWidgets import QWidget

DARK = "dark"
LIGHT = "light"

_PALETTES = {
    DARK: {
        "bg": "#121212",
        "bg_alt": "#181818",
        "panel": "#1e1e1e",
        "panel_hover": "#2a2a2a",
        "panel_pressed": "#1a1a1a",
        "border": "#2d2d2d",
        "border_strong": "#3d3d3d",
        "text": "#e0e0e0",
        "text_strong": "#ffffff",
        "muted": "#9e9e9e",
        "accent": "#00e5ff",
        "accent_hover": "#4fc3f7",
        "success": "#69f0ae",
        "danger": "#ff5252",
        "warning": "#ffd54f",
        "info": "#4fc3f7",
        "purple": "#ba68c8",
        "orange": "#ffb74d",
        "teal": "#80cbc4",
        "selection": "#264f78",
        "info_bg": "#1565c0",
        "success_bg": "#2e7d32",
        "danger_bg": "#b71c1c",
        "warning_bg": "#f57f17",
        "purple_bg": "#6a1b9a",
        "orange_bg": "#e65100",
        "teal_bg": "#00695c",
        "pink_bg": "#ad1457",
        "neutral_bg": "#37474f",
        "neutral_text": "#ffffff",
        "subtle_bg": "#2a2a2a",
        "subtle_text": "#ffffff",
        "success_dark_bg": "#1b5e20",
        "viewer_bg": "#141414",
        "viewer_axes": "#e0e0e0",
        "viewer_edge": "#ffffff",
        "viewer_bbox": "#444444",
        "viewer_text": "#ffffff",
        "syntax_comment": "#757575",
        "syntax_g": "#00e5ff",
        "syntax_m": "#ffb74d",
        "syntax_axis": "#69f0ae",
        "syntax_arc": "#4fc3f7",
        "syntax_feed": "#ea80fc",
        "syntax_tool": "#ffd54f",
    },
    LIGHT: {
        "bg": "#f5f6f8",
        "bg_alt": "#ffffff",
        "panel": "#eceff1",
        "panel_hover": "#e1e6ea",
        "panel_pressed": "#d9dfe4",
        "border": "#d5d9dd",
        "border_strong": "#b9c0c6",
        "text": "#202124",
        "text_strong": "#000000",
        "muted": "#5f6368",
        "accent": "#007c91",
        "accent_hover": "#00697a",
        "success": "#1b7a4b",
        "danger": "#c62828",
        "warning": "#8a6d00",
        "info": "#0277bd",
        "purple": "#7b1fa2",
        "orange": "#b35c00",
        "teal": "#00695c",
        "selection": "#bbdefb",
        "info_bg": "#1565c0",
        "success_bg": "#2e7d32",
        "danger_bg": "#c62828",
        "warning_bg": "#ef6c00",
        "purple_bg": "#6a1b9a",
        "orange_bg": "#e65100",
        "teal_bg": "#00695c",
        "pink_bg": "#ad1457",
        "neutral_bg": "#e1e6ea",
        "neutral_text": "#202124",
        "subtle_bg": "#e8ecef",
        "subtle_text": "#202124",
        "success_dark_bg": "#1b5e20",
        "viewer_bg": "#f7f8fa",
        "viewer_axes": "#37474f",
        "viewer_edge": "#546e7a",
        "viewer_bbox": "#b0bec5",
        "viewer_text": "#202124",
        "syntax_comment": "#6b7280",
        "syntax_g": "#007c91",
        "syntax_m": "#b35c00",
        "syntax_axis": "#1b7a4b",
        "syntax_arc": "#0277bd",
        "syntax_feed": "#8e24aa",
        "syntax_tool": "#8a6d00",
    },
}

_STYLE = Template("""
QMainWindow, QWidget {
    background-color: $bg;
    color: $text;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}

QToolTip {
    background-color: $panel;
    color: $text;
    border: 1px solid $border_strong;
    padding: 4px 6px;
}

QToolBar {
    background-color: $panel;
    border-bottom: 1px solid $border;
    padding: 4px;
    spacing: 6px;
}

QToolBar::separator {
    background-color: $border;
    width: 1px;
    margin: 4px 2px;
}

QLabel#brandLabel {
    color: $accent;
    font-size: 15px;
    font-weight: bold;
}

QLabel#fileLabel {
    color: $muted;
    font-style: italic;
    margin-left: 10px;
}

QLabel#fileLabel[role="accent"] {
    color: $accent;
    font-style: normal;
    font-weight: bold;
}

QLabel[role="accent"],
QCheckBox[role="accent"] {
    color: $accent;
}

QLabel[role="success"],
QCheckBox[role="success"] {
    color: $success;
}

QLabel[role="danger"],
QCheckBox[role="danger"] {
    color: $danger;
}

QLabel[role="warning"],
QCheckBox[role="warning"] {
    color: $warning;
}

QLabel[role="info"] {
    color: $info;
}

QLabel[role="purple"],
QCheckBox[role="purple"] {
    color: $purple;
}

QLabel[role="orange"],
QCheckBox[role="orange"] {
    color: $orange;
}

QLabel[role="teal"] {
    color: $teal;
}

QLabel[role="muted"],
QCheckBox[role="muted"] {
    color: $muted;
}

QLabel[role="strong"] {
    color: $text_strong;
    font-weight: bold;
}

QLabel[role="accent"],
QLabel[role="success"],
QLabel[role="strong"] {
    font-weight: bold;
}

QPushButton {
    background-color: $panel_hover;
    color: $text_strong;
    border: 1px solid $border_strong;
    border-radius: 4px;
    padding: 6px 12px;
}

QPushButton:hover {
    background-color: $panel_pressed;
    border-color: $border_strong;
}

QPushButton:pressed {
    background-color: $panel;
}

QPushButton[role="primary"] {
    background-color: $info_bg;
    color: #ffffff;
    border-color: $info_bg;
    font-weight: bold;
}

QPushButton[role="success"] {
    background-color: $success_bg;
    color: #ffffff;
    border-color: $success_bg;
    font-weight: bold;
}

QPushButton[role="danger"] {
    background-color: $danger_bg;
    color: #ffffff;
    border-color: $danger_bg;
    font-weight: bold;
}

QPushButton[role="warning"] {
    background-color: $warning_bg;
    color: #ffffff;
    border-color: $warning_bg;
    font-weight: bold;
}

QPushButton[role="purple"] {
    background-color: $purple_bg;
    color: #ffffff;
    border-color: $purple_bg;
    font-weight: bold;
}

QPushButton[role="orange"] {
    background-color: $orange_bg;
    color: #ffffff;
    border-color: $orange_bg;
    font-weight: bold;
}

QPushButton[role="teal"] {
    background-color: $teal_bg;
    color: #ffffff;
    border-color: $teal_bg;
    font-weight: bold;
}

QPushButton[role="pink"] {
    background-color: $pink_bg;
    color: #ffffff;
    border-color: $pink_bg;
    font-weight: bold;
}

QPushButton[role="success_dark"] {
    background-color: $success_dark_bg;
    color: #ffffff;
    border-color: $success_dark_bg;
}

QPushButton[role="neutral"] {
    background-color: $neutral_bg;
    color: $neutral_text;
    border-color: $border_strong;
}

QPushButton[role="subtle"] {
    background-color: $subtle_bg;
    color: $subtle_text;
    border-color: $border_strong;
}

QPushButton[role="primary"]:hover,
QPushButton[role="success"]:hover,
QPushButton[role="success_dark"]:hover,
QPushButton[role="danger"]:hover,
QPushButton[role="warning"]:hover,
QPushButton[role="purple"]:hover,
QPushButton[role="orange"]:hover,
QPushButton[role="teal"]:hover,
QPushButton[role="pink"]:hover {
    border-color: $text_strong;
}

QPushButton:disabled {
    background-color: $panel;
    color: $muted;
    border-color: $border;
}

QToolButton#themeToggle {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 3px 7px;
    font-size: 14px;
    color: $muted;
}

QToolButton#themeToggle:hover {
    background-color: $panel_hover;
    border-color: $border_strong;
}

QToolButton#themeToggle:pressed {
    background-color: $panel_pressed;
}

QLineEdit, QComboBox {
    background-color: $bg_alt;
    border: 1px solid $border_strong;
    border-radius: 4px;
    padding: 5px 8px;
    color: $text_strong;
    selection-background-color: $selection;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid $accent;
}

QLineEdit[role="success"] {
    color: $success;
    font-weight: bold;
}

QComboBox::drop-down {
    border: none;
    width: 18px;
}

QComboBox QAbstractItemView {
    background-color: $panel;
    color: $text;
    border: 1px solid $border_strong;
    selection-background-color: $info_bg;
    selection-color: #ffffff;
    outline: none;
}

QGroupBox {
    border: 1px solid $border;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: bold;
    color: $accent;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
}

QTabWidget::pane {
    border: 1px solid $border;
    background-color: $bg_alt;
    border-radius: 4px;
}

QTabBar::tab {
    background-color: $panel;
    color: $muted;
    padding: 8px 12px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: $panel_hover;
    color: $accent;
    font-weight: bold;
    border-bottom: 2px solid $accent;
}

QTabBar::tab:hover {
    background-color: $panel_hover;
    color: $text_strong;
}

QScrollBar:vertical {
    border: none;
    background-color: $bg_alt;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: $border_strong;
    border-radius: 4px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: $accent_hover;
}

QScrollBar:horizontal {
    border: none;
    background-color: $bg_alt;
    height: 8px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background-color: $border_strong;
    border-radius: 4px;
    min-width: 20px;
}

QScrollBar::handle:horizontal:hover {
    background-color: $accent_hover;
}

QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}

QStatusBar {
    background-color: $bg_alt;
    border-top: 1px solid $border;
    color: $muted;
}

QFrame[role="panel"] {
    background-color: $panel;
    border-radius: 4px;
}

QPlainTextEdit {
    background-color: $bg_alt;
    color: $text;
    border: 1px solid $border;
    border-radius: 4px;
    selection-background-color: $selection;
}

QTableWidget {
    background-color: $bg_alt;
    alternate-background-color: $panel;
    color: $text;
    border: 1px solid $border;
    border-radius: 4px;
    gridline-color: $border;
    selection-background-color: $info_bg;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: $panel;
    color: $muted;
    border: none;
    border-right: 1px solid $border;
    border-bottom: 1px solid $border;
    padding: 4px 6px;
    font-weight: bold;
}

QTableWidget::item:selected {
    background-color: $info_bg;
    color: #ffffff;
}

QCheckBox, QRadioButton {
    color: $text;
    spacing: 6px;
}

QSlider::groove:horizontal {
    height: 4px;
    background-color: $panel;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background-color: $accent;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background-color: $accent;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

QProgressBar {
    background-color: $panel;
    border: 1px solid $border;
    border-radius: 3px;
}

QProgressBar::chunk {
    background-color: $accent;
    border-radius: 2px;
}

QSplitter::handle {
    background-color: $border;
}

QMenu {
    background-color: $panel;
    color: $text;
    border: 1px solid $border_strong;
}

QMenu::item:selected {
    background-color: $info_bg;
    color: #ffffff;
}
""")


def get_palette(theme: str) -> dict:
    """Retorna a paleta do tema informado (escuro como fallback)."""
    return _PALETTES.get(theme, _PALETTES[DARK])


def build_stylesheet(theme: str) -> str:
    """Monta a folha de estilo QSS completa para o tema informado."""
    return _STYLE.substitute(get_palette(theme))


def set_role(widget: QWidget, role: str) -> None:
    """Define o papel visual do widget (usado pelos seletores do QSS)."""
    widget.setProperty("role", role)


def update_role(widget: QWidget, role: str) -> None:
    """Atualiza o papel visual e força a reaplicação do estilo."""
    widget.setProperty("role", role)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
