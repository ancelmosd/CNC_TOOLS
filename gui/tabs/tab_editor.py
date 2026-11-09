"""
tab_editor.py — Editor de Texto G-Code com Syntax Highlighting e Sincronização 3D.
"""

import re
from typing import Callable, List
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QPlainTextEdit, QMessageBox,
    QFrame
)
from PySide6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont,
    QTextDocument
)
from PySide6.QtCore import Qt, QRegularExpression

from core.gcode_parser import GCodeBlock, parse_line
from gui.theme import DARK, get_palette, set_role


class GCodeHighlighter(QSyntaxHighlighter):
    """Realçador de sintaxe para código G-Code CNC."""

    def __init__(self, document: QTextDocument, theme: str = DARK):
        super().__init__(document)
        self._theme = theme
        self._rules = []
        self._build_rules()

    def _build_rules(self):
        self._rules = []
        colors = get_palette(self._theme)

        # 1. Comentários (cinza itálico)
        comment_fmt = QTextCharFormat()
        comment_fmt.setForeground(QColor(colors["syntax_comment"]))
        comment_fmt.setFontItalic(True)
        self._rules.append((QRegularExpression(r"\(.*?\)"), comment_fmt))
        self._rules.append((QRegularExpression(r";[^\n]*"), comment_fmt))

        # 2. Comandos G (Ciano)
        g_fmt = QTextCharFormat()
        g_fmt.setForeground(QColor(colors["syntax_g"]))
        g_fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r"\b[Gg]\d+(\.\d+)?\b"), g_fmt))

        # 3. Comandos M (Laranja / Âmbar)
        m_fmt = QTextCharFormat()
        m_fmt.setForeground(QColor(colors["syntax_m"]))
        m_fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r"\b[Mm]\d+(\.\d+)?\b"), m_fmt))

        # 4. Eixos de Movimento X, Y, Z, A, B, C (Verde)
        axis_fmt = QTextCharFormat()
        axis_fmt.setForeground(QColor(colors["syntax_axis"]))
        self._rules.append((QRegularExpression(r"[XYZABCxyzabc]\s*-?\d+\.?\d*"), axis_fmt))

        # 5. Offsets de Centro e Arcos I, J, K, R (Azul Claro)
        arc_fmt = QTextCharFormat()
        arc_fmt.setForeground(QColor(colors["syntax_arc"]))
        self._rules.append((QRegularExpression(r"[IJKRijkr]\s*-?\d+\.?\d*"), arc_fmt))

        # 6. Avanço F e Rotação S (Magenta)
        feed_fmt = QTextCharFormat()
        feed_fmt.setForeground(QColor(colors["syntax_feed"]))
        feed_fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r"[FSfs]\s*\d+\.?\d*"), feed_fmt))

        # 7. Ferramentas T e Troca (Amarelo)
        tool_fmt = QTextCharFormat()
        tool_fmt.setForeground(QColor(colors["syntax_tool"]))
        tool_fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r"\b[Tt]\d+\b"), tool_fmt))

    def apply_theme(self, theme: str):
        """Reconstrói as regras de realce para o tema informado."""
        self._theme = theme
        self._build_rules()
        self.rehighlight()

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class EditorTab(QWidget):
    """Aba de Edição Direta do G-Code com coloração de sintaxe e atualização no 3D."""

    def __init__(self, get_blocks_fn: Callable, set_blocks_fn: Callable, parent=None):
        super().__init__(parent)
        self._get_blocks = get_blocks_fn
        self._set_blocks = set_blocks_fn
        self._is_syncing = False
        self._theme = DARK

        self._setup_ui()

    def apply_theme(self, theme: str):
        """Atualiza as cores do realce de sintaxe para o tema informado."""
        self._theme = theme
        if hasattr(self, "_highlighter"):
            self._highlighter.apply_theme(theme)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Barra superior com ações e busca
        top_bar = QFrame()
        set_role(top_bar, "panel")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(6, 4, 6, 4)
        top_layout.setSpacing(8)

        # Botão Aplicar alterações ao modelo
        self._btn_apply = QPushButton("🔄 Aplicar Edições ao 3D")
        set_role(self._btn_apply, "teal")
        self._btn_apply.setToolTip("Re-interpreta as linhas editadas e atualiza o visualizador 3D")
        self._btn_apply.clicked.connect(self._apply_text_changes)
        top_layout.addWidget(self._btn_apply)

        # Botão Recarregar original
        self._btn_reload = QPushButton("↩️ Reverter")
        set_role(self._btn_reload, "neutral")
        self._btn_reload.setToolTip("Descarta alterações não salvas e recarrega os blocos atuais")
        self._btn_reload.clicked.connect(self._reload_from_blocks)
        top_layout.addWidget(self._btn_reload)

        top_layout.addSpacing(12)

        # Campo de busca
        top_layout.addWidget(QLabel("🔍 Localizar:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Buscar texto...")
        self._search_edit.setMaximumWidth(180)
        self._search_edit.returnPressed.connect(self._find_next)
        top_layout.addWidget(self._search_edit)

        self._btn_find = QPushButton("Próximo")
        set_role(self._btn_find, "subtle")
        self._btn_find.clicked.connect(self._find_next)
        top_layout.addWidget(self._btn_find)

        top_layout.addStretch()

        self._lbl_cursor = QLabel("Linha: 1, Col: 1")
        set_role(self._lbl_cursor, "muted")
        self._lbl_cursor.setStyleSheet("font-size: 11px;")
        top_layout.addWidget(self._lbl_cursor)

        layout.addWidget(top_bar)

        # Editor de Texto com Syntax Highlighting
        self._editor = QPlainTextEdit()
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.Monospace)
        self._editor.setFont(font)
        self._highlighter = GCodeHighlighter(self._editor.document(), self._theme)
        self._editor.cursorPositionChanged.connect(self._on_cursor_changed)
        layout.addWidget(self._editor)

    def update_from_blocks(self, blocks: List[GCodeBlock]):
        """Atualiza o conteúdo do editor a partir dos blocos atuais."""
        if self._is_syncing:
            return

        self._is_syncing = True
        lines = [b.to_gcode() for b in blocks]
        text = "\n".join(lines)
        self._editor.setPlainText(text)
        self._is_syncing = False

    def _reload_from_blocks(self):
        blocks = self._get_blocks()
        self.update_from_blocks(blocks)

    def _apply_text_changes(self):
        text = self._editor.toPlainText()
        raw_lines = text.splitlines()

        if not raw_lines:
            QMessageBox.warning(self, "Aviso", "O editor está vazio.")
            return

        try:
            new_blocks = []
            for i, line in enumerate(raw_lines, start=1):
                b = parse_line(line, line_number=i)
                new_blocks.append(b)

            self._set_blocks(new_blocks, "Modificações manuais aplicadas via Editor de Texto")
            QMessageBox.information(self, "Sucesso",
                f"{len(new_blocks)} linhas processadas e atualizadas no visualizador 3D!")
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Parsear G-Code", str(e))

    def _find_next(self):
        query = self._search_edit.text()
        if not query:
            return
        found = self._editor.find(query)
        if not found:
            # Voltar ao início e buscar novamente
            cursor = self._editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)
            self._editor.find(query)

    def _on_cursor_changed(self):
        cursor = self._editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        self._lbl_cursor.setText(f"Linha: {line}, Col: {col}")

