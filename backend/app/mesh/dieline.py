import math
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import trimesh
from scipy.spatial.transform import Rotation
from shapely.geometry import LineString, Point
from shapely.ops import polygonize, unary_union

from app.mesh.common import (
    MeshResult,
    concat_geometry,
    concat_textured_geometry,
    normalize_multiple_to_unit_scale,
    rasterize_artwork,
    triangulate_polygon_2d,
)

MIN_PANEL_AREA_FRACTION = 0.001
DEFAULT_FOLD_ANGLE_DEG = 90.0

# Kraft-brown, for the box's inside faces + raw-edge walls (no artwork there)
CARDBOARD_COLOR = (196, 164, 132)

_EXTENSION_TO_KIND = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".svg": "svg", ".pdf": "pdf"}


def _panel_extrusion_split(
    polygon_points: list[tuple[float, float]],
    thickness: float,
    uv_origin: tuple[float, float],
    uv_size: tuple[float, float],
) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray], list[tuple[np.ndarray, np.ndarray]]]:
    """Extrude one flat panel, split into an "outside" front cap (artwork side,
    UV-projected onto the original artwork) and "inside" back cap + walls
    (cardboard side — the box interior and raw panel edges aren't printed)."""
    verts2d, faces = triangulate_polygon_2d(polygon_points, [])
    front = np.column_stack([verts2d[:, 0], verts2d[:, 1], np.zeros(len(verts2d))])
    back = np.column_stack([verts2d[:, 0], verts2d[:, 1], np.full(len(verts2d), thickness)])

    min_x, min_y = uv_origin
    ref_w, ref_h = uv_size
    front_uv = np.column_stack([(verts2d[:, 0] - min_x) / ref_w, (verts2d[:, 1] - min_y) / ref_h])

    n = len(polygon_points)
    ring = np.asarray(polygon_points, dtype=float)
    wall_verts = np.vstack([
        np.column_stack([ring[:, 0], ring[:, 1], np.zeros(n)]),
        np.column_stack([ring[:, 0], ring[:, 1], np.full(n, thickness)]),
    ])
    wall_faces = []
    for i in range(n):
        j = (i + 1) % n
        wall_faces.append([i, i + n, j + n])
        wall_faces.append([i, j + n, j])

    artwork_part = (front, faces[:, ::-1], front_uv)
    cardboard_parts = [(back, faces), (wall_verts, np.array(wall_faces))]
    return artwork_part, cardboard_parts


def _reference_box(features: dict) -> tuple[float, float, float, float]:
    """(min_x, min_y, width, height) of the coordinate space the line points
    are expressed in — SVG viewBox, PDF page size, or raster image pixels."""
    if "view_box" in features:
        vb = features["view_box"]
        return vb["min_x"], vb["min_y"], vb["width"], vb["height"]
    if "page_size" in features:
        ps = features["page_size"]
        return 0.0, 0.0, ps["width"], ps["height"]
    if "image_size" in features:
        isz = features["image_size"]
        return 0.0, 0.0, isz["width"], isz["height"]
    raise ValueError("No reference size found in dieline features")


def _snap_endpoints(
    lines: list[dict[str, Any]], tolerance: float
) -> list[list[tuple[float, float]]]:
    """Union-find clustering of nearby line endpoints, snapped to their cluster
    centroid. Raster-detected lines (independent Hough passes per edge) rarely
    share exact coordinates even when visually touching — without this,
    shapely's polygonize sees tiny gaps and never closes a panel.

    Only each line's first/last point is touched — interior vertices (e.g. a
    rectangle traced as one 5-point closed ring) are preserved as-is."""
    starts = [tuple(line["points"][0]) for line in lines]
    ends = [tuple(line["points"][-1]) for line in lines]
    endpoints = starts + ends
    n = len(endpoints)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if math.dist(endpoints[i], endpoints[j]) <= tolerance:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    centroids = {}
    for idxs in clusters.values():
        cx = sum(endpoints[i][0] for i in idxs) / len(idxs)
        cy = sum(endpoints[i][1] for i in idxs) / len(idxs)
        for i in idxs:
            centroids[i] = (cx, cy)

    result = []
    for k, line in enumerate(lines):
        pts = [tuple(p) for p in line["points"]]
        pts[0] = centroids[k]
        pts[-1] = centroids[len(lines) + k]
        result.append(pts)
    return result


def _snap_t_junctions(
    points_list: list[list[tuple[float, float]]], tolerance: float
) -> list[list[tuple[float, float]]]:
    """After corner-to-corner clustering, a line ending mid-span on another line
    (a T-junction — e.g. a fold line meeting a border) still won't precisely
    touch it. Project any endpoint that's merely *close* to another line onto
    that line's exact geometry, so shapely's noding sees a real intersection.
    Only first/last points move; interior vertices are untouched."""
    result = [list(pts) for pts in points_list]
    for i, pts in enumerate(points_list):
        for k in (0, -1):
            pt = Point(pts[k])
            best_dist = tolerance
            best_proj = None
            for j, other in enumerate(points_list):
                if j == i:
                    continue
                other_line = LineString(other)
                dist = other_line.distance(pt)
                if 1e-6 < dist < best_dist:
                    best_dist = dist
                    best_proj = other_line.interpolate(other_line.project(pt))
            if best_proj is not None:
                result[i][k] = (best_proj.x, best_proj.y)
    return result


def _extract_panels(lines: list[dict[str, Any]]) -> tuple[list[Any], list[LineString | None]]:
    all_points = np.array([pt for line in lines for pt in line["points"]], dtype=float)
    bbox_diag = float(np.hypot(*(all_points.max(axis=0) - all_points.min(axis=0)))) if len(all_points) else 100.0
    snap_tolerance = max(bbox_diag * 0.02, 6.0)
    snapped_points = _snap_endpoints(lines, snap_tolerance)
    snapped_points = _snap_t_junctions(snapped_points, snap_tolerance)

    # Keep line_geoms the same length/order as `lines` (None for degenerate
    # zero-length snaps) so callers can zip them against the original
    # classified-line list by index.
    line_geoms: list[LineString | None] = [
        None if (len(pts) == 2 and pts[0] == pts[1]) else LineString(pts) for pts in snapped_points
    ]
    valid_geoms = [g for g in line_geoms if g is not None]
    if not valid_geoms:
        raise ValueError("No line geometry found to build panels from")

    noded = unary_union(valid_geoms)
    panels = list(polygonize(noded))
    if not panels:
        raise ValueError("Lines did not form any closed panel regions")

    total_area = sum(p.area for p in panels)
    min_area = total_area * MIN_PANEL_AREA_FRACTION
    panels = [p for p in panels if p.area >= min_area]
    if not panels:
        raise ValueError("All candidate panels were smaller than the noise threshold")

    return panels, line_geoms


def _match_edge_type(
    edge_mid: Point, classified_lines: list[dict[str, Any]], line_geoms: list[LineString | None], eps: float
) -> str:
    for line, geom in zip(classified_lines, line_geoms):
        if geom is not None and geom.distance(edge_mid) < eps:
            return line["type"]
    return "unknown"


def _round_pt(pt: tuple[float, float], precision: int = 1) -> tuple[float, float]:
    return (round(pt[0], precision), round(pt[1], precision))


def _build_adjacency(
    panels: list[Any], lines: list[dict[str, Any]], line_geoms: list[LineString | None], eps: float
) -> tuple[nx.Graph, list[list[tuple[float, float]]]]:
    graph = nx.Graph()
    panel_rings = []

    edge_to_panels: dict[frozenset, list[tuple[int, str, tuple, tuple]]] = {}

    for panel_idx, panel in enumerate(panels):
        graph.add_node(panel_idx, area=panel.area)
        coords = list(panel.exterior.coords)[:-1]
        panel_rings.append(coords)
        n = len(coords)
        for i in range(n):
            p1 = coords[i]
            p2 = coords[(i + 1) % n]
            mid = Point((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            edge_type = _match_edge_type(mid, lines, line_geoms, eps)
            key = frozenset({_round_pt(p1), _round_pt(p2)})
            edge_to_panels.setdefault(key, []).append((panel_idx, edge_type, p1, p2))

    for key, entries in edge_to_panels.items():
        if len(entries) != 2:
            continue
        (idx_a, type_a, p1, p2), (idx_b, type_b, _, _) = entries
        if idx_a == idx_b:
            continue
        if "fold" in (type_a, type_b):
            graph.add_edge(idx_a, idx_b, hinge=(p1, p2))

    return graph, panel_rings


def _compute_transforms(
    graph: nx.Graph,
    base_idx: int,
    fold_angle_deg: float,
    panel_rings: list[list[tuple[float, float]]],
) -> tuple[dict[int, np.ndarray], nx.DiGraph]:
    transforms = {base_idx: np.eye(4)}
    tree = nx.bfs_tree(graph, base_idx)

    for parent, child in nx.bfs_edges(graph, base_idx):
        hinge = graph.edges[parent, child]["hinge"]
        h1, h2 = hinge
        parent_t = transforms[parent]

        # Choose the hinge axis's sign so every child folds to the SAME side
        # relative to its own parent (not just a fixed direction from however
        # shapely happened to wind that edge) — otherwise sibling flaps can
        # fold to opposite sides of the parent and the net never closes into
        # a coherent box. This is computed once in the FLAT/pre-fold layout
        # (a fixed geometric relationship between parent and child) and then
        # rotated into the parent's current world orientation.
        axis_local = np.array([h2[0] - h1[0], h2[1] - h1[1], 0.0])
        axis_local /= np.linalg.norm(axis_local) or 1.0

        centroid = np.asarray(panel_rings[child]).mean(axis=0)
        r_local = np.array([centroid[0] - h1[0], centroid[1] - h1[1], 0.0])
        cross_z = axis_local[0] * r_local[1] - axis_local[1] * r_local[0]
        if cross_z < 0:
            axis_local = -axis_local

        axis_world = parent_t[:3, :3] @ axis_local
        axis_world /= np.linalg.norm(axis_world) or 1.0

        h1_4 = np.array([h1[0], h1[1], 0.0, 1.0])
        h1_world = (parent_t @ h1_4)[:3]

        rot3 = Rotation.from_rotvec(axis_world * np.radians(fold_angle_deg)).as_matrix()
        rot4 = np.eye(4)
        rot4[:3, :3] = rot3

        to_origin = np.eye(4)
        to_origin[:3, 3] = -h1_world
        back = np.eye(4)
        back[:3, 3] = h1_world

        rotate_about_hinge = back @ rot4 @ to_origin
        transforms[child] = rotate_about_hinge @ parent_t

    return transforms, tree


def _mesh_from_panels(
    panel_rings: list[list[tuple[float, float]]],
    thickness: float,
    transforms: dict[int, np.ndarray] | None,
    uv_origin: tuple[float, float],
    uv_size: tuple[float, float],
    artwork_image,
) -> trimesh.Scene:
    """Build a two-primitive scene: an "artwork" mesh (every panel's outward
    face, textured with the original packaging art) and a "cardboard" mesh
    (every panel's inside face + raw edge walls, flat kraft-brown)."""
    artwork_parts = []
    cardboard_parts = []

    for idx, ring in enumerate(panel_rings):
        try:
            artwork_part, cb_parts = _panel_extrusion_split(ring, thickness, uv_origin, uv_size)
        except Exception:
            continue

        t = transforms.get(idx, np.eye(4)) if transforms is not None else np.eye(4)

        def apply(v: np.ndarray) -> np.ndarray:
            homo = np.hstack([v, np.ones((len(v), 1))])
            return (homo @ t.T)[:, :3]

        fv, ff, fuv = artwork_part
        artwork_parts.append((apply(fv), ff, fuv))
        for v, f in cb_parts:
            cardboard_parts.append((apply(v), f))

    artwork_v, artwork_f, artwork_uv = concat_textured_geometry(artwork_parts)
    cardboard_v, cardboard_f = concat_geometry(cardboard_parts)

    (artwork_v, cardboard_v), _scale = normalize_multiple_to_unit_scale(
        [artwork_v, cardboard_v], target_size=2.0
    )

    scene = trimesh.Scene()

    if len(artwork_v):
        material = trimesh.visual.material.PBRMaterial(
            baseColorTexture=artwork_image, metallicFactor=0.0, roughnessFactor=0.8
        )
        visual = trimesh.visual.TextureVisuals(uv=artwork_uv, material=material)
        artwork_mesh = trimesh.Trimesh(vertices=artwork_v, faces=artwork_f, visual=visual, process=False)
        scene.add_geometry(artwork_mesh, geom_name="artwork")

    if len(cardboard_v):
        material = trimesh.visual.material.PBRMaterial(
            baseColorFactor=[c / 255 for c in CARDBOARD_COLOR] + [1.0],
            metallicFactor=0.0,
            roughnessFactor=0.9,
        )
        cardboard_mesh = trimesh.Trimesh(vertices=cardboard_v, faces=cardboard_f, process=False)
        cardboard_mesh.visual = trimesh.visual.TextureVisuals(material=material)
        scene.add_geometry(cardboard_mesh, geom_name="cardboard")

    return scene


def generate(
    features: dict,
    original_image_path: Path,
    output_dir: Path,
    fold_angle_deg: float = DEFAULT_FOLD_ANGLE_DEG,
) -> MeshResult:
    """Partition the classified dieline lines into flat panel polygons (via
    shapely's planar-arrangement polygonize), build the panel-adjacency graph
    from fold-classified shared edges, derive a kinematic tree rooted at the
    largest panel, and export both the flat net and a folded 3D state.

    Each panel's outward face is UV-projected onto the original packaging
    artwork; its inside face and raw edge walls get a flat cardboard color —
    a real box net is printed on one side of the blank, and that whole
    printed side becomes the box's outside after folding, uniformly.

    Fold direction (mountain vs valley) isn't recoverable from color/dash
    classification alone, so every hinge folds the same way by convention —
    a real box may need some hinges flipped, and this doesn't attempt
    collision detection between panels during/after folding.
    """
    lines = features.get("lines", [])
    panels, line_geoms = _extract_panels(lines)

    all_coords = np.array([pt for p in panels for pt in p.exterior.coords])
    bbox_diag = float(np.hypot(*(all_coords.max(axis=0) - all_coords.min(axis=0)))) or 100.0
    eps = max(bbox_diag * 1e-4, 0.5)

    graph, panel_rings = _build_adjacency(panels, lines, line_geoms, eps)

    components = list(nx.connected_components(graph))
    all_transforms: dict[int, np.ndarray] = {}
    tree_edges = []
    base_indices = []
    for component in components:
        base_idx = max(component, key=lambda i: graph.nodes[i]["area"])
        base_indices.append(base_idx)
        transforms, tree = _compute_transforms(
            graph.subgraph(component), base_idx, fold_angle_deg, panel_rings
        )
        all_transforms.update(transforms)
        tree_edges.extend(list(tree.edges()))

    panel_thickness = max(bbox_diag * 0.01, 1.0)

    min_x, min_y, ref_w, ref_h = _reference_box(features)
    file_kind = _EXTENSION_TO_KIND.get(original_image_path.suffix.lower(), "png")
    artwork_image = rasterize_artwork(original_image_path, file_kind, (ref_w, ref_h))

    flat_scene = _mesh_from_panels(
        panel_rings, panel_thickness, None, (min_x, min_y), (ref_w, ref_h), artwork_image
    )
    folded_scene = _mesh_from_panels(
        panel_rings, panel_thickness, all_transforms, (min_x, min_y), (ref_w, ref_h), artwork_image
    )

    flat_filename = "dieline_flat.glb"
    folded_filename = "dieline_folded.glb"
    flat_scene.export(str(output_dir / flat_filename), file_type="glb")
    folded_scene.export(str(output_dir / folded_filename), file_type="glb")

    hinge_count = sum(1 for _ in graph.edges())
    tree_edge_set = {frozenset(e) for e in tree_edges}
    auxiliary_hinges = sum(1 for e in graph.edges() if frozenset(e) not in tree_edge_set)

    summary = {
        "panel_count": len(panels),
        "hinge_count": hinge_count,
        "tree_edge_count": len(tree_edges),
        "auxiliary_hinge_count": auxiliary_hinges,
        "connected_components": len(components),
        "fold_angle_deg": fold_angle_deg,
        "note": (
            "Fold direction is a fixed convention (not recoverable from color/dash "
            "classification alone) and panels are not checked for collisions while folding."
        ),
    }

    kinematic_tree = {
        "panels": [
            {"id": i, "area": round(panels[i].area, 1), "is_base": i in base_indices, "polygon": panel_rings[i]}
            for i in range(len(panels))
        ],
        "hinges": [
            {
                "panel_a": a,
                "panel_b": b,
                "points": [list(graph.edges[a, b]["hinge"][0]), list(graph.edges[a, b]["hinge"][1])],
                "in_tree": frozenset((a, b)) in tree_edge_set,
            }
            for a, b in graph.edges()
        ],
        "fold_angle_deg": fold_angle_deg,
    }

    return MeshResult(
        mesh_filename=folded_filename,
        extra_filename=flat_filename,
        summary=summary,
        features=kinematic_tree,
    )
