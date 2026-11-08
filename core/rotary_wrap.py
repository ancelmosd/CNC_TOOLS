"""
rotary_wrap.py — Converte G-Code XY plano para corte em eixo rotativo (4º eixo).

Mapeamento:
  Eixo Y (mm) → Eixo A (graus), de acordo com a circunferência do cilindro.
  Fórmula: A = (Y / (π × diâmetro)) × 360°

O eixo X permanece como X (avanço ao longo do cilindro).
O eixo Z permanece como Z (profundidade de corte).
"""

import math
import copy
from typing import List, Optional
from core.gcode_parser import GCodeBlock
from core.arc_converter import arc_to_lines


def wrap_to_rotary(blocks: List[GCodeBlock],
                   diameter_mm: float,
                   y_to_a: bool = True,
                   a_offset: float = 0.0,
                   zero_at_surface: bool = True) -> List[GCodeBlock]:
    """
    Converte G-Code plano XY para eixo rotativo (A = 4º eixo).

    O eixo Y é mapeado para rotação angular A.
    O eixo X permanece inalterado (comprimento ao longo do cilindro).

    Args:
        blocks: Lista de GCodeBlocks originais (G-Code plano).
        diameter_mm: Diâmetro do cilindro em mm.
        y_to_a: Se True, mapeia Y→A. Se False, mapeia X→A e Y permanece.
        a_offset: Offset angular inicial em graus (rotação de início).
        zero_at_surface: Se True, Z=0 está na superfície externa do cilindro
                         (Z negativo corta para dentro). Se False, Z=0 está
                         no centro do eixo de rotação.

    Returns:
        Nova lista de GCodeBlocks com eixo A ao invés de Y (ou X).
    """
    if diameter_mm <= 0:
        raise ValueError("Diâmetro do cilindro deve ser maior que zero.")

    # Arcos G2/G3 não podem ser simplesmente "desenrolados" no cilindro.
    # Converter para segmentos G1 antes evita que virem retas incorretas.
    if any(b.command in ('G2', 'G02', 'G3', 'G03') for b in blocks):
        blocks = arc_to_lines(blocks)

    circumference = math.pi * diameter_mm  # mm por revolução completa

    radius = diameter_mm / 2.0

    result = copy.deepcopy(blocks)

    # Guardar os parâmetros do wrap em cada movimento. Assim a simulação 3D
    # consegue reconstruir o percurso enrolado mesmo depois de outras
    # transformações (ou de um undo), sem precisar de estado externo.
    rotary_meta = {
        "diameter_mm": diameter_mm,
        "y_to_a": y_to_a,
        "a_offset": a_offset,
        "zero_at_surface": zero_at_surface,
    }

    for b in result:
        if not b.is_move:
            continue
        b.rotary = dict(rotary_meta)

        if y_to_a:
            if b.y is not None:
                # Converter Y (mm) → A (graus)
                b.a = round((b.y / circumference) * 360.0 + a_offset, 4)
                b.y = None  # Remover Y
        else:
            if b.x is not None:
                b.a = round((b.x / circumference) * 360.0 + a_offset, 4)
                b.x = None

        # Ajustar Z conforme a referência de origem
        if not zero_at_surface and b.z is not None:
            # Se zero_at_surface=False, Z=0 está no centro do eixo.
            # O G-Code plano assume Z=0 na superfície, então deslocamos:
            # Z_centro = Z_superfície + raio
            b.z = round(b.z + radius, 4)

        # Arcos não fazem sentido após o wrap: seriam convertidos para G1 antes
        if b.command in ('G2', 'G02', 'G3', 'G03'):
            b.command = 'G1'
            b.i = None
            b.j = None
            b.k = None
            b.r = None

    return result


def has_rotary_axis(blocks: List[GCodeBlock]) -> bool:
    """True se algum movimento já possui o eixo rotativo A explícito."""
    return any(b.is_move and b.a is not None for b in blocks)


def rotary_config_from_blocks(blocks: List[GCodeBlock]) -> Optional[dict]:
    """Recupera os parâmetros do wrapper gravados nos blocos (se existirem)."""
    for b in blocks:
        cfg = getattr(b, "rotary", None)
        if cfg:
            return dict(cfg)
    return None


def resolve_rotary_config(blocks: List[GCodeBlock],
                          rotary: Optional[dict] = None) -> Optional[dict]:
    """
    Resolve os parâmetros do 4º eixo para simulação.

    Prioridade: dicionário explícito > metadados gravados pelo wrap.
    Retorna None quando não há informação suficiente.
    """
    cfg = dict(rotary) if rotary else rotary_config_from_blocks(blocks)
    if not cfg:
        return None

    try:
        diameter = float(cfg.get("diameter_mm", 0.0))
    except (TypeError, ValueError):
        return None
    if diameter <= 0:
        return None

    cfg["diameter_mm"] = diameter
    cfg.setdefault("y_to_a", True)
    cfg.setdefault("a_offset", 0.0)
    cfg.setdefault("zero_at_surface", True)
    return cfg


def rotary_point_3d(x: float, y: float, a: float, z: float,
                    diameter_mm: float,
                    y_to_a: bool = True,
                    z_is_center: bool = False) -> tuple:
    """
    Converte uma posição de máquina (X, Y, A, Z) para um ponto 3D no cilindro.

    Args:
        x, y, a, z: coordenadas de máquina (A em graus).
        diameter_mm: diâmetro do tarugo.
        y_to_a: True → cilindro ao longo de X (Y virou A).
                False → cilindro ao longo de Y (X virou A).
        z_is_center: True → Z já está referenciado ao centro do eixo.
                     False → Z está referenciado à superfície externa.
    """
    radius = max(0.1, diameter_mm / 2.0)
    r_eff = max(0.01, z) if z_is_center else (radius + z)
    rad = math.radians(a)
    sin_a = math.sin(rad)
    cos_a = math.cos(rad)

    if y_to_a:
        return (x, r_eff * sin_a, r_eff * cos_a)
    return (r_eff * sin_a, y, r_eff * cos_a)


def rotary_workpiece_matrix(x: float, y: float, a: float,
                            y_to_a: bool = True) -> List[List[float]]:
    """
    Matriz 4x4 do modo "peça se move".

    A cena é montada no referencial do rotor (ponto da superfície na posição
    angular A). Para manter a ferramenta fixa no topo do cilindro, aplicamos
    a transformação inversa à peça e ao percurso: rotação de -A e translação
    do eixo linear, levando o ponto atual para (0, 0, r).

    Retorna a matriz em formato de lista 4x4 (linha/coluna), compatível com
    numpy e com vtkMatrix4x4.
    """
    rad = math.radians(a)

    if y_to_a:
        # Ponto atual: (x, r·sin A, r·cos A) → rotaciona +A em X → (x, 0, r)
        ca, sa = math.cos(rad), math.sin(rad)
        return [
            [1.0, 0.0, 0.0, -x],
            [0.0, ca, -sa, 0.0],
            [0.0, sa, ca, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]

    # Ponto atual: (r·sin A, y, r·cos A) → rotaciona -A em Y → (0, y, r)
    theta = -rad
    ca, sa = math.cos(theta), math.sin(theta)
    return [
        [ca, 0.0, sa, 0.0],
        [0.0, 1.0, 0.0, -y],
        [-sa, 0.0, ca, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def calculate_feed_for_rotary(linear_feed_mm_min: float,
                               diameter_mm: float) -> float:
    """
    Converte feed rate linear (mm/min) para feed angular (graus/min).

    Útil quando o controlador usa graus/min para o eixo A.

    Args:
        linear_feed_mm_min: Velocidade de avanço original em mm/min.
        diameter_mm: Diâmetro do cilindro em mm.

    Returns:
        Feed rate em graus/min para o eixo rotativo.
    """
    circumference = math.pi * diameter_mm
    return (linear_feed_mm_min / circumference) * 360.0


def estimate_cylinder_dimensions(blocks: List[GCodeBlock],
                                 y_to_a: bool = True) -> dict:
    """
    Estima as dimensões necessárias para wrapping baseado no G-Code.

    O mapeamento define qual eixo vira rotação:
        - y_to_a=True  → Y vira A (cilindro ao longo de X)
        - y_to_a=False → X vira A (cilindro ao longo de Y)

    O diâmetro sugerido é calculado sobre o percurso do eixo que será
    enrolado (Y no modo Y→A, X no modo X→A), garantindo que o trajeto caiba
    em no máximo uma volta completa e evitando sobreposição de linhas.

    Args:
        blocks: Lista de GCodeBlocks.
        y_to_a: Mapeamento do 4º eixo selecionado.

    Returns:
        Dicionário com:
        - axis_length: comprimento do tarugo ao longo do eixo do cilindro (mm)
        - wrap_travel: percurso linear que será convertido em A (mm)
        - suggested_diameter: diâmetro mínimo sugerido (mm)
        - x_length / y_travel: mantidos para compatibilidade
    """
    xs = [b.x for b in blocks if b.is_move and b.x is not None]
    ys = [b.y for b in blocks if b.is_move and b.y is not None]

    x_range = (max(xs) - min(xs)) if xs else 0.0
    y_range = (max(ys) - min(ys)) if ys else 0.0

    if y_to_a:
        axis_range = x_range      # cilindro ao longo de X
        wrap_range = y_range      # Y vira A
    else:
        axis_range = y_range      # cilindro ao longo de Y
        wrap_range = x_range      # X vira A

    # Diâmetro mínimo para que o percurso enrolado caiba em uma volta
    suggested_diameter = (wrap_range / math.pi) if wrap_range > 0 else 0.0

    return {
        "axis_length": round(axis_range, 3),
        "wrap_travel": round(wrap_range, 3),
        "suggested_diameter": round(suggested_diameter, 3),
        # Compatibilidade com chamadas antigas
        "x_length": round(x_range, 3),
        "y_travel": round(y_range, 3),
    }


def extract_rotary_trajectories_3d(blocks: List[GCodeBlock],
                                   diameter_mm: float,
                                   y_to_a: bool = True,
                                   zero_at_surface: bool = True,
                                   a_offset: float = 0.0) -> dict:
    """
    Converte percursos de G-Code em segmentos 3D enrolados no cilindro.
    Subdivide segmentos angulares para criar curvas perfeitas na casca cilíndrica.

    Args:
        blocks: Lista de GCodeBlocks (planos ou já com eixo A).
        diameter_mm: Diâmetro do cilindro em mm.
        y_to_a: Se True, cilindro está ao longo do eixo X (Y vira A).
                Se False, cilindro está ao longo do eixo Y (X vira A).
        zero_at_surface: Se True, Z=0 é a superfície externa do tarugo (R = D/2).
                         Se False, Z=0 é o centro do eixo do cilindro.
        a_offset: Offset angular inicial em graus.

    Returns:
        Dicionário com:
        - g1_lines: lista de segmentos [(x1,y1,z1), (x2,y2,z2)]
        - g0_lines: lista de segmentos [(x1,y1,z1), (x2,y2,z2)]
        - cylinder: parâmetros do cilindro (centro, direção, raio, altura, min, max)
    """
    radius = max(0.1, diameter_mm / 2.0)
    circumference = math.pi * diameter_mm

    # Se os blocos já vieram do wrap, o Z pode estar referenciado ao centro
    # do eixo (zero_at_surface=False). Em blocos planos, Z é sempre a
    # superfície do material, então somamos o raio.
    wrapped = has_rotary_axis(blocks)
    z_is_center = wrapped and not zero_at_surface

    cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
    first_a = next((b.a for b in blocks if b.is_move and b.a is not None), None)
    cur_a = float(first_a) if (wrapped and first_a is not None) else a_offset
    if wrapped and z_is_center:
        # Posição inicial assumida na superfície (Z=raio no referencial
        # do centro), evitando um segmento saindo do eixo do cilindro.
        cur_z = radius

    g1_lines = []
    g0_lines = []

    all_linear_pos = []

    def get_pt_3d(x_val: float, y_val: float, a_val: float, z_val: float):
        return rotary_point_3d(
            x_val, y_val, a_val, z_val,
            diameter_mm=diameter_mm,
            y_to_a=y_to_a,
            z_is_center=z_is_center,
        )

    for b in blocks:
        if not b.is_move:
            continue

        nx = b.x if b.x is not None else cur_x
        ny = b.y if b.y is not None else cur_y
        nz = b.z if b.z is not None else cur_z

        # Determinar ângulo A (modal quando omitido no G-Code)
        if b.a is not None:
            na = b.a
        elif wrapped:
            # Blocos já enrolados: A omitido significa "mantém o ângulo".
            na = cur_a
        elif y_to_a:
            na = (ny / circumference) * 360.0 + a_offset
        else:
            na = (nx / circumference) * 360.0 + a_offset

        # Coletar posição ao longo do eixo linear para determinar o comprimento do cilindro
        lin_coord = nx if y_to_a else ny
        all_linear_pos.append(lin_coord)

        # Verificar se precisa subdividir o arco para acompanhar a curvatura do cilindro
        da = na - cur_a
        subdivs = max(1, int(math.ceil(abs(da) / 3.0)))
        subdivs = min(subdivs, 120)  # limite de segurança

        p_prev = get_pt_3d(cur_x, cur_y, cur_a, cur_z)

        for step in range(1, subdivs + 1):
            t = step / float(subdivs)
            ix = cur_x + t * (nx - cur_x)
            iy = cur_y + t * (ny - cur_y)
            ia = cur_a + t * (na - cur_a)
            iz = cur_z + t * (nz - cur_z)

            p_next = get_pt_3d(ix, iy, ia, iz)

            if b.is_rapid:
                g0_lines.append([p_prev, p_next])
            else:
                g1_lines.append([p_prev, p_next])

            p_prev = p_next

        cur_x, cur_y, cur_z, cur_a = nx, ny, nz, na

    # Determinar limites e centro do cilindro de material
    if all_linear_pos:
        l_min = min(all_linear_pos)
        l_max = max(all_linear_pos)
    else:
        l_min, l_max = 0.0, 100.0

    length = max(1.0, l_max - l_min)
    # Adicionar 5% de margem visual nas extremidades para o tarugo aparecer completo
    margin = max(5.0, length * 0.05)
    cyl_length = length + 2 * margin
    l_center = (l_min + l_max) / 2.0

    if y_to_a:
        cyl_center = (l_center, 0.0, 0.0)
        cyl_direction = (1.0, 0.0, 0.0)
    else:
        cyl_center = (0.0, l_center, 0.0)
        cyl_direction = (0.0, 1.0, 0.0)

    cylinder_params = {
        "center": cyl_center,
        "direction": cyl_direction,
        "radius": radius,
        "height": cyl_length,
        "length_min": l_min,
        "length_max": l_max,
        "axis": "X" if y_to_a else "Y"
    }

    return {
        "g1_lines": g1_lines,
        "g0_lines": g0_lines,
        "cylinder": cylinder_params,
        "config": {
            "diameter_mm": diameter_mm,
            "y_to_a": y_to_a,
            "a_offset": a_offset,
            "zero_at_surface": zero_at_surface,
        },
    }
