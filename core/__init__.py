"""
core — Módulos fundamentais de processamento de G-Code.
"""

from core.gcode_parser import GCodeBlock, parse_line, parse_file, write_file, get_bounding_box, get_bounding_box_3d, get_z_range, get_path_points
from core.surface_map import HeightMap, apply_surface_map, generate_probe_gcode
from core.rotary_wrap import (
    wrap_to_rotary,
    estimate_cylinder_dimensions,
    extract_rotary_trajectories_3d,
    calculate_feed_for_rotary,
    rotary_config_from_blocks,
    resolve_rotary_config,
    rotary_point_3d,
    rotary_workpiece_matrix,
    has_rotary_axis,
)
from core.transforms import scale, translate, rotate, mirror_x, mirror_y
from core.splitter import split_by_lines, split_by_tool_change, split_by_layer, save_parts
from core.arc_converter import arc_to_lines
from core.statistics import analyze_gcode, format_duration
from core.optimizer import optimize_gcode

__all__ = [
    "GCodeBlock",
    "parse_line",
    "parse_file",
    "write_file",
    "get_bounding_box",
    "get_bounding_box_3d",
    "get_z_range",
    "get_path_points",
    "HeightMap",
    "apply_surface_map",
    "generate_probe_gcode",
    "wrap_to_rotary",
    "estimate_cylinder_dimensions",
    "extract_rotary_trajectories_3d",
    "calculate_feed_for_rotary",
    "rotary_config_from_blocks",
    "resolve_rotary_config",
    "rotary_point_3d",
    "rotary_workpiece_matrix",
    "has_rotary_axis",
    "scale",
    "translate",
    "rotate",
    "mirror_x",
    "mirror_y",
    "split_by_lines",
    "split_by_tool_change",
    "split_by_layer",
    "save_parts",
    "arc_to_lines",
    "analyze_gcode",
    "format_duration",
    "optimize_gcode",
]
