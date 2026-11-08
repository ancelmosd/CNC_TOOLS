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


class GCodeHighlighter(QSyntaxHighlighter):
    """Realçador de sintaxe para código G-Code CNC."""

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules = []

        # 1. Comentários (cinza itálico)
        comment_fmt = QTextCharFormat()
        comment_fmt.setForeground(QColor("#757575"))
        comment_fmt.setFontItalic(True)
        self._rules.append((QRegularExpression(r"\(.*?\)"), comment_fmt))
        self._rules.append((QRegularExpression(r";[^\n]*"), comment_fmt))

        # 2. Comandos G (Ciano)
        g_fmt = QTextCharFormat()
        g_fmt.setForeground(QColor("#00e5ff"))
        g_fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r"\b[Gg]\d+(\.\d+)?\b"), g_fmt))

        # 3. Comandos M (Laranja / Âmbar)
        m_fmt = QTextCharFormat()
        m_fmt.setForeground(QColor("#ffb74d"))
        m_fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r"\b[Mm]\d+(\.\d+)?\b"), m_fmt))

        # 4. Eixos de Movimento X, Y, Z, A, B, C (Verde)
        axis_fmt = QTextCharFormat()
        axis_fmt.setForeground(QColor("#69f0ae"))
        self._rules.append((QRegularExpression(r"[XYZABCxyzabc]\s*-?\d+\.?\d*"), axis_fmt))

        # 5. Offsets de Centro e Arcos I, J, K, R (Azul Claro)
        arc_fmt = QTextCharFormat()
        arc_fmt.setForeground(QColor("#4fc3f7"))
        self._rules.append((QRegularExpression(r"[IJKRijkr]\s*-?\d+\.?\d*"), arc_fmt))

        # 6. Avanço F e Rotação S (Magenta)
        feed_fmt = QTextCharFormat()
        feed_fmt.setForeground(QColor("#ea80fc"))
        feed_fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r"[FSfs]\s*\d+\.?\d*"), feed_fmt))

        # 7. Ferramentas T e Troca (Amarelo)
        tool_fmt = QTextCharFormat()
        tool_fmt.setForeground(QColor("#ffd54f"))
        tool_fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r"\b[Tt]\d+\b"), tool_fmt))

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

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Barra superior com ações e busca
        top_bar = QFrame()
        top_bar.setStyleSheet("background-color: #1e1e1e; border-radius: 4px; padding: 2px;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(6, 4, 6, 4)
        top_layout.setSpacing(8)

        # Botão Aplicar alterações ao modelo
        self._btn_apply = QPushButton("🔄 Aplicar Edições ao 3D")
        self._btn_apply.setStyleSheet("background-color: #00695c; font-weight: bold; padding: 6px 12px;")
        self._btn_apply.setToolTip("Re-interpreta as linhas editadas e atualiza o visualizador 3D")
        self._btn_apply.clicked.connect(self._apply_text_changes)
        top_layout.addWidget(self._btn_apply)

        # Botão Recarregar original
        self._btn_reload = QPushButton("↩️ Reverter")
        self._btn_reload.setStyleSheet("background-color: #37474f; padding: 6px 10px;")
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
        self._btn_find.setStyleSheet("background-color: #2a2a2a; padding: 5px 10px;")
        self._btn_find.clicked.connect(self._find_next)
        top_layout.addWidget(self._btn_find)

        top_layout.addStretch()

        self._lbl_cursor = QLabel("Linha: 1, Col: 1")
        self._lbl_cursor.setStyleSheet("color: #888888; font-size: 11px;")
        top_layout.addWidget(self._lbl_cursor)

        layout.addWidget(top_bar)

        # Editor de Texto com Syntax Highlighting
        self._editor = QPlainTextEdit()
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.Monospace)
        self._editor.setFont(font)
        self._editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #121212;
                color: #e0e0e0;
                border: 1px solid #2d2d2d;
                border-radius: 4px;
                selection-background-color: #264f78;
            }
        """)
        self._highlighter = GCodeHighlighter(self._editor.document())
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

