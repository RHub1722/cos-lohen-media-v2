from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from scipy.optimize import minimize_scalar


ROOT = Path(__file__).resolve().parent / "Lohen_Weapons" / "stl_tpu"
NAMES = [
    "spear_7_L.stl",
    "spear_7_R.stl",
    "spear_9_L.stl",
    "spear_9_R.stl",
    "spear_10_L.stl",
    "spear_10_R.stl",
]


def signed_volume(triangles: np.ndarray) -> float:
    """Oriented tetrahedron sum, in mm^3."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def edge_incidence(mesh: trimesh.Trimesh, decimals: int = 6) -> tuple[int, int, int]:
    """Counts boundary, manifold, and non-manifold undirected edges after weld."""
    vertices = np.round(mesh.vertices, decimals=decimals)
    _, inverse = np.unique(vertices, axis=0, return_inverse=True)
    faces = inverse[mesh.faces]
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges.sort(axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int((counts == 1).sum()), int((counts == 2).sum()), int((counts > 2).sum())


def unique_vertices(mesh: trimesh.Trimesh, decimals: int = 6) -> np.ndarray:
    return np.unique(np.round(mesh.vertices, decimals=decimals), axis=0)


def nearest_error(source: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    distance, _ = cKDTree(target).query(source, workers=-1)
    return float(np.sqrt(np.mean(distance**2))), float(distance.max())


def horizontal_section_area(mesh: trimesh.Trimesh, z_mm: float) -> float:
    """Area enclosed by all horizontal section loops, via shoelace."""
    section = mesh.section(plane_origin=[0.0, 0.0, z_mm], plane_normal=[0.0, 0.0, 1.0])
    if section is None:
        return 0.0
    total = 0.0
    for loop in section.discrete:
        points = np.asarray(loop)[:, :2]
        total += 0.5 * abs(
            np.dot(points[:-1, 0], points[1:, 1])
            - np.dot(points[:-1, 1], points[1:, 0])
        )
    return float(total)


def best_proper_rotation_error(left: np.ndarray, right: np.ndarray) -> dict:
    """Best set error over rotations allowed by distinct covariance eigenframes.

    Any exact rigid isometry between point sets maps covariance eigenvectors.
    With three distinct eigenvalues only the eight eigenvector sign choices remain.
    We retain determinant +1 candidates (proper rotations) and test point sets.
    """
    lp = left - left.mean(axis=0)
    rp = right - right.mean(axis=0)
    leval, levec = np.linalg.eigh(np.cov(lp, rowvar=False, bias=True))
    reval, revec = np.linalg.eigh(np.cov(rp, rowvar=False, bias=True))
    order_l = np.argsort(leval)[::-1]
    order_r = np.argsort(reval)[::-1]
    leval, levec = leval[order_l], levec[:, order_l]
    reval, revec = reval[order_r], revec[:, order_r]

    best = (math.inf, math.inf, None)
    for signs in itertools.product((-1.0, 1.0), repeat=3):
        rotation = levec @ np.diag(signs) @ revec.T
        if np.linalg.det(rotation) < 0.0:
            continue
        transformed = lp @ rotation + right.mean(axis=0)
        rms, maximum = nearest_error(transformed, right)
        if rms < best[0]:
            best = (rms, maximum, rotation)
    return {
        "rms_mm": best[0],
        "max_mm": best[1],
        "covariance_eigenvalues_L": leval.tolist(),
        "covariance_eigenvalues_R": reval.tolist(),
        "rotation_det": float(np.linalg.det(best[2])),
    }


def analyze(path: Path) -> tuple[trimesh.Trimesh, dict]:
    mesh = trimesh.load_mesh(path, force="mesh", process=False)
    welded = trimesh.load_mesh(path, force="mesh", process=True)
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    bounds = np.array((triangles.min(axis=(0, 1)), triangles.max(axis=(0, 1))))
    areas = trimesh.triangles.area(triangles)
    boundary, manifold, nonmanifold = edge_incidence(mesh)
    rounded = np.round(mesh.vertices, decimals=6)
    _, inverse = np.unique(rounded, axis=0, return_inverse=True)
    welded_faces = inverse[mesh.faces]
    unordered_faces = np.sort(welded_faces, axis=1)
    _, duplicate_counts = np.unique(unordered_faces, axis=0, return_counts=True)
    volume_signed = signed_volume(triangles)
    volume_abs = abs(volume_signed)
    surface = float(areas.sum())
    z_min = bounds[0, 2]
    at_bottom = np.isclose(triangles[:, :, 2], z_min, rtol=0.0, atol=1e-6)
    bottom_faces = np.all(at_bottom, axis=1)
    bottom_vertices = np.unique(
        np.round(triangles.reshape((-1, 3))[at_bottom.reshape(-1)], decimals=6), axis=0
    )
    result = {
        "file": path.name,
        "triangles": len(triangles),
        "bounds_min_mm": bounds[0].tolist(),
        "bounds_max_mm": bounds[1].tolist(),
        "size_mm": (bounds[1] - bounds[0]).tolist(),
        "bbox_center_mm": ((bounds[1] + bounds[0]) / 2.0).tolist(),
        "signed_volume_cm3": volume_signed / 1000.0,
        "trimesh_volume_cm3": float(mesh.volume) / 1000.0,
        "surface_area_cm2": surface / 100.0,
        "effective_slab_thickness_mm_2V_over_S": 2.0 * volume_abs / surface,
        "bottom_vertices_at_zmin": len(bottom_vertices),
        "bottom_coplanar_faces": int(bottom_faces.sum()),
        "bottom_coplanar_face_area_mm2": float(areas[bottom_faces].sum()),
        "horizontal_section_area_at_z_0.2_mm2": horizontal_section_area(welded, z_min + 0.2),
        "is_watertight_after_vertex_weld": bool(welded.is_watertight),
        "is_winding_consistent_after_vertex_weld": bool(welded.is_winding_consistent),
        "is_volume_after_vertex_weld": bool(welded.is_volume),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "manifold_edges": manifold,
        "duplicate_unoriented_face_groups": int((duplicate_counts > 1).sum()),
        "area_median_mm2": float(np.median(areas)),
        "area_min_mm2": float(areas.min()),
        "area_eq_0_mm2": int((areas == 0.0).sum()),
        "area_lt_1e-6_mm2": int((areas < 1e-6).sum()),
        "area_lt_1e-5_mm2": int((areas < 1e-5).sum()),
        "ten_smallest_areas_mm2": np.sort(areas)[:10].tolist(),
    }
    return mesh, result


def square_footprint(length: float, width: float) -> dict:
    if width > length:
        length, width = width, length
    diagonal = (length + width) / math.sqrt(2.0)
    best = min(length, diagonal)
    angle = 0.0 if length <= diagonal else 45.0
    return {
        "L_mm": length,
        "W_mm": width,
        "aspect_L_over_W": length / width,
        "straight_square_mm": length,
        "45deg_square_mm": diagonal,
        "optimal_angle_deg": angle,
        "minimum_square_mm": best,
        "fits_180": best <= 180.0,
        "fits_256": best <= 256.0,
    }


def actual_xy_footprint(mesh: trimesh.Trimesh) -> dict:
    """Minimum square enclosing the actual XY vertex set under rotation."""
    points = np.unique(np.round(mesh.vertices[:, :2], decimals=6), axis=0)

    def extents(theta: float) -> tuple[float, float]:
        cosine, sine = math.cos(theta), math.sin(theta)
        x = points[:, 0] * cosine - points[:, 1] * sine
        y = points[:, 0] * sine + points[:, 1] * cosine
        return float(np.ptp(x)), float(np.ptp(y))

    def objective(theta: float) -> float:
        return max(extents(theta))

    grid = np.linspace(0.0, math.pi / 2.0, 7201)
    values = np.array([objective(theta) for theta in grid])
    index = int(np.argmin(values))
    low = grid[max(0, index - 2)]
    high = grid[min(len(grid) - 1, index + 2)]
    optimum = minimize_scalar(
        objective, bounds=(low, high), method="bounded", options={"xatol": 1e-13}
    )
    width, height = extents(float(optimum.x))
    return {
        "optimal_angle_deg": math.degrees(float(optimum.x)),
        "rotated_size_mm": [width, height],
        "minimum_square_mm": max(width, height),
        "fits_180": max(width, height) <= 180.0,
        "fits_256": max(width, height) <= 256.0,
    }


def shell_mass_range(volume_cm3: float, area_cm2: float) -> dict:
    """First-order shell + 20% infill estimate, not a slicer simulation.

    delta is an effective inward solid skin.  0.8--1.35 mm spans typical
    top/bottom skin and three 0.4-mm-nozzle perimeter lines.
    """
    estimates = {}
    for delta_mm in (0.8, 1.35):
        shell_fraction = min(1.0, area_cm2 * (delta_mm / 10.0) / volume_cm3)
        material_fraction = shell_fraction + (1.0 - shell_fraction) * 0.20
        estimates[str(delta_mm)] = {
            "shell_fraction": shell_fraction,
            "material_fraction": material_fraction,
            "mass_g_at_TPU_1.21": volume_cm3 * material_fraction * 1.21,
        }
    return estimates


def main() -> None:
    meshes = {}
    output = {"files": [], "pairs": {}, "footprints": {}}
    for name in NAMES:
        mesh, result = analyze(ROOT / name)
        meshes[name] = mesh
        output["files"].append(result)

    for number in (7, 9, 10):
        lname = f"spear_{number}_L.stl"
        rname = f"spear_{number}_R.stl"
        left = unique_vertices(meshes[lname])
        right = unique_vertices(meshes[rname])
        reflected = left.copy()
        reflected[:, 0] *= -1.0
        mirror_rms, mirror_max = nearest_error(reflected, right)
        reverse_rms, reverse_max = nearest_error(right, reflected)
        output["pairs"][str(number)] = {
            "unique_vertices_L": len(left),
            "unique_vertices_R": len(right),
            "mirror_L_to_R_rms_mm": mirror_rms,
            "mirror_L_to_R_max_mm": mirror_max,
            "mirror_R_to_L_rms_mm": reverse_rms,
            "mirror_R_to_L_max_mm": reverse_max,
            "best_proper_rotation": best_proper_rotation_error(left, right),
        }

    by_name = {entry["file"]: entry for entry in output["files"]}
    for number in (7, 9, 10):
        entry = by_name[f"spear_{number}_L.stl"]
        size = entry["size_mm"]
        output["footprints"][str(number)] = square_footprint(size[0], size[1])
        output["footprints"][str(number)]["actual_mesh_xy"] = actual_xy_footprint(
            meshes[f"spear_{number}_L.stl"]
        )
        output["footprints"][str(number)]["shell_mass_range"] = shell_mass_range(
            abs(entry["signed_volume_cm3"]), entry["surface_area_cm2"]
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
