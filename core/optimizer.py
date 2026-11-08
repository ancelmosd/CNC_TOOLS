"""
optimizer.py — Otimização, limpeza e compactação de código G-Code.

Recursos:
- Remoção de movimentos com distância zero (pontos duplicados consecutivos)
- Remoção de comandos modais redundantes
- Arredondamento e normalização de precisão decimal (ex: 3 ou 4 casas)
- Remoção ou limpeza de comentários e linhas em branco
- Cálculo de estatísticas de redução de tamanho de arquivo e linhas
"""

import math
from typing import List, Tuple, Dict, Any, Optional
from core.gcode_parser import GCodeBlock, parse_line


def optimize_gcode(blocks: List[GCodeBlock],
                   remove_zero_distance: bool = True,
                   remove_comments: bool = False,
                   remove_blank_lines: bool = True,
                   decimal_places: Optional[int] = 3) -> Tuple[List[GCodeBlock], Dict[str, Any]]:
    """
    Otimiza a lista de blocos de G-Code removendo redundâncias.

    Args:
        blocks: Lista de GCodeBlock originais.
        remove_zero_distance: Se True, elimina movimentos que não alteram posição XYZ.
        remove_comments: Se True, remove comentários para reduzir o tamanho.
        remove_blank_lines: Se True, remove linhas vazias.
        decimal_places: Número de casas decimais para arredondamento (None para manter).

    Returns:
        (blocos_otimizados, estatisticas_da_otimizacao)
    """
    orig_total_lines = len(blocks)
    orig_char_count = sum(len(b.to_gcode()) for b in blocks)

    optimized: List[GCodeBlock] = []

    cur_x: Optional[float] = None
    cur_y: Optional[float] = None
    cur_z: Optional[float] = None
    cur_a: Optional[float] = None
    cur_f: Optional[float] = None

    eliminated_zero_moves = 0
    eliminated_blanks = 0
    eliminated_comments = 0

    for b in blocks:
        # 1. Linhas vazias
        raw_clean = b.raw.strip() if b.raw else ""
        if remove_blank_lines and not raw_clean and not b.command and not b.is_move:
            eliminated_blanks += 1
            continue

        # 2. Comentários puros
        if remove_comments and b.is_comment_only:
            eliminated_comments += 1
            continue

        # Clonar bloco para trabalhar
        nb = GCodeBlock(raw="", line_number=len(optimized) + 1)
        nb.command = b.command
        nb.comment = "" if remove_comments else b.comment
        nb.is_comment_only = b.is_comment_only
        nb.is_move = b.is_move
        nb.is_rapid = b.is_rapid
        nb.n = b.n

        # Tratar precisão decimal
        def round_coord(v: Optional[float]) -> Optional[float]:
            if v is None:
                return None
            if decimal_places is not None:
                return round(v, decimal_places)
            return v

        nb.x = round_coord(b.x)
        nb.y = round_coord(b.y)
        nb.z = round_coord(b.z)
        nb.a = round_coord(b.a)
        nb.i = round_coord(b.i)
        nb.j = round_coord(b.j)
        nb.k = round_coord(b.k)
        nb.r = round_coord(b.r)
        nb.f = round_coord(b.f)
        nb.s = round_coord(b.s)

        # 3. Eliminação de movimentos de distância zero
        if b.is_move and remove_zero_distance:
            # Posições pretendidas
            target_x = nb.x if nb.x is not None else cur_x
            target_y = nb.y if nb.y is not None else cur_y
            target_z = nb.z if nb.z is not None else cur_z
            target_a = nb.a if nb.a is not None else cur_a

            # Verificar se já temos uma posição anterior conhecida
            if cur_x is not None and cur_y is not None and cur_z is not None:
                dx = (target_x - cur_x) if target_x is not None else 0.0
                dy = (target_y - cur_y) if target_y is not None else 0.0
                dz = (target_z - cur_z) if target_z is not None else 0.0
                da = (target_a - cur_a) if (target_a is not None and cur_a is not None) else 0.0

                dist = math.sqrt(dx * dx + dy * dy + dz * dz) + abs(da)

                # Se a distância for zero e não tiver mudança importante (como F ou S novo)
                # e não for arco G2/G3 (que pode ter o mesmo início e fim em círculo completo)
                if dist < 1e-5 and nb.command in ('G0', 'G00', 'G1', 'G01'):
                    feed_changed = (nb.f is not None and nb.f != cur_f)
                    spindle_changed = (nb.s is not None)
                    if not feed_changed and not spindle_changed:
                        eliminated_zero_moves += 1
                        continue

            # Atualizar coordenadas correntes
            if target_x is not None:
                cur_x = target_x
            if target_y is not None:
                cur_y = target_y
            if target_z is not None:
                cur_z = target_z
            if target_a is not None:
                cur_a = target_a
        elif b.is_move:
            if nb.x is not None:
                cur_x = nb.x
            if nb.y is not None:
                cur_y = nb.y
            if nb.z is not None:
                cur_z = nb.z
            if nb.a is not None:
                cur_a = nb.a

        if nb.f is not None:
            cur_f = nb.f

        optimized.append(nb)

    new_total_lines = len(optimized)
    new_char_count = sum(len(b.to_gcode()) for b in optimized)

    lines_reduced = orig_total_lines - new_total_lines
    chars_reduced = orig_char_count - new_char_count
    pct_reduced = (chars_reduced / max(1, orig_char_count)) * 100.0

    stats = {
        "original_lines": orig_total_lines,
        "optimized_lines": new_total_lines,
        "lines_reduced": lines_reduced,
        "eliminated_zero_moves": eliminated_zero_moves,
        "eliminated_blanks": eliminated_blanks,
        "eliminated_comments": eliminated_comments,
        "original_bytes": orig_char_count,
        "optimized_bytes": new_char_count,
        "bytes_reduced": chars_reduced,
        "percent_reduced": max(0.0, pct_reduced)
    }

    return optimized, stats

