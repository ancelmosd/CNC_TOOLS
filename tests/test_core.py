"""
Testes de regressão do núcleo do GCode Tools.

Execute na raiz do projeto:
    python -m unittest discover -s tests -v
"""

import math
import os
import re
import tempfile
import unittest

from core.gcode_parser import (
    parse_line, parse_file, write_file, get_bounding_box, get_bounding_box_3d,
)
from core.surface_map import HeightMap, apply_surface_map, generate_probe_gcode
from core.splitter import split_by_layer
from core.transforms import rotate, translate, scale, mirror_x
from core.rotary_wrap import (
    wrap_to_rotary,
    estimate_cylinder_dimensions,
    extract_rotary_trajectories_3d,
    rotary_point_3d,
    rotary_workpiece_matrix,
)
from core.arc_converter import arc_to_lines
from core.statistics import analyze_gcode, format_duration


class TestParserRoundTrip(unittest.TestCase):
    """Linhas não modificadas devem ser preservadas exatamente."""

    def test_preserves_multiple_g_codes(self):
        raw = "G17 G21 G90"
        self.assertEqual(parse_line(raw).to_gcode(), raw)

    def test_preserves_tool_change(self):
        raw = "T1 M6"
        self.assertEqual(parse_line(raw).to_gcode(), raw)

    def test_preserves_secondary_m_code(self):
        raw = "G1 X10 Y20 M3 S1000"
        self.assertEqual(parse_line(raw).to_gcode(), raw)

    def test_preserves_comments_and_line_number(self):
        raw = "N10 G1 X1.50 F100 ; acabamento"
        self.assertEqual(parse_line(raw).to_gcode(), raw)

    def test_preserves_unknown_lines(self):
        for raw in ("%", "", "somente texto"):
            self.assertEqual(parse_line(raw).to_gcode(), raw)

    def test_modified_line_keeps_other_words(self):
        block = parse_line("G17 G1 X10 Y20 M3")
        block.x = 15.0
        self.assertEqual(block.to_gcode(), "G17 G1 X15 Y20 M3")

    def test_file_round_trip(self):
        content = [
            "G17 G21 G90",
            "T1 M6",
            "G0 Z5.0",
            "G1 X10 Y20 M3 S1000 (corte)",
            "M5",
        ]
        fd, path = tempfile.mkstemp(suffix=".gcode")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(content) + "\n")
            write_file(parse_file(path), path)
            with open(path, "r", encoding="utf-8") as f:
                result = [line.rstrip("\n") for line in f]
            self.assertEqual(result, content)
        finally:
            os.remove(path)


class TestBoundingBox(unittest.TestCase):
    def test_modal_coordinates(self):
        blocks = [parse_line("G1 X10 Y0"), parse_line("G1 Y10")]
        self.assertEqual(get_bounding_box(blocks), (10.0, 10.0, 0.0, 10.0))

    def test_modal_coordinates_3d(self):
        blocks = [parse_line("G1 Z-1"), parse_line("G1 X10"), parse_line("G1 Z-2")]
        self.assertEqual(
            get_bounding_box_3d(blocks),
            (0.0, 10.0, 0.0, 0.0, -2.0, -1.0),
        )


class TestHeightMap(unittest.TestCase):
    def _write(self, text: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_reads_labeled_xyz_lines(self):
        path = self._write(
            "X,Y,Z\n"
            "X10.0 Y10.0 Z-0.1\n"
            "X20.0 Y10.0 Z0.2\n"
            "X10.0 Y20.0 Z0.0\n"
            "X20.0 Y20.0 Z0.1\n"
        )
        hm = HeightMap.from_file(path)
        self.assertEqual(len(hm.points_x), 4)
        self.assertTrue(hm.is_valid())

    def test_reads_csv_header(self):
        path = self._write("X,Y,Z\n10,10,-0.1\n20,10,0.2\n10,20,0.0\n20,20,0.1\n")
        hm = HeightMap.from_file(path)
        self.assertEqual(len(hm.points_x), 4)

    def test_outside_bounds_clamps_to_edge(self):
        hm = HeightMap.from_points([
            (10, 10, -0.1), (20, 10, 0.2),
            (10, 20, 0.0), (20, 20, 0.1),
        ])
        self.assertAlmostEqual(hm.get_z_offset(-100, -100), -0.1, places=6)
        self.assertAlmostEqual(hm.get_z_offset(100, 100), 0.1, places=6)

    def test_empty_heightmap_is_invalid(self):
        hm = HeightMap.from_points([])
        self.assertFalse(hm.is_valid())
        self.assertEqual(hm.get_z_offset(0, 0), 0.0)

    def test_regular_grid_interpolates_midpoint(self):
        hm = HeightMap.from_points([
            (10, 10, -0.1), (20, 10, 0.2),
            (10, 20, 0.0), (20, 20, 0.1),
        ])
        self.assertEqual(hm._is_regular_grid, True)
        self.assertAlmostEqual(hm.get_z_offset(15, 15), 0.05, places=6)

    def test_remove_points_ignores_invalid_and_duplicate_indices(self):
        hm = HeightMap.from_points([
            (0, 0, 0.1), (10, 0, 0.2),
            (0, 10, 0.3), (10, 10, 0.4),
        ])
        # 1 e 3 são válidos; 3 repetido e 99/-1 devem ser ignorados.
        removed = hm.remove_points([1, 3, 3, 99, -1])
        self.assertEqual(removed, 2)
        self.assertEqual(hm.points_x.tolist(), [0.0, 0.0])
        self.assertEqual(hm.points_y.tolist(), [0.0, 10.0])
        self.assertEqual(hm.points_z.tolist(), [0.1, 0.3])
        self.assertFalse(hm.is_valid())

    def test_remove_point_rebuilds_interpolator(self):
        hm = HeightMap.from_points([
            (0, 0, 0.0), (10, 0, 1.0),
            (0, 10, 2.0), (10, 10, 3.0),
        ])
        self.assertTrue(hm._is_regular_grid)

        hm.remove_points([3])
        self.assertEqual(len(hm.points_x), 3)
        self.assertFalse(hm._is_regular_grid)
        # Plano z = 0.1x + 0.2y permanece válido com os 3 pontos restantes.
        self.assertAlmostEqual(hm.get_z_offset(2, 2), 0.6, places=6)


class TestSurfaceMap(unittest.TestCase):
    def test_compensates_modal_z_moves(self):
        # Plano inclinado: offset = x / 10
        hm = HeightMap.from_points([
            (x, y, x / 10.0) for x in (0, 10, 20) for y in (0, 10)
        ])
        blocks = [
            parse_line("G1 Z-1 F100"),
            parse_line("G1 X10"),
            parse_line("G1 X20"),
        ]
        result = apply_surface_map(blocks, hm)

        # Z original é modal (-1). O offset deve ser somado UMA vez por ponto.
        self.assertEqual(result[0].z, -1.0)   # offset 0
        self.assertEqual(result[1].z, 0.0)    # -1 + 1
        self.assertEqual(result[2].z, 1.0)    # -1 + 2

    def test_does_not_inject_redundant_z(self):
        hm = HeightMap.from_points([
            (0, 0, 0.0), (10, 0, 0.0), (0, 10, 0.0), (10, 10, 0.0),
        ])
        blocks = [parse_line("G1 Z-1"), parse_line("G1 X5")]
        result = apply_surface_map(blocks, hm)
        self.assertIsNone(result[1].z)
        self.assertEqual(result[1].to_gcode(), "G1 X5")

    def test_does_not_inject_z_into_setup_line(self):
        # Cabeçalho típico de CAM: G0 é apenas modal, não há eixos.
        hm = HeightMap.from_points([
            (0, 0, 0.1997), (10, 0, 0.1), (0, 10, 0.2), (10, 10, 0.3),
        ])
        header = "N6 G00 G21 G17 G90 G40 G49 G80"
        blocks = [
            parse_line(header),
            parse_line("G0 X0 Y0 Z5"),
            parse_line("G1 Z-1 F100"),
            parse_line("G1 X10 Y10"),
        ]
        result = apply_surface_map(blocks, hm)

        self.assertIsNone(result[0].z)
        self.assertEqual(result[0].to_gcode(), header)
        # Movimentos reais continuam sendo compensados normalmente.
        self.assertAlmostEqual(result[1].z, 5.1997, places=4)
        self.assertAlmostEqual(result[2].z, -0.8003, places=4)

    def test_generate_probe_raster_point_count(self):
        gcode = generate_probe_gcode(
            -50, 50, -30, 30, nx=8, ny=5,
            controller="mach3", pattern="raster",
        )
        # 8x5 pontos + retorno final ao último ponto.
        coords = re.findall(r"G0 X(-?\d+\.?\d*)Y(-?\d+\.?\d*)", gcode)
        self.assertEqual(len(coords), 8 * 5 + 1)
        self.assertEqual(gcode.count("G31"), 8 * 5)

    def test_generate_probe_circular_stays_within_bounds(self):
        gcode = generate_probe_gcode(
            -50, 50, -30, 30, nx=8, ny=5,
            controller="mach3", pattern="circular",
        )
        coords = re.findall(r"G0 X(-?\d+\.?\d*)Y(-?\d+\.?\d*)", gcode)
        # Centro + anéis + retorno final.
        self.assertGreater(len(coords), 10)
        self.assertGreater(gcode.count("G31"), 8)

        for xs, ys in coords:
            x, y = float(xs), float(ys)
            self.assertGreaterEqual(x, -50.0001)
            self.assertLessEqual(x, 50.0001)
            self.assertGreaterEqual(y, -30.0001)
            self.assertLessEqual(y, 30.0001)

        # O centro da área deve estar entre os pontos sondados.
        self.assertTrue(any(abs(float(xs)) < 1e-6 and abs(float(ys)) < 1e-6
                            for xs, ys in coords))

    def test_generate_probe_circular_grbl(self):
        gcode = generate_probe_gcode(
            -50, 50, -50, 50, nx=8, ny=5,
            controller="grbl", pattern="circular",
        )
        self.assertIn("G38.2", gcode)
        self.assertGreater(gcode.count("G38.2"), 8)
        self.assertIn("Padrão: circular", gcode)

    def test_generate_probe_uses_explicit_points(self):
        points = [(0, 0), (10, 5), (20, -5)]
        gcode = generate_probe_gcode(
            -50, 50, -30, 30, nx=8, ny=5,
            controller="mach3", pattern="circular", points=points,
        )
        coords = re.findall(r"G0 X(-?\d+\.?\d*)Y(-?\d+\.?\d*)", gcode)
        # 3 pontos + retorno final ao último ponto.
        self.assertEqual(len(coords), 4)
        self.assertEqual(gcode.count("G31"), 3)
        self.assertEqual(coords[:3], [
            ("0.000", "0.000"), ("10.000", "5.000"), ("20.000", "-5.000"),
        ])

    def test_generate_probe_rejects_empty_explicit_points(self):
        with self.assertRaises(ValueError):
            generate_probe_gcode(
                -50, 50, -30, 30, nx=8, ny=5, points=[],
            )


class TestSplitter(unittest.TestCase):
    def test_layer_split_keeps_modal_moves(self):
        blocks = [
            parse_line("G1 Z-1"), parse_line("G1 X10"), parse_line("G1 Y10"),
            parse_line("G1 Z-2"), parse_line("G1 X20"),
        ]
        layers = split_by_layer(blocks)
        self.assertEqual([z for z, _ in layers], [-1.0, -2.0])
        self.assertEqual(len(layers[0][1]), 3)
        self.assertEqual(len(layers[1][1]), 2)


class TestTransforms(unittest.TestCase):
    def test_rotate_uses_modal_y(self):
        result = rotate([
            parse_line("G1 X10 Y0"),
            parse_line("G1 X10"),   # Y modal = 0
        ], 90.0, 0.0, 0.0)
        self.assertEqual(result[1].to_gcode(), "G1 X0 Y10")

    def test_rotate_arc_offsets_when_j_absent(self):
        result = rotate([parse_line("G3 X10 Y0 I5")], 90.0, 0.0, 0.0)
        # I=5, J=0 girado 90° → I=0, J=5
        self.assertAlmostEqual(result[0].i, 0.0)
        self.assertAlmostEqual(result[0].j, 5.0)

    def test_negative_scale_flips_arc_direction(self):
        result = scale([parse_line("G3 X10 Y0 I5 J0")], -1.0, 1.0, 1.0)
        self.assertEqual(result[0].command, "G2")
        self.assertEqual(result[0].i, -5.0)

    def test_identity_operations_do_not_rewrite_lines(self):
        blocks = [parse_line("G17 G1 X10 Y20 M3")]
        self.assertEqual(scale(blocks)[0].to_gcode(), "G17 G1 X10 Y20 M3")
        self.assertEqual(translate(blocks)[0].to_gcode(), "G17 G1 X10 Y20 M3")
        self.assertEqual(mirror_x(blocks)[0].to_gcode(), "G17 G1 X-10 Y20 M3")


class TestRotary(unittest.TestCase):
    def test_arcs_are_converted_before_wrapping(self):
        blocks = [parse_line("G0 X0 Y0"), parse_line("G3 X10 Y0 I5 J0 F100")]
        result = wrap_to_rotary(blocks, diameter_mm=20.0)
        self.assertFalse(any(b.command in ("G2", "G02", "G3", "G03") for b in result))
        self.assertGreater(len(result), 2)

    def test_y_is_replaced_by_a(self):
        result = wrap_to_rotary([parse_line("G1 X5 Y10")], diameter_mm=20.0)
        block = result[0]
        self.assertIsNone(block.y)
        self.assertAlmostEqual(block.a, (10.0 / (3.141592653589793 * 20.0)) * 360.0, places=4)

    def test_trajectory_returns_cylinder_data(self):
        data = extract_rotary_trajectories_3d(
            [parse_line("G1 X0 Y0 Z0"), parse_line("G1 X10 Y10 Z-1")],
            diameter_mm=20.0,
        )
        self.assertIn("cylinder", data)
        self.assertGreater(len(data["g1_lines"]), 0)

    def test_estimate_diameter_uses_y_travel_for_y_to_a(self):
        circumference = math.pi * 20.0
        blocks = [
            parse_line("G0 X0 Y0"),
            parse_line(f"G1 X40 Y0"),
            parse_line(f"G1 X40 Y{circumference}"),
        ]
        info = estimate_cylinder_dimensions(blocks, y_to_a=True)

        # Cilindro ao longo de X: comprimento = X; Y vira A.
        self.assertAlmostEqual(info["axis_length"], 40.0, places=3)
        self.assertAlmostEqual(info["wrap_travel"], circumference, places=3)
        self.assertAlmostEqual(info["suggested_diameter"], 20.0, places=3)

    def test_estimate_diameter_uses_x_travel_for_x_to_a(self):
        circumference = math.pi * 20.0
        blocks = [
            parse_line("G0 X0 Y0"),
            parse_line(f"G1 X{circumference} Y0"),
            parse_line(f"G1 X{circumference} Y40"),
        ]
        info = estimate_cylinder_dimensions(blocks, y_to_a=False)

        # Cilindro ao longo de Y: comprimento = Y; X vira A.
        self.assertAlmostEqual(info["axis_length"], 40.0, places=3)
        self.assertAlmostEqual(info["wrap_travel"], circumference, places=3)
        self.assertAlmostEqual(info["suggested_diameter"], 20.0, places=3)

    def test_x_to_a_wrap_fits_in_one_turn(self):
        # Com diâmetro estimado pelo X, o X completo deve mapear em 360°.
        circumference = math.pi * 20.0
        blocks = [
            parse_line("G0 X0 Y0"),
            parse_line(f"G1 X0 Y0"),
            parse_line(f"G1 X{circumference} Y40"),
        ]
        info = estimate_cylinder_dimensions(blocks, y_to_a=False)
        wrapped = wrap_to_rotary(blocks, diameter_mm=info["suggested_diameter"],
                                 y_to_a=False)
        a_values = [b.a for b in wrapped if b.a is not None]
        self.assertAlmostEqual(max(a_values) - min(a_values), 360.0, places=2)

    def test_zero_at_surface_adjusts_z(self):
        # Para diâmetro 50mm, raio = 25mm.
        # Com zero_at_surface=False, Z=-2mm na superfície vira Z=23mm do centro.
        result = wrap_to_rotary(
            [parse_line("G1 X0 Y10 Z-2.0")],
            diameter_mm=50.0,
            zero_at_surface=False
        )
        self.assertAlmostEqual(result[0].z, 23.0, places=3)

    def test_wrap_stores_rotary_metadata(self):
        result = wrap_to_rotary([parse_line("G1 X0 Y10")], diameter_mm=20.0)
        self.assertIsNotNone(result[0].rotary)
        self.assertEqual(result[0].rotary["diameter_mm"], 20.0)

    def test_modal_a_is_preserved_after_wrap(self):
        # Meia volta (A=180) e depois um movimento só de Z/X sem A explícito.
        circumference = math.pi * 20.0
        blocks = [
            parse_line("G0 X0 Y0 Z5"),
            parse_line("G1 Z-1 F100"),
            parse_line(f"G1 X40 Y{circumference / 2.0}"),
            parse_line("G1 Z-2"),
            parse_line("G1 X0"),
        ]
        wrapped = wrap_to_rotary(blocks, diameter_mm=20.0)
        data = extract_rotary_trajectories_3d(wrapped, diameter_mm=20.0)

        # O último segmento precisa continuar em A=180 (y≈0, z negativo),
        # e não voltar para A=0 (z positivo).
        last_p1, last_p2 = data["g1_lines"][-1]
        self.assertAlmostEqual(last_p1[1], 0.0, places=6)
        self.assertAlmostEqual(last_p2[1], 0.0, places=6)
        self.assertLess(last_p1[2], 0.0)
        self.assertLess(last_p2[2], 0.0)

    def test_rotary_sim_points_follow_wrapped_path(self):
        circumference = math.pi * 20.0
        blocks = [
            parse_line("G0 X0 Y0 Z5"),
            parse_line("G1 Z-1 F100"),
            parse_line("G1 X40 Y0"),
            parse_line(f"G1 X40 Y{circumference}"),
            parse_line("G1 Z-2"),
            parse_line("G1 X0"),
        ]
        wrapped = wrap_to_rotary(blocks, diameter_mm=20.0)
        data = analyze_gcode(wrapped)

        self.assertIsNotNone(data["rotary_config"])
        self.assertEqual(len(data["sim_points"]), len(data["sim_rotary"]))

        radius = 10.0
        max_angular_jump = 0.0
        for p, m in zip(data["sim_points"], data["sim_rotary"]):
            self.assertIsNotNone(m)
            mx, my, ma, mz = m
            # Ponto 3D deve estar no raio efetivo (raio + Z de superfície).
            r3d = math.hypot(p[1], p[2])
            self.assertAlmostEqual(r3d, radius + mz, places=5)

        for (p1, m1), (p2, m2) in zip(
            zip(data["sim_points"], data["sim_rotary"]),
            zip(data["sim_points"][1:], data["sim_rotary"][1:]),
        ):
            if abs(m2[2] - m1[2]) > 1e-9:
                max_angular_jump = max(
                    max_angular_jump,
                    math.dist(p1[:3], p2[:3]),
                )
        # Movimentos angulares devem ser subdivididos, não "teleportar".
        self.assertLess(max_angular_jump, 1.0)

    def test_rotary_sim_preview_from_flat_blocks(self):
        # Sem aplicar o wrap: blocos planos + diâmetro informado.
        blocks = [
            parse_line("G0 X0 Y0 Z5"),
            parse_line("G1 Z-1 F100"),
            parse_line("G1 X0 Y%.4f" % (math.pi * 20.0)),
        ]
        data = analyze_gcode(blocks, rotary={"diameter_mm": 20.0})

        self.assertIsNotNone(data["rotary_config"])
        self.assertEqual(len(data["sim_points"]), len(data["sim_rotary"]))
        # A deve ser derivado de Y, e o raio deve ser 9mm (10 - 1).
        last_m = data["sim_rotary"][-1]
        self.assertAlmostEqual(last_m[2], 360.0, places=2)
        last_p = data["sim_points"][-1]
        self.assertAlmostEqual(math.hypot(last_p[1], last_p[2]), 9.0, places=5)

    def test_workpiece_matrix_keeps_contact_at_top(self):
        diameter = 20.0
        for z in (-1.0, 0.0, 2.0):
            for angle in (0.0, 45.0, 90.0, 180.0, 270.0, 360.0):
                for y_to_a in (True, False):
                    if y_to_a:
                        p = rotary_point_3d(40.0, 0.0, angle, z, diameter, True, False)
                        matrix = rotary_workpiece_matrix(40.0, 0.0, angle, True)
                    else:
                        p = rotary_point_3d(0.0, 40.0, angle, z, diameter, False, False)
                        matrix = rotary_workpiece_matrix(0.0, 40.0, angle, False)

                    q = [
                        sum(matrix[i][j] * p[j] for j in range(3)) + matrix[i][3]
                        for i in range(3)
                    ]
                    self.assertAlmostEqual(q[0], 0.0, places=6)
                    self.assertAlmostEqual(q[1], 0.0, places=6)
                    self.assertAlmostEqual(q[2], diameter / 2.0 + z, places=6)

    def test_zero_at_surface_false_keeps_center_radius(self):
        # Wrap com Z referenciado ao centro: Z=23mm → raio 23mm.
        blocks = [parse_line("G1 X0 Y10 Z-2.0")]
        wrapped = wrap_to_rotary(blocks, diameter_mm=50.0,
                                 zero_at_surface=False)
        data = analyze_gcode(wrapped)
        last_p = data["sim_points"][-1]
        last_m = data["sim_rotary"][-1]
        self.assertAlmostEqual(math.hypot(last_p[1], last_p[2]), 23.0, places=3)
        self.assertAlmostEqual(last_m[3], 23.0, places=3)


class TestArcConverter(unittest.TestCase):
    def test_full_circle_arc(self):
        # Círculo completo 360° em torno de (10, 0) com raio 10 (I=10, J=0)
        # Começa em (0, 0) e termina em (0, 0)
        blocks = [parse_line("G0 X0 Y0"), parse_line("G2 X0 Y0 I10 J0 F500")]
        lines = arc_to_lines(blocks, tolerance_mm=0.05)
        # Não pode ter ficado vazio ou 0 segmentos
        self.assertGreater(len(lines), 10)
        # Todos os segmentos devem ser G1
        for b in lines[1:]:
            self.assertEqual(b.command, "G1")


class TestStatistics(unittest.TestCase):
    def test_analyze_gcode_metrics(self):
        blocks = [
            parse_line("G0 X0 Y0 Z5"),
            parse_line("G1 Z-1 F200"),
            parse_line("G1 X100 Y0 F500 S12000 M3"),
            parse_line("G0 Z5"),
        ]
        data = analyze_gcode(blocks, default_rapid_feed=2000.0)
        self.assertEqual(data["total_lines"], 4)
        self.assertAlmostEqual(data["cut_distance"], 106.0, delta=1.0) # 6mm Z + 100mm X
        self.assertGreater(data["total_time_sec"], 0.0)
        self.assertEqual(data["max_spindle"], 12000.0)
        self.assertEqual(len(data["sim_points"]), 5) # ponto inicial (0,0,0) + 4 movimentos

    def test_format_duration(self):
        self.assertEqual(format_duration(45), "00m 45s")
        self.assertEqual(format_duration(125), "02m 05s")
        self.assertEqual(format_duration(3665), "1h 01m 05s")


if __name__ == "__main__":
    unittest.main()
