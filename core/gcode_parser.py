"""
gcode_parser.py — Parser e writer de G-Code para o GCode Tools.

Responsabilidades:
- Ler arquivos .gcode / .nc / .tap linha por linha
- Extrair comandos, coordenadas e parâmetros de cada linha
- Manter linhas não-reconhecidas intactas (comentários, M-codes especiais, etc.)
- Reescrever G-Code a partir de blocos modificados SEM perder palavras que o
  parser não interpreta (T, múltiplos G, M, parâmetros de máquina, etc.)
"""

import re
import math
from dataclasses import dataclass, field
from typing import Optional, List, Tuple


# ---------------------------------------------------------------------------
# Estrutura de dados para uma linha de G-Code
# ---------------------------------------------------------------------------

# Letra → atributo do dataclass
_FIELD_ATTR_BY_LETTER = {
    'N': 'n',
    'X': 'x', 'Y': 'y', 'Z': 'z',
    'I': 'i', 'J': 'j', 'K': 'k',
    'R': 'r', 'A': 'a', 'F': 'f', 'S': 's',
}

# Ordem usada ao acrescentar coordenadas que não existiam na linha original
# (ex.: eixo A criado pelo wrap rotativo, ou Z injetado pelo auto-leveling).
_FIELD_ORDER = ['X', 'Y', 'Z', 'I', 'J', 'K', 'R', 'A', 'F', 'S']


def _format_number(value) -> str:
    """Formata um número de G-Code sem lixo de ponto flutuante."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    text = f"{float(value):.4f}".rstrip('0').rstrip('.')
    if text in ('', '-0'):
        return '0'
    return text


@dataclass
class GCodeBlock:
    """Representa uma única linha (bloco) de G-Code."""
    raw: str                        # Linha original sem alterações
    line_number: int = 0            # Índice da linha no arquivo (0-based)

    # Comando principal (ex: 'G0', 'G1', 'G2', 'G3', 'M6', etc.)
    command: Optional[str] = None

    # Coordenadas extraídas
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    i: Optional[float] = None       # Centro arco X (relativo)
    j: Optional[float] = None       # Centro arco Y (relativo)
    k: Optional[float] = None       # Centro arco Z (relativo)
    r: Optional[float] = None       # Raio do arco
    a: Optional[float] = None       # Eixo rotativo A

    # Parâmetros de feed/speed
    f: Optional[float] = None       # Feed rate
    s: Optional[float] = None       # Spindle speed

    # Número de linha N (opcional no G-Code)
    n: Optional[int] = None

    # Comentário (entre parênteses ou após ;)
    comment: str = ""

    # True se a linha é só comentário ou linha em branco
    is_comment_only: bool = False

    # True se é movimento (G0, G1, G2, G3)
    is_move: bool = False

    # True se é rapid (G0)
    is_rapid: bool = False

    # Metadados do wrapper rotativo (diâmetro, mapeamento, offset...).
    # Não é serializado no G-Code; serve para a simulação 3D reconstruir o
    # cilindro e o percurso enrolado depois do wrap.
    rotary: Optional[dict] = field(default=None, repr=False)

    # Template da linha original: [(letra, token_original, valor), ...]
    words: List[Tuple[str, str, float]] = field(default_factory=list)
    # Índice em `words` da palavra G/M usada como `command`
    command_word_index: Optional[int] = None
    # Snapshot dos campos no momento do parse (para saber se a linha mudou)
    _original_values: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Reconstrução da linha
    # ------------------------------------------------------------------

    def _is_modified(self) -> bool:
        """True se algum campo interpretado foi alterado depois do parse."""
        if not self._original_values:
            return True
        if self.command != self._original_values.get('command'):
            return True
        for attr in _FIELD_ATTR_BY_LETTER.values():
            if getattr(self, attr) != self._original_values.get(attr):
                return True
        return False

    def _build_from_fields(self) -> str:
        """Reconstrói uma linha criada programaticamente (sem template)."""
        parts = []
        if self.n is not None:
            parts.append(f"N{self.n}")
        if self.command:
            parts.append(self.command)
        for letter in _FIELD_ORDER:
            attr = _FIELD_ATTR_BY_LETTER[letter]
            val = getattr(self, attr)
            if val is not None:
                parts.append(f"{letter}{_format_number(val)}")

        line = " ".join(parts)
        if self.comment:
            line = f"{line} ({self.comment})" if line else f"({self.comment})"
        return line

    def to_gcode(self) -> str:
        """
        Reconstrói a linha de G-Code a partir dos campos modificados.

        Linhas não modificadas são devolvidas EXATAMENTE como no arquivo
        original. Linhas modificadas são reconstruídas preservando todas as
        palavras originais (inclusive T, M e múltiplos comandos G).
        """
        if self.is_comment_only:
            return self.raw

        # Blocos gerados programaticamente (ex.: segmentos de arco) não têm
        # template: monta a partir dos campos.
        if not self.words:
            return self._build_from_fields()

        # Nada mudou → preserva a linha original byte a byte (menos EOL).
        if not self._is_modified():
            return self.raw

        parts: List[str] = []
        seen_letters = set()

        for idx, (letter, token, _value) in enumerate(self.words):
            upper = letter.upper()

            if idx == self.command_word_index and self.command:
                parts.append(self.command)
                seen_letters.add(upper)
                continue

            attr = _FIELD_ATTR_BY_LETTER.get(upper)
            if attr is None:
                # Palavra não interpretada (T, M secundário, G extra, etc.)
                parts.append(token)
                continue

            seen_letters.add(upper)
            val = getattr(self, attr)
            if val is None:
                # Campo removido (ex.: Y no wrap rotativo)
                continue

            original = self._original_values.get(attr)
            if original is not None and val == original:
                # Valor inalterado: mantém o token original (X10.0, X10, ...)
                parts.append(token)
            else:
                parts.append(f"{upper}{_format_number(val)}")

        # Campos novos que não existiam no template (ex.: A, Z injetado)
        for letter in _FIELD_ORDER:
            if letter in seen_letters:
                continue
            attr = _FIELD_ATTR_BY_LETTER[letter]
            val = getattr(self, attr)
            if val is not None:
                parts.append(f"{letter}{_format_number(val)}")

        line = " ".join(parts)

        if self.comment:
            line = f"{line} ({self.comment})" if line else f"({self.comment})"

        return line


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Regex para extrair palavras G-Code (letra + número)
_WORD_RE = re.compile(r'([A-Za-z])\s*(-?\d+\.?\d*)', re.IGNORECASE)
# Regex para comentários entre parênteses
_COMMENT_PAREN_RE = re.compile(r'\(([^)]*)\)')
# Regex para comentários estilo ponto-e-vírgula
_COMMENT_SEMI_RE = re.compile(r';(.*)')


def parse_line(raw: str, line_number: int = 0) -> GCodeBlock:
    """Parseia uma única linha de G-Code e retorna um GCodeBlock."""
    block = GCodeBlock(raw=raw, line_number=line_number)

    line = raw.strip()

    # Extrair comentários
    comment_parts = []
    paren_matches = _COMMENT_PAREN_RE.findall(line)
    comment_parts.extend(paren_matches)
    line = _COMMENT_PAREN_RE.sub('', line)

    semi_match = _COMMENT_SEMI_RE.search(line)
    if semi_match:
        comment_parts.append(semi_match.group(1).strip())
        line = line[:semi_match.start()]

    block.comment = " | ".join(c.strip() for c in comment_parts if c.strip())

    line = line.strip()

    if not line:
        block.is_comment_only = True
        return block

    # Extrair palavras preservando o token original
    matches = list(_WORD_RE.finditer(line))
    if not matches:
        block.is_comment_only = True
        return block

    words: List[Tuple[str, str, float]] = []
    for match in matches:
        letter = match.group(1)
        token = match.group(0)
        str_value = match.group(2)
        try:
            value = float(str_value)
        except ValueError:
            continue
        words.append((letter, token, value))

    if not words:
        block.is_comment_only = True
        return block

    block.words = words

    # Valor numérico da última ocorrência de cada letra (semântica G-Code)
    word_dict = {}
    for letter, _token, value in words:
        word_dict[letter.upper()] = value

    # Número de linha N
    if 'N' in word_dict:
        block.n = int(word_dict['N'])

    # Comandos G e M (G tem prioridade como "command").
    # O índice da palavra correspondente é guardado para que a reconstrução
    # altere somente esse comando e preserve os demais.
    last_g_index = None
    last_m_index = None
    for idx, (letter, _token, _value) in enumerate(words):
        upper = letter.upper()
        if upper == 'G':
            last_g_index = idx
        elif upper == 'M':
            last_m_index = idx

    if last_g_index is not None:
        g_num = word_dict['G']
        block.command = f"G{int(g_num)}" if g_num == int(g_num) else f"G{g_num}"
        block.command_word_index = last_g_index
    elif last_m_index is not None:
        block.command = f"M{int(word_dict['M'])}"
        block.command_word_index = last_m_index

    # Coordenadas
    for letter in _FIELD_ORDER:
        if letter in word_dict:
            setattr(block, _FIELD_ATTR_BY_LETTER[letter], word_dict[letter])

    # Classificar movimentos
    # Menções a G0/G1/G2/G3 fora da palavra principal (ex.: "G90 G0 X0")
    # também precisam ser reconhecidas como movimento.
    move_codes = set()
    for letter, _token, value in words:
        if letter.upper() == 'G':
            move_codes.add(int(value) if value == int(value) else value)

    if block.command in ('G0', 'G00') or 0 in move_codes:
        block.is_move = True
        block.is_rapid = True
    elif block.command in ('G1', 'G01', 'G2', 'G02', 'G3', 'G03') or move_codes & {1, 2, 3}:
        block.is_move = True

    # Snapshot para detecção de modificações
    block._original_values = {
        'command': block.command,
        **{attr: getattr(block, attr) for attr in _FIELD_ATTR_BY_LETTER.values()},
    }

    return block


def parse_file(filepath: str) -> List[GCodeBlock]:
    """Lê um arquivo G-Code e retorna lista de GCodeBlocks."""
    blocks = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for idx, line in enumerate(f):
            block = parse_line(line.rstrip('\n\r'), line_number=idx)
            blocks.append(block)
    return blocks


def write_file(blocks: List[GCodeBlock], filepath: str) -> None:
    """Reescreve um arquivo G-Code a partir de uma lista de GCodeBlocks."""
    with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
        for block in blocks:
            f.write(block.to_gcode() + '\n')


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def get_bounding_box(blocks: List[GCodeBlock]) -> Tuple[float, float, float, float]:
    """
    Retorna a bounding box XY do caminho de corte.

    Coordenadas modais (omitidas em uma linha) são propagadas da mesma forma
    que a máquina faria.

    Returns: (x_min, x_max, y_min, y_max)
    """
    xs, ys = [], []
    cur_x, cur_y = 0.0, 0.0

    for b in blocks:
        if not b.is_move:
            continue
        if b.x is not None:
            cur_x = b.x
        if b.y is not None:
            cur_y = b.y
        xs.append(cur_x)
        ys.append(cur_y)

    if not xs or not ys:
        return (0.0, 0.0, 0.0, 0.0)

    return (min(xs), max(xs), min(ys), max(ys))


def get_z_range(blocks: List[GCodeBlock]) -> Tuple[float, float]:
    """Retorna (z_min, z_max) de todos os movimentos."""
    zs = []
    cur_z = 0.0
    for b in blocks:
        if not b.is_move:
            continue
        if b.z is not None:
            cur_z = b.z
        zs.append(cur_z)

    if not zs:
        return (0.0, 0.0)
    return (min(zs), max(zs))


def get_bounding_box_3d(blocks: List[GCodeBlock]) -> Tuple[float, float, float, float, float, float]:
    """
    Retorna a bounding box XYZ completa de todos os movimentos.

    Returns: (x_min, x_max, y_min, y_max, z_min, z_max)
    """
    xs, ys, zs = [], [], []
    cur_x, cur_y, cur_z = 0.0, 0.0, 0.0

    for b in blocks:
        if not b.is_move:
            continue
        if b.x is not None:
            cur_x = b.x
        if b.y is not None:
            cur_y = b.y
        if b.z is not None:
            cur_z = b.z
        xs.append(cur_x)
        ys.append(cur_y)
        zs.append(cur_z)

    x_min = min(xs) if xs else 0.0
    x_max = max(xs) if xs else 0.0
    y_min = min(ys) if ys else 0.0
    y_max = max(ys) if ys else 0.0
    z_min = min(zs) if zs else 0.0
    z_max = max(zs) if zs else 0.0

    return (x_min, x_max, y_min, y_max, z_min, z_max)


def get_path_points(blocks: List[GCodeBlock]) -> Tuple[List, List, List, List, List, List]:
    """
    Extrai pontos da trajetória para visualização.
    Retorna: (cut_x, cut_y, cut_z, rapid_x, rapid_y, rapid_z)
    """
    cut_x, cut_y, cut_z = [], [], []
    rapid_x, rapid_y, rapid_z = [], [], []

    cur_x, cur_y, cur_z = 0.0, 0.0, 0.0

    for b in blocks:
        if not b.is_move:
            continue

        nx = b.x if b.x is not None else cur_x
        ny = b.y if b.y is not None else cur_y
        nz = b.z if b.z is not None else cur_z

        if b.is_rapid:
            rapid_x.extend([cur_x, nx, None])
            rapid_y.extend([cur_y, ny, None])
            rapid_z.extend([cur_z, nz, None])
        else:
            cut_x.extend([cur_x, nx, None])
            cut_y.extend([cur_y, ny, None])
            cut_z.extend([cur_z, nz, None])

        cur_x, cur_y, cur_z = nx, ny, nz

    return cut_x, cut_y, cut_z, rapid_x, rapid_y, rapid_z
