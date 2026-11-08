"""
surface_map.py — Mapeamento de superfície e compensação automática de Z.

Fluxo:
1. Carregar heightmap (grid de pontos X,Y,Z medidos por probing)
2. Interpolação bilinear via SciPy para qualquer ponto XY
3. Ajustar Z de cada linha G0/G1 do G-Code original

Formato CSV esperado para o heightmap:
    X,Y,Z
    0.0,0.0,-0.12
    10.0,0.0,0.05
    ...
"""

import csv
import copy
import math
import re
from typing import List, Tuple, Optional
import numpy as np
from scipy.interpolate import RectBivariateSpline, griddata
from core.gcode_parser import GCodeBlock


# ---------------------------------------------------------------------------
# HeightMap — carrega e interpola o mapa de altura
# ---------------------------------------------------------------------------

class HeightMap:
    """
    Armazena e interpola um mapa de alturas (heightmap) obtido por probing.

    Suporta dois modos:
    - Grid regular (RectBivariateSpline) — mais rápido e preciso
    - Pontos irregulares (griddata) — mais flexível
    """

    def __init__(self):
        self.points_x: np.ndarray = np.array([])
        self.points_y: np.ndarray = np.array([])
        self.points_z: np.ndarray = np.array([])
        self._interpolator = None
        self._is_regular_grid = False

    # ------------------------------------------------------------------
    # Carregamento
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, filepath: str) -> 'HeightMap':
        """
        Carrega um heightmap de um arquivo de pontos (CSV, TXT, DAT, etc.).
        Suporta:
            - Delimitadores: vírgula, ponto-e-vírgula, tabulações ou espaços
            - Formatos: X Y Z, X,Y,Z ou X10.0 Y20.0 Z-0.1
            - Ignora comentários e linhas de cabeçalho
        """
        hm = cls()
        xs, ys, zs = [], [], []

        coord_re = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')

        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith((';', '(', '#', '//')):
                    # Comentário ou cabeçalho textual
                    continue
                # Obs.: não descartar linhas que começam com X/x — o formato
                # "X10.0 Y20.0 Z-0.1" é aceito e é dado válido, não cabeçalho.

                # Remover comentários entre parênteses ou após ;
                line = re.sub(r'\([^)]*\)', '', line)
                if ';' in line:
                    line = line.split(';')[0]

                # Se houver rótulos X/Y/Z, remover as letras para isolar números
                clean = re.sub(r'[XxYyZz=,;]', ' ', line)
                nums = coord_re.findall(clean)
                if len(nums) >= 3:
                    try:
                        xs.append(float(nums[0]))
                        ys.append(float(nums[1]))
                        zs.append(float(nums[2]))
                    except ValueError:
                        continue

        hm.points_x = np.array(xs)
        hm.points_y = np.array(ys)
        hm.points_z = np.array(zs)
        hm._build_interpolator()
        return hm

    @classmethod
    def from_csv(cls, filepath: str) -> 'HeightMap':
        """Alias para from_file."""
        return cls.from_file(filepath)

    @classmethod
    def from_points(cls, points: List[Tuple[float, float, float]]) -> 'HeightMap':
        """Cria um HeightMap a partir de lista de tuplas (x, y, z)."""
        hm = cls()
        arr = np.array(points, dtype=float)
        if arr.size == 0:
            hm.points_x = np.array([])
            hm.points_y = np.array([])
            hm.points_z = np.array([])
            return hm
        hm.points_x = arr[:, 0]
        hm.points_y = arr[:, 1]
        hm.points_z = arr[:, 2]
        hm._build_interpolator()
        return hm

    def update_point_z(self, index: int, new_z: float):
        """Atualiza a cota Z de um ponto pelo índice e reconstrói o interpolador."""
        if 0 <= index < len(self.points_z):
            self.points_z[index] = new_z
            self._build_interpolator()

    def save_to_file(self, filepath: str, format_type: str = "mach3"):
        """
        Salva os pontos de probe no disco.
        format_type: "mach3" (X Y Z separados por espaço) ou "csv" (delimitado por vírgula).
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            if format_type.lower() == "csv":
                f.write("X,Y,Z\n")
                for x, y, z in zip(self.points_x, self.points_y, self.points_z):
                    f.write(f"{x:.4f},{y:.4f},{z:.4f}\n")
            else:
                f.write("; Pontos de Probe — GCode Tools\n")
                for x, y, z in zip(self.points_x, self.points_y, self.points_z):
                    f.write(f"{x:.4f} {y:.4f} {z:.4f}\n")

    # ------------------------------------------------------------------
    # Build do interpolador
    # ------------------------------------------------------------------

    def _build_interpolator(self):
        """Detecta se os pontos formam grid regular e constrói o interpolador."""
        self._is_regular_grid = False
        if len(self.points_x) < 4:
            self._interpolator = None
            return

        unique_x = np.unique(self.points_x)
        unique_y = np.unique(self.points_y)

        # Verificar se é grid regular: total de pontos == nx * ny
        if len(unique_x) * len(unique_y) == len(self.points_x):
            try:
                # Reorganizar em grid 2D ordenado
                z_grid = np.zeros((len(unique_y), len(unique_x)))
                for xi, x in enumerate(unique_x):
                    for yi, y in enumerate(unique_y):
                        mask = (np.isclose(self.points_x, x) &
                                np.isclose(self.points_y, y))
                        if mask.any():
                            z_grid[yi, xi] = self.points_z[mask][0]

                self._interpolator = RectBivariateSpline(
                    unique_y, unique_x, z_grid, kx=1, ky=1
                )
                self._is_regular_grid = True
                return
            except Exception:
                pass

        # Grid irregular: usar griddata
        self._is_regular_grid = False
        self._interpolator = None  # griddata é chamado on-demand

    # ------------------------------------------------------------------
    # Interpolação
    # ------------------------------------------------------------------

    def get_z_offset(self, x: float, y: float) -> float:
        """
        Retorna o offset de Z para o ponto (x, y) por interpolação.

        Returns:
            Valor de Z compensado. Retorna 0.0 se não houver dados suficientes.
        """
        if len(self.points_x) == 0:
            return 0.0

        if self._is_regular_grid and self._interpolator is not None:
            try:
                # Não extrapolar para fora da área sondada: limita à borda do
                # mapa (extrapolação linear pode gerar compensações perigosas).
                x = float(np.clip(x, self.points_x.min(), self.points_x.max()))
                y = float(np.clip(y, self.points_y.min(), self.points_y.max()))

                # RectBivariateSpline retorna array 2D (1, 1). No NumPy 2.x
                # float(array) não é mais permitido, por isso usamos .item().
                return float(self._interpolator(y, x).item())
            except Exception:
                return 0.0

        # Fallback: griddata com interpolação linear
        try:
            pts = np.column_stack([self.points_x, self.points_y])
            result = griddata(pts, self.points_z, (x, y), method='linear')
            if np.isnan(result):
                # Fora do convex hull: usar nearest
                result = griddata(pts, self.points_z, (x, y), method='nearest')
            return float(result)
        except Exception:
            return 0.0

    def is_valid(self) -> bool:
        """Retorna True se o heightmap tem pontos suficientes para interpolação."""
        return len(self.points_x) >= 3

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        """Retorna (x_min, x_max, y_min, y_max) dos pontos do heightmap."""
        if len(self.points_x) == 0:
            return (0.0, 0.0, 0.0, 0.0)
        return (float(self.points_x.min()), float(self.points_x.max()),
                float(self.points_y.min()), float(self.points_y.max()))

    def as_grid_arrays(self):
        """Retorna (X, Y, Z) como arrays 2D para visualização (matplotlib)."""
        if not self.is_valid():
            return None, None, None
        unique_x = np.unique(self.points_x)
        unique_y = np.unique(self.points_y)
        XI, YI = np.meshgrid(unique_x, unique_y)
        pts = np.column_stack([self.points_x, self.points_y])
        ZI = griddata(pts, self.points_z, (XI, YI), method='linear')
        return XI, YI, ZI


# ---------------------------------------------------------------------------
# Aplicar mapeamento ao G-Code
# ---------------------------------------------------------------------------

def apply_surface_map(blocks: List[GCodeBlock],
                      heightmap: HeightMap,
                      feed_rate: Optional[float] = None) -> List[GCodeBlock]:
    """
    Ajusta os valores de Z de cada bloco de movimento com base no heightmap.

    Z_novo = Z_original + offset_interpolado(X, Y)

    Args:
        blocks: Lista de GCodeBlocks originais.
        heightmap: HeightMap com os dados de probing.
        feed_rate: Se fornecido, força este feed rate nos movimentos ajustados.
                   None = mantém o feed original.

    Returns:
        Nova lista de GCodeBlocks com Z compensado.
    """
    if not heightmap.is_valid():
        raise ValueError("HeightMap inválido ou sem pontos suficientes.")

    result = copy.deepcopy(blocks)
    cur_x, cur_y = 0.0, 0.0     # posição modal XY original
    cur_z = 0.0                 # Z modal ORIGINAL (não compensado)
    applied_z = 0.0             # Z modal já compensado (o que a máquina vê)

    for b in result:
        if not b.is_move:
            continue

        # Linhas de setup como "N6 G00 G21 G17 G90 G40 G49 G80" contêm G0
        # apenas como modo modal e não têm nenhum eixo. Não representam um
        # deslocamento real, então não devem receber Z compensado nem
        # alterar a posição modal (isso injetava um Z errado no cabeçalho).
        if b.x is None and b.y is None and b.z is None:
            continue

        # Posição efetiva (coordenadas modais propagadas)
        px = b.x if b.x is not None else cur_x
        py = b.y if b.y is not None else cur_y
        pz = b.z if b.z is not None else cur_z

        # Calcular offset para a posição XY real do movimento
        z_offset = heightmap.get_z_offset(px, py)
        new_z = round(pz + z_offset, 4)

        # Z é modal. Se a linha não traz Z explícito, o valor efetivo é o
        # anterior; só precisamos gravar um novo Z quando a compensação
        # realmente altera a altura naquele ponto. Isso corrige o caso mais
        # comum (G1 X.. Y.. sem Z repetido) sem inflar o arquivo à toa.
        if b.z is not None or abs(new_z - applied_z) > 1e-6:
            b.z = new_z

        # Forçar feed rate se solicitado
        if feed_rate is not None and b.f is not None:
            b.f = feed_rate

        cur_x, cur_y = px, py
        cur_z = pz
        applied_z = new_z

    return result


# ---------------------------------------------------------------------------
# Gerador de G-Code de probing
# ---------------------------------------------------------------------------

def generate_probe_gcode(x_min: float, x_max: float,
                         y_min: float, y_max: float,
                         nx: int, ny: int,
                         safe_z: float = 5.0,
                         probe_z: float = -5.0,
                         feed_probe: float = 50.0,
                         feed_travel: float = 1000.0,
                         controller: str = "mach3",
                         pattern: str = "raster") -> str:
    """
    Gera o G-Code de probing para um grid nx×ny dentro da área dada.

    Suporta:
        - "mach3": Formato idêntico ao G-Code Ripper (G31, M40/M41, #499) para Mach3/LinuxCNC
        - "grbl": Formato com G38.2 para GRBL / Candle / CNC Shield

    Args:
        x_min, x_max: Limites do eixo X da área de probing.
        y_min, y_max: Limites do eixo Y da área de probing.
        nx, ny: Número de pontos no grid em X e Y.
        safe_z: Altura de deslocamento seguro (mm).
        probe_z: Profundidade máxima de probing (mm, negativo).
        feed_probe: Velocidade de probing (mm/min).
        feed_travel: Velocidade de deslocamento (mm/min).
        controller: "mach3" ou "grbl".
        pattern: "raster" (unidirecional) ou "serpentine" (zig-zag).

    Returns:
        String com G-Code de probing completo.
    """
    xs = np.linspace(x_min, x_max, nx)
    ys = np.linspace(y_min, y_max, ny)

    lines = []

    if controller.lower().startswith("mach"):
        # Formato G-Code Ripper / Mach3 com M40 e M41
        lines.append("( G-Code Probing Routine — GCode Tools )")
        lines.append("( Format: Mach3 / LinuxCNC — G-Code Ripper style )")
        lines.append("G21   (set units to mm)")
        lines.append("G90")
        lines.append("(G Code)")
        lines.append("M40")
        lines.append(f"G0 Z{safe_z:.3f}")
        lines.append(f"#499 = {safe_z:.3f}")

        last_x = x_min
        last_y = y_min

        for yi, y in enumerate(ys):
            row_xs = xs if (pattern == "raster" or yi % 2 == 0) else xs[::-1]
            for x in row_xs:
                lines.append(f"G0 X{x:.3f}Y{y:.3f}")
                lines.append(f"G31 Z{probe_z:.3f} F{feed_probe:.1f}")
                lines.append(f"G0 Z{safe_z:.3f}")
                last_x, last_y = x, y

        lines.append(f"G0 Z{safe_z:.3f}")
        lines.append(f"G0 X{last_x:.3f}Y{last_y:.3f}")
        lines.append("M41")
        lines.append("(G Code)")
        lines.append("(G-Code Postamble)")
        lines.append("M2")

    else:
        # Formato GRBL / Candle
        lines.append("; === GCode Tools — Probing Routine (GRBL) ===")
        lines.append(f"; Grid: {nx}x{ny}  |  Área: X[{x_min:.3f},{x_max:.3f}] Y[{y_min:.3f},{y_max:.3f}]")
        lines.append("G90 (modo absoluto)")
        lines.append("G21 (unidades mm)")
        lines.append(f"G0 Z{safe_z:.3f} F{feed_travel:.0f} (subir para Z seguro)")
        lines.append("")

        for yi, y in enumerate(ys):
            row_xs = xs if (pattern == "raster" or yi % 2 == 0) else xs[::-1]
            for x in row_xs:
                lines.append(f"G0 X{x:.3f} Y{y:.3f} F{feed_travel:.0f}")
                lines.append(f"G38.2 Z{probe_z:.3f} F{feed_probe:.1f}")
                lines.append(f"G0 Z{safe_z:.3f}")

        lines.append("")
        lines.append("; === Fim do Probing ===")
        lines.append(f"G0 X{x_min:.3f} Y{y_min:.3f}")

    return "\n".join(lines)
