"""
transforms.py — Transformações geométricas sobre listas de GCodeBlocks.

Operações suportadas:
- Escalar (X, Y, Z independentemente)
- Transladar (mover origem)
- Espelhar (flip X ou Y)
- Rotacionar em torno de um ponto
"""

import math
import copy
from typing import List, Tuple, Optional
from core.gcode_parser import GCodeBlock


def _apply_to_moves(blocks: List[GCodeBlock], func) -> List[GCodeBlock]:
    """Aplica func(block) a todos os blocos de movimento. Retorna nova lista (deep copy)."""
    result = copy.deepcopy(blocks)
    for b in result:
        if b.is_move:
            func(b)
    return result


# ---------------------------------------------------------------------------
# Escalar
# ---------------------------------------------------------------------------

def scale(blocks: List[GCodeBlock],
          sx: float = 1.0,
          sy: float = 1.0,
          sz: float = 1.0) -> List[GCodeBlock]:
    """
    Escala as coordenadas X, Y, Z de todos os movimentos.

    Args:
        blocks: Lista de GCodeBlocks originais.
        sx: Fator de escala em X.
        sy: Fator de escala em Y.
        sz: Fator de escala em Z.

    Returns:
        Nova lista de GCodeBlocks com coordenadas escaladas.
    """
    def _scale(b: GCodeBlock):
        if b.x is not None:
            b.x *= sx
        if b.y is not None:
            b.y *= sy
        if b.z is not None:
            b.z *= sz
        # Escalar também offsets de arco
        if b.i is not None:
            b.i *= sx
        if b.j is not None:
            b.j *= sy
        if b.k is not None:
            b.k *= sz

        # Escala com sinal negativo em apenas um eixo equivale a espelhar:
        # o sentido de giro do arco se inverte.
        if sx * sy < 0:
            if b.command in ('G2', 'G02'):
                b.command = 'G3'
            elif b.command in ('G3', 'G03'):
                b.command = 'G2'

    return _apply_to_moves(blocks, _scale)


# ---------------------------------------------------------------------------
# Transladar
# ---------------------------------------------------------------------------

def translate(blocks: List[GCodeBlock],
              dx: float = 0.0,
              dy: float = 0.0,
              dz: float = 0.0) -> List[GCodeBlock]:
    """
    Move (translada) todas as coordenadas pelo offset dado.

    Args:
        blocks: Lista de GCodeBlocks originais.
        dx: Deslocamento em X.
        dy: Deslocamento em Y.
        dz: Deslocamento em Z.

    Returns:
        Nova lista de GCodeBlocks transladada.
    """
    def _translate(b: GCodeBlock):
        if b.x is not None:
            b.x += dx
        if b.y is not None:
            b.y += dy
        if b.z is not None:
            b.z += dz
        # Offsets I/J/K NÃO são transladados (são relativos ao ponto inicial)

    return _apply_to_moves(blocks, _translate)


# ---------------------------------------------------------------------------
# Espelhar
# ---------------------------------------------------------------------------

def mirror_x(blocks: List[GCodeBlock]) -> List[GCodeBlock]:
    """Espelha em X (inverte sinal de X e I)."""
    def _mirror(b: GCodeBlock):
        if b.x is not None:
            b.x = -b.x
        if b.i is not None:
            b.i = -b.i
        # Inversão de sentido do arco: G2 ↔ G3
        if b.command in ('G2', 'G02'):
            b.command = 'G3'
        elif b.command in ('G3', 'G03'):
            b.command = 'G2'

    return _apply_to_moves(blocks, _mirror)


def mirror_y(blocks: List[GCodeBlock]) -> List[GCodeBlock]:
    """Espelha em Y (inverte sinal de Y e J)."""
    def _mirror(b: GCodeBlock):
        if b.y is not None:
            b.y = -b.y
        if b.j is not None:
            b.j = -b.j
        if b.command in ('G2', 'G02'):
            b.command = 'G3'
        elif b.command in ('G3', 'G03'):
            b.command = 'G2'

    return _apply_to_moves(blocks, _mirror)


# ---------------------------------------------------------------------------
# Rotacionar
# ---------------------------------------------------------------------------

def rotate(blocks: List[GCodeBlock],
           angle_deg: float,
           cx: float = 0.0,
           cy: float = 0.0) -> List[GCodeBlock]:
    """
    Rotaciona o G-Code em torno do ponto (cx, cy) pelo ângulo dado.

    Args:
        blocks: Lista de GCodeBlocks originais.
        angle_deg: Ângulo em graus (positivo = anti-horário).
        cx: Coordenada X do ponto de rotação.
        cy: Coordenada Y do ponto de rotação.

    Returns:
        Nova lista de GCodeBlocks rotacionada.
    """
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    def _rotate_point(x: float, y: float) -> Tuple[float, float]:
        rx = x - cx
        ry = y - cy
        nx = rx * cos_a - ry * sin_a + cx
        ny = rx * sin_a + ry * cos_a + cy
        return nx, ny

    result = copy.deepcopy(blocks)
    cur_x, cur_y = 0.0, 0.0

    for b in result:
        if not b.is_move:
            continue

        # Coordenadas modais: se só X (ou só Y) vier na linha, o outro eixo
        # assume a posição atual da máquina — NÃO zero.
        has_xy = b.x is not None or b.y is not None
        if b.x is not None:
            cur_x = b.x
        if b.y is not None:
            cur_y = b.y

        if has_xy:
            nx, ny = _rotate_point(cur_x, cur_y)
            # Os dois eixos precisam ser gravados: a rotação altera ambos.
            b.x = nx
            b.y = ny
            # `cur_x`/`cur_y` continuam no sistema ORIGINAL: eles representam
            # as coordenadas modais de entrada da próxima linha.

        # Rotacionar também os offsets I/J do arco (ausente = 0, não modal)
        if b.i is not None or b.j is not None:
            oi = b.i if b.i is not None else 0.0
            oj = b.j if b.j is not None else 0.0
            b.i = oi * cos_a - oj * sin_a
            b.j = oi * sin_a + oj * cos_a

    return result
