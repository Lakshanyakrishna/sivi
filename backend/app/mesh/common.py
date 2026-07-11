from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz
import numpy as np
import trimesh
from PIL import Image
from shapely.geometry import Polygon

_VECTOR_KINDS = {"svg", "pdf"}


@dataclass
class MeshResult:
    mesh_filename: str
    summary: dict[str, Any]
    extra_filename: str | None = None
    features: dict[str, Any] | None = None


def signed_area(ring: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2


def ensure_orientation(ring: list[tuple[float, float]], ccw: bool) -> list[tuple[float, float]]:
    """Force a ring's winding direction. Exterior rings should be CCW, holes CW —
    this makes the vertex-bisector offset below shrink exteriors and grow holes
    uniformly, using one shared formula."""
    is_ccw = signed_area(ring) > 0
    return ring if is_ccw == ccw else list(reversed(ring))


def offset_ring(
    ring: list[tuple[float, float]], distance: float, max_scale: float = 4.0
) -> list[tuple[float, float]]:
    """Move every vertex `distance` to the left of its local bisected travel
    direction (miter-style). For a CCW ring this shrinks it inward; for a CW
    ring (a properly-oriented hole) it grows it outward — exactly the two
    behaviors a uniform inward bevel needs, from one formula."""
    pts = np.asarray(ring, dtype=float)
    n = len(pts)
    result = []
    for i in range(n):
        prev_pt = pts[(i - 1) % n]
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        e1 = cur - prev_pt
        e2 = nxt - cur
        e1 /= np.linalg.norm(e1) + 1e-9
        e2 /= np.linalg.norm(e2) + 1e-9
        n1 = np.array([-e1[1], e1[0]])
        n2 = np.array([-e2[1], e2[0]])
        bisector = n1 + n2
        blen = np.linalg.norm(bisector)
        if blen < 1e-6:
            offset_vec = n1 * distance
        else:
            bisector = bisector / blen
            cos_half = float(np.dot(bisector, n1))
            scale = 1.0 / max(cos_half, 1e-3)
            scale = min(scale, max_scale)
            offset_vec = bisector * distance * scale
        result.append(tuple(cur + offset_vec))
    return result


def triangulate_polygon_2d(
    exterior: list[tuple[float, float]], holes: list[list[tuple[float, float]]]
) -> tuple[np.ndarray, np.ndarray]:
    """Earcut-triangulate a polygon (with optional holes), returning (2D vertices, faces).

    Many small/close holes (e.g. a dieline's dense line-crossings misread as
    holes) can make the polygon self-overlapping; `buffer(0)`'s standard fix
    can itself split the result into a MultiPolygon or collapse it to empty,
    so both are handled explicitly instead of raising a confusing crash
    downstream when construction code assumes a single valid polygon.
    """
    polygon = Polygon(exterior, holes=holes if holes else None)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty:
        raise ValueError("Polygon has no area left after repairing self-intersections")
    if polygon.geom_type == "MultiPolygon":
        polygon = max(polygon.geoms, key=lambda g: g.area)

    vertices, faces = trimesh.creation.triangulate_polygon(polygon, engine="earcut")
    vertices = np.asarray(vertices)
    if vertices.ndim != 2 or len(vertices) < 3:
        raise ValueError("Triangulation produced no usable geometry")
    return vertices, np.asarray(faces)


def ruled_strip(
    ring_a: list[tuple[float, float]], z_a: float, ring_b: list[tuple[float, float]], z_b: float
) -> tuple[np.ndarray, np.ndarray]:
    """Build a quad-strip surface connecting two same-length, same-order rings
    at two different depths (used for bevel slopes and straight walls)."""
    n = len(ring_a)
    verts_a = np.array([(x, y, z_a) for x, y in ring_a])
    verts_b = np.array([(x, y, z_b) for x, y in ring_b])
    vertices = np.vstack([verts_a, verts_b])

    faces = []
    for i in range(n):
        j = (i + 1) % n
        a0, a1 = i, j
        b0, b1 = i + n, j + n
        faces.append([a0, b0, b1])
        faces.append([a0, b1, a1])

    return vertices, np.array(faces)


def concat_geometry(
    parts: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """Merge a list of (vertices, faces) pairs into one combined (vertices, faces) array."""
    all_vertices = []
    all_faces = []
    offset = 0
    for vertices, faces in parts:
        if len(vertices) == 0:
            continue
        all_vertices.append(vertices)
        all_faces.append(faces + offset)
        offset += len(vertices)
    if not all_vertices:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int)
    return np.vstack(all_vertices), np.vstack(all_faces)


def rasterize_artwork(
    original_path: Path, file_kind: str, reference_size: tuple[float, float], target_width: int = 1024
) -> Image.Image:
    """Render the original upload as a clean RGB texture image (no overlays).

    `reference_size` is the (width, height) of the coordinate space the caller's
    contour/line points are already expressed in — for vector inputs this is
    the SVG viewBox or PDF page size (points), for raster dielines/graphics
    it's the source image's own pixel dimensions. We only need our rendered
    texture's aspect ratio to match; UV mapping stays resolution-independent
    (normalized 0-1 against `reference_size`), so the absolute pixel scale we
    rasterize at here doesn't need to match Phase 2's own rasterization.
    """
    ref_w, ref_h = reference_size
    if file_kind in _VECTOR_KINDS:
        doc = fitz.open(str(original_path))
        scale = target_width / ref_w if ref_w else 1.0
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(scale, scale))
        mode = "RGB" if pix.n == 3 else "RGBA"
        return Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("RGB")

    return Image.open(original_path).convert("RGB")


def concat_textured_geometry(
    parts: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Like concat_geometry, but also merges a per-vertex UV array per part."""
    all_vertices, all_faces, all_uv = [], [], []
    offset = 0
    for vertices, faces, uv in parts:
        if len(vertices) == 0:
            continue
        all_vertices.append(vertices)
        all_faces.append(faces + offset)
        all_uv.append(uv)
        offset += len(vertices)
    if not all_vertices:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int), np.zeros((0, 2))
    return np.vstack(all_vertices), np.vstack(all_faces), np.vstack(all_uv)


def normalize_to_unit_scale(
    vertices: np.ndarray, target_size: float = 2.0
) -> tuple[np.ndarray, float]:
    """Uniformly scale vertices so the longest bounding-box side equals target_size."""
    if len(vertices) == 0:
        return vertices, 1.0
    extents = vertices.max(axis=0) - vertices.min(axis=0)
    longest = float(extents.max()) or 1.0
    scale = target_size / longest
    center = (vertices.max(axis=0) + vertices.min(axis=0)) / 2
    return (vertices - center) * scale, scale


def normalize_multiple_to_unit_scale(
    vertex_arrays: list[np.ndarray], target_size: float = 2.0
) -> tuple[list[np.ndarray], float]:
    """Like normalize_to_unit_scale, but computes one shared scale/center from
    the combined bounds of several vertex arrays — for a multi-primitive scene
    where each part must stay spatially aligned with the others."""
    non_empty = [v for v in vertex_arrays if len(v)]
    if not non_empty:
        return vertex_arrays, 1.0
    combined = np.vstack(non_empty)
    extents = combined.max(axis=0) - combined.min(axis=0)
    longest = float(extents.max()) or 1.0
    scale = target_size / longest
    center = (combined.max(axis=0) + combined.min(axis=0)) / 2
    return [(v - center) * scale if len(v) else v for v in vertex_arrays], scale
