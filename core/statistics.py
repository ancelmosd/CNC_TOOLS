"""
statistics.py — Análise, estatísticas e estimativa de tempo de usinagem para G-Code.
"""

import math
from typing import List, Dict, Any, Tuple, Optional
from core.gcode_parser import GCodeBlock, get_bounding_box_3d
from core.rotary_wrap import (
    has_rotary_axis,
    resolve_rotary_config,
    rotary_point_3d,
)


def analyze_gcode(blocks: List[GCodeBlock],
                  default_rapid_feed: float = 2000.0,
                  rotary: Optional[dict] = None) -> Dict[str, Any]:
    """
    Analisa a lista de blocos de G-Code e extrai métricas detalhadas.

    Args:
        blocks: Lista de GCodeBlock.
        default_rapid_feed: Velocidade estimada para movimentos rápidos G0 (mm/min).
        rotary: Parâmetros opcionais do 4º eixo (diameter_mm, y_to_a,
                zero_at_surface, a_offset). Se omitido, usa os metadados
                gravados pelo próprio wrap rotativo.

    Returns:
        Dicionário com estatísticas completas e pontos de simulação.
    """
    total_lines = len(blocks)
    cut_distance = 0.0
    rapid_distance = 0.0
    
    cut_time_sec = 0.0
    rapid_time_sec = 0.0

    cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
    cur_f = 600.0  # Feed padrão se não especificado (mm/min)
    cur_s = None

    feeds_used = []
    spindles_used = []
    tools_used = set()
    cmd_counts: Dict[str, int] = {}

    # ---------------- Configuração do 4º eixo ----------------
    cfg = resolve_rotary_config(blocks, rotary)
    wrapped = has_rotary_axis(blocks)
    if cfg:
        diameter_mm = float(cfg["diameter_mm"])
        radius = max(0.1, diameter_mm / 2.0)
        circumference = math.pi * diameter_mm
        cfg_y_to_a = bool(cfg.get("y_to_a", True))
        cfg_offset = float(cfg.get("a_offset", 0.0))
        # Em blocos planos, Z é sempre a superfície do material.
        # Em blocos já enrolados, Z só é referenciado ao centro quando o
        # wrap foi feito com zero_at_surface=False.
        z_is_center = wrapped and not bool(cfg.get("zero_at_surface", True))
        first_a = next((b.a for b in blocks if b.is_move and b.a is not None), None)
        cur_a = float(first_a) if (wrapped and first_a is not None) else cfg_offset
        # Z referenciado ao centro: a posição inicial desconhecida é
        # assumida na superfície (raio), não no eixo.
        if wrapped and z_is_center:
            cur_z = radius
    else:
        diameter_mm = 0.0
        radius = 0.0
        circumference = 1.0
        cfg_y_to_a = True
        cfg_offset = 0.0
        z_is_center = False
        cur_a = 0.0

    # Pontos para simulação: [(x, y, z, is_rapid, feed, line_number)]
    # Em modo rotativo, (x, y, z) já são as coordenadas 3D enroladas no
    # cilindro — as mesmas usadas para desenhar o percurso estático.
    sim_points: List[Tuple[float, float, float, bool, float, int]] = []
    # Estado de máquina alinhado a sim_points: (x, y, a, z). Permite ao
    # visualizador animar a peça no modo "peça se move".
    sim_rotary: List[Optional[Tuple[float, float, float, float]]] = []

    if cfg:
        p0 = rotary_point_3d(0.0, 0.0, cur_a, cur_z, diameter_mm,
                             cfg_y_to_a, z_is_center)
        sim_points.append((p0[0], p0[1], p0[2], True, default_rapid_feed, 0))
        sim_rotary.append((0.0, 0.0, cur_a, cur_z))
    else:
        sim_points.append((0.0, 0.0, 0.0, True, default_rapid_feed, 0))
        sim_rotary.append(None)

    for b in blocks:
        cmd = (b.command or "").upper()
        if cmd:
            cmd_counts[cmd] = cmd_counts.get(cmd, 0) + 1

        if b.f is not None and b.f > 0:
            cur_f = b.f
            feeds_used.append(b.f)

        if b.s is not None and b.s > 0:
            cur_s = b.s
            spindles_used.append(b.s)

        # Rastrear ferramentas em T ou comentários
        if hasattr(b, "words") and b.words:
            for item in b.words:
                letter = item[0] if isinstance(item, (tuple, list)) else str(item)
                token = item[1] if isinstance(item, (tuple, list)) and len(item) > 1 else str(item)
                if letter.upper() == "T":
                    tools_used.add(token.upper())
        if cmd in ("M6", "M06"):
            t_name = f"Ferramenta (linha {b.line_number})"
            tools_used.add(t_name)

        if not b.is_move:
            continue

        nx = b.x if b.x is not None else cur_x
        ny = b.y if b.y is not None else cur_y
        nz = b.z if b.z is not None else cur_z

        # Ângulo A do próximo ponto (modal quando omitido)
        if cfg:
            if b.a is not None:
                na = b.a
            elif wrapped:
                na = cur_a
            else:
                linear = ny if cfg_y_to_a else nx
                na = (linear / circumference) * 360.0 + cfg_offset

            # Interpolar movimentos angulares para o trajeto 3D ficar
            # contínuo (uma volta completa não pode "teleportar" a fresa).
            da = abs(na - cur_a)
            subdivs = max(1, int(math.ceil(da / 3.0)))
            subdivs = min(subdivs, 120)
        else:
            na = cur_a
            subdivs = 1

        feed_for_seg = default_rapid_feed if b.is_rapid else cur_f

        prev_p = (rotary_point_3d(cur_x, cur_y, cur_a, cur_z, diameter_mm,
                                  cfg_y_to_a, z_is_center)
                  if cfg else (cur_x, cur_y, cur_z))

        new_points = []
        new_machine = []
        seg_dist = 0.0

        for step in range(1, subdivs + 1):
            t = step / float(subdivs)
            ix = cur_x + t * (nx - cur_x)
            iy = cur_y + t * (ny - cur_y)
            iz = cur_z + t * (nz - cur_z)

            if cfg:
                ia = cur_a + t * (na - cur_a)
                p = rotary_point_3d(ix, iy, ia, iz, diameter_mm,
                                    cfg_y_to_a, z_is_center)
                new_machine.append((ix, iy, ia, iz))
            else:
                ia = cur_a
                p = (ix, iy, iz)
                new_machine.append(None)

            seg_dist += math.sqrt(
                (p[0] - prev_p[0]) ** 2 +
                (p[1] - prev_p[1]) ** 2 +
                (p[2] - prev_p[2]) ** 2
            )
            prev_p = p

            new_points.append((p[0], p[1], p[2], b.is_rapid,
                               feed_for_seg, b.line_number))

        if seg_dist > 1e-6:
            if b.is_rapid:
                rapid_distance += seg_dist
                rapid_time_sec += (seg_dist / feed_for_seg) * 60.0
            else:
                cut_distance += seg_dist
                cut_time_sec += (seg_dist / feed_for_seg) * 60.0

            sim_points.extend(new_points)
            sim_rotary.extend(new_machine)

        cur_x, cur_y, cur_z, cur_a = nx, ny, nz, na

    total_dist = cut_distance + rapid_distance
    total_time_sec = cut_time_sec + rapid_time_sec

    bbox = get_bounding_box_3d(blocks)
    xmin, xmax, ymin, ymax, zmin, zmax = bbox

    return {
        "total_lines": total_lines,
        "cut_distance": cut_distance,
        "rapid_distance": rapid_distance,
        "total_distance": total_dist,
        "cut_time_sec": cut_time_sec,
        "rapid_time_sec": rapid_time_sec,
        "total_time_sec": total_time_sec,
        "min_feed": min(feeds_used) if feeds_used else cur_f,
        "max_feed": max(feeds_used) if feeds_used else cur_f,
        "avg_feed": (sum(feeds_used) / len(feeds_used)) if feeds_used else cur_f,
        "min_spindle": min(spindles_used) if spindles_used else 0.0,
        "max_spindle": max(spindles_used) if spindles_used else 0.0,
        "tools": sorted(list(tools_used)),
        "command_counts": cmd_counts,
        "bbox": {
            "xmin": xmin, "xmax": xmax,
            "ymin": ymin, "ymax": ymax,
            "zmin": zmin, "zmax": zmax,
            "dx": xmax - xmin,
            "dy": ymax - ymin,
            "dz": zmax - zmin
        },
        "sim_points": sim_points,
        "sim_rotary": sim_rotary,
        "rotary_config": cfg,
    }


def format_duration(seconds: float) -> str:
    """Formata segundos em HH:MM:SS ou MM:SS amigável."""
    if seconds < 0:
        return "00:00"
    total_sec = int(round(seconds))
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"
