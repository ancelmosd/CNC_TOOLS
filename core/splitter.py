"""
splitter.py — Divide arquivos G-Code em partes menores.

Modos de divisão:
- Por número máximo de linhas
- Por troca de ferramenta (M6)
- Por camada / profundidade Z
"""

import copy
import os
from typing import List, Tuple
from core.gcode_parser import GCodeBlock


# ---------------------------------------------------------------------------
# Divisão por número de linhas
# ---------------------------------------------------------------------------

def split_by_lines(blocks: List[GCodeBlock],
                   max_lines: int) -> List[List[GCodeBlock]]:
    """
    Divide a lista de blocos em partes com no máximo max_lines linhas.

    Args:
        blocks: Lista completa de GCodeBlocks.
        max_lines: Número máximo de linhas por parte.

    Returns:
        Lista de partes, cada parte é uma lista de GCodeBlocks.
    """
    if max_lines <= 0:
        raise ValueError("max_lines deve ser maior que zero.")

    parts = []
    for i in range(0, len(blocks), max_lines):
        parts.append(blocks[i:i + max_lines])
    return parts


# ---------------------------------------------------------------------------
# Divisão por troca de ferramenta (M6)
# ---------------------------------------------------------------------------

def split_by_tool_change(blocks: List[GCodeBlock]) -> List[List[GCodeBlock]]:
    """
    Divide o G-Code a cada ocorrência de M6 (troca de ferramenta).
    Cada parte começa após um M6 (ou no início do arquivo).

    Args:
        blocks: Lista completa de GCodeBlocks.

    Returns:
        Lista de partes por ferramenta.
    """
    parts = []
    current = []

    for b in blocks:
        is_tool_change = b.command and b.command.upper() in ('M6', 'M06')

        if is_tool_change and current:
            # Inclui o M6 no final da parte atual
            current.append(copy.deepcopy(b))
            parts.append(current)
            current = []
        else:
            current.append(copy.deepcopy(b))

    if current:
        parts.append(current)

    return parts if parts else [blocks]


# ---------------------------------------------------------------------------
# Divisão por camada (profundidade Z)
# ---------------------------------------------------------------------------

def split_by_layer(blocks: List[GCodeBlock],
                   z_tolerance: float = 0.001) -> List[Tuple[float, List[GCodeBlock]]]:
    """
    Agrupa os blocos de G-Code por profundidade Z (camadas).

    Args:
        blocks: Lista completa de GCodeBlocks.
        z_tolerance: Tolerância para considerar dois valores Z iguais (mm).

    Returns:
        Lista de tuplas (z_value, blocos_da_camada) ordenadas por Z decrescente
        (do mais raso ao mais profundo).
    """
    layers = {}  # z_level → list of blocks
    cur_z = None

    def _layer_for(z_value: float) -> float:
        """Encontra (ou cria) a camada correspondente dentro da tolerância."""
        for z_key in layers:
            if abs(z_key - z_value) <= z_tolerance:
                return z_key
        new_key = round(z_value, 4)
        layers[new_key] = []
        return new_key

    for b in blocks:
        if b.is_move:
            # Z é modal: movimentos sem Z explícito pertencem à camada atual.
            if b.z is not None:
                cur_z = b.z
            z_key = b.z if b.z is not None else (cur_z if cur_z is not None else 0.0)
            layers[_layer_for(z_key)].append(copy.deepcopy(b))
        else:
            # Blocos não-movimento vão para a camada corrente ou a camada 0
            z_key = cur_z if cur_z is not None else 0.0
            layers[_layer_for(z_key)].append(copy.deepcopy(b))

    # Ordenar por Z decrescente (raso → profundo)
    sorted_layers = sorted(layers.items(), key=lambda x: x[0], reverse=True)
    return sorted_layers


# ---------------------------------------------------------------------------
# Utilitário: salvar partes em arquivos
# ---------------------------------------------------------------------------

def save_parts(parts: List[List[GCodeBlock]],
               base_path: str,
               prefix: str = "part") -> List[str]:
    """
    Salva cada parte como um arquivo separado.

    Args:
        parts: Lista de partes (cada uma é uma lista de GCodeBlocks).
        base_path: Diretório de destino.
        prefix: Prefixo do nome de arquivo (ex: "part" → "part_001.gcode").

    Returns:
        Lista dos caminhos de arquivo criados.
    """
    from core.gcode_parser import write_file
    os.makedirs(base_path, exist_ok=True)

    saved = []
    for i, part in enumerate(parts, start=1):
        filename = f"{prefix}_{i:03d}.gcode"
        filepath = os.path.join(base_path, filename)
        write_file(part, filepath)
        saved.append(filepath)

    return saved
