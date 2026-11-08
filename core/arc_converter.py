"""
arc_converter.py — Converte arcos (G2/G3) em segmentos lineares (G1).

Útil para controladores que não suportam interpolação circular,
ou para facilitar transformações que não preservam arcos corretamente.
"""

import math
import copy
from typing import List
from core.gcode_parser import GCodeBlock


def arc_to_lines(blocks: List[GCodeBlock],
                 tolerance_mm: float = 0.01) -> List[GCodeBlock]:
    """
    Converte todos os comandos G2/G3 em sequências de G1.

    Args:
        blocks: Lista de GCodeBlocks originais.
        tolerance_mm: Tolerância máxima de corda (mm). Controla o número
                      de segmentos gerados. Menor valor = mais segmentos
                      = maior precisão.

    Returns:
        Nova lista de GCodeBlocks com arcos substituídos por linhas.
    """
    result = []
    cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
    cur_f = None

    for b in blocks:
        # Atualizar posição corrente para movimentos não-arco
        if b.command in ('G0', 'G00', 'G1', 'G01'):
            if b.x is not None:
                cur_x = b.x
            if b.y is not None:
                cur_y = b.y
            if b.z is not None:
                cur_z = b.z
            if b.f is not None:
                cur_f = b.f
            result.append(copy.deepcopy(b))
            continue

        if b.command not in ('G2', 'G02', 'G3', 'G03'):
            result.append(copy.deepcopy(b))
            continue

        # ----- Converter arco -----
        clockwise = b.command in ('G2', 'G02')

        # Ponto final
        end_x = b.x if b.x is not None else cur_x
        end_y = b.y if b.y is not None else cur_y
        end_z = b.z if b.z is not None else cur_z
        feed = b.f if b.f is not None else cur_f

        segments = _arc_to_segments(
            start=(cur_x, cur_y),
            end=(end_x, end_y),
            i_offset=b.i,
            j_offset=b.j,
            radius=b.r,
            clockwise=clockwise,
            start_z=cur_z,
            end_z=end_z,
            tolerance=tolerance_mm,
        )

        for sx, sy, sz in segments:
            nb = GCodeBlock(raw="", line_number=b.line_number)
            nb.command = 'G1'
            nb.x = round(sx, 4)
            nb.y = round(sy, 4)
            nb.z = round(sz, 4) if abs(sz - cur_z) > 1e-6 or sz != end_z else None
            if feed is not None:
                nb.f = feed
                feed = None  # só no primeiro segmento
            nb.is_move = True
            nb.comment = f"arc from G{2 if clockwise else 3}"
            result.append(nb)

        cur_x, cur_y, cur_z = end_x, end_y, end_z
        if b.f is not None:
            cur_f = b.f

    return result


# ---------------------------------------------------------------------------
# Funções internas de geometria
# ---------------------------------------------------------------------------

def _arc_to_segments(start, end, i_offset, j_offset, radius,
                     clockwise, start_z, end_z, tolerance):
    """
    Calcula os pontos intermediários de um arco.
    Suporta arcos definidos por I/J (offset do centro) ou R (raio).
    """
    sx, sy = start
    ex, ey = end

    if i_offset is not None or j_offset is not None:
        # Definição por I/J: centro relativo ao ponto de início
        ci = sx + (i_offset or 0.0)
        cj = sy + (j_offset or 0.0)
    elif radius is not None:
        # Definição por R
        ci, cj = _center_from_radius(sx, sy, ex, ey, radius, clockwise)
    else:
        # Sem info suficiente, retornar linha reta
        return [(ex, ey, end_z)]

    r = math.hypot(sx - ci, sy - cj)
    if r < 1e-9:
        return [(ex, ey, end_z)]

    # Ângulos de início e fim
    start_angle = math.atan2(sy - cj, sx - ci)
    end_angle = math.atan2(ey - cj, ex - ci)

    # Detectar arco de círculo completo (ponto inicial ≈ ponto final)
    is_full_circle = (abs(sx - ex) < 1e-6 and abs(sy - ey) < 1e-6)

    if is_full_circle:
        # Círculo completo: percorrer 360° na direção correta
        if clockwise:
            end_angle = start_angle - 2 * math.pi
        else:
            end_angle = start_angle + 2 * math.pi
    else:
        if clockwise:
            if end_angle >= start_angle:
                end_angle -= 2 * math.pi
        else:
            if end_angle <= start_angle:
                end_angle += 2 * math.pi

    arc_angle = abs(end_angle - start_angle)

    # Número de segmentos pela tolerância de corda
    # tolerância = r - r*cos(θ/2)  →  θ = 2*acos(1 - tol/r)
    if tolerance > 0 and r > 0:
        half_angle = math.acos(max(-1.0, min(1.0, 1.0 - tolerance / r)))
        n_segments = max(1, math.ceil(arc_angle / (2 * half_angle)))
    else:
        n_segments = 32

    n_segments = min(n_segments, 1000)  # limite de segurança

    points = []
    for k in range(1, n_segments + 1):
        t = k / n_segments
        angle = start_angle + t * (end_angle - start_angle)
        px = ci + r * math.cos(angle)
        py = cj + r * math.sin(angle)
        pz = start_z + t * (end_z - start_z)
        points.append((px, py, pz))

    return points


def _center_from_radius(sx, sy, ex, ey, r, clockwise):
    """Calcula o centro do arco a partir do raio (pode ter duas soluções)."""
    dx = ex - sx
    dy = ey - sy
    d = math.hypot(dx, dy)
    if d < 1e-9 or abs(r) < d / 2:
        # Fallback: ponto médio
        return (sx + ex) / 2, (sy + ey) / 2

    # Distância do ponto médio ao centro
    h = math.sqrt(r * r - (d / 2) ** 2)

    # Ponto médio
    mx = (sx + ex) / 2
    my = (sy + ey) / 2

    # Perpendicular normalizada
    px = -dy / d
    py = dx / d

    # Duas possíveis posições de centro
    if (r > 0 and not clockwise) or (r < 0 and clockwise):
        cx = mx + h * px
        cy = my + h * py
    else:
        cx = mx - h * px
        cy = my - h * py

    return cx, cy
