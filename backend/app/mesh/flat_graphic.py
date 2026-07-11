from pathlib import Path

import numpy as np
import trimesh

from app.mesh.common import (
    MeshResult,
    concat_geometry,
    ensure_orientation,
    normalize_to_unit_scale,
    offset_ring,
    rasterize_artwork,
    ruled_strip,
    triangulate_polygon_2d,
)

EXTENSION_TO_KIND = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".svg": "svg", ".pdf": "pdf"}


def _build_panel_mesh(
    outer: list[tuple[float, float]],
    holes: list[list[tuple[float, float]]],
    thickness: float,
    bevel: float,
) -> tuple[np.ndarray, np.ndarray]:
    outer = ensure_orientation(outer, ccw=True)
    holes = [ensure_orientation(h, ccw=False) for h in holes]

    inset_outer = offset_ring(outer, bevel)
    inset_holes = [offset_ring(h, bevel) for h in holes]

    cap_verts2d, cap_faces = triangulate_polygon_2d(inset_outer, inset_holes)

    def cap_3d(z: float, flip: bool) -> tuple[np.ndarray, np.ndarray]:
        verts3d = np.column_stack([cap_verts2d[:, 0], cap_verts2d[:, 1], np.full(len(cap_verts2d), z)])
        faces = cap_faces[:, ::-1] if flip else cap_faces
        return verts3d, faces

    front_v, front_f = cap_3d(0.0, flip=True)
    back_v, back_f = cap_3d(thickness, flip=False)

    parts = [(front_v, front_f), (back_v, back_f)]

    parts.append(ruled_strip(inset_outer, 0.0, outer, bevel))
    parts.append(ruled_strip(outer, bevel, outer, thickness - bevel))
    parts.append(ruled_strip(outer, thickness - bevel, inset_outer, thickness))

    for hole, inset_hole in zip(holes, inset_holes):
        parts.append(ruled_strip(inset_hole, 0.0, hole, bevel))
        parts.append(ruled_strip(hole, bevel, hole, thickness - bevel))
        parts.append(ruled_strip(hole, thickness - bevel, inset_hole, thickness))

    return concat_geometry(parts)


def _sample_average_color(image_path: Path) -> tuple[int, int, int]:
    from app.processing.flat_graphic import _foreground_mask, _load_as_bgr

    file_kind = EXTENSION_TO_KIND.get(image_path.suffix.lower(), "png")
    try:
        bgr = _load_as_bgr(image_path, file_kind)
        mask = _foreground_mask(bgr) > 0
        if not mask.any():
            return (60, 60, 60)
        mean_bgr = bgr[mask].mean(axis=0)
        return (int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0]))
    except Exception:
        return (60, 60, 60)


def generate(
    features: dict, original_image_path: Path | None, output_dir: Path
) -> MeshResult:
    """Earcut-triangulate the Phase 2 contour polygons, extrude them into solid
    panels with beveled edges, and export as a single textured-material GLB."""
    contours = features.get("contours", [])

    holes_by_parent: dict[int, list[list[tuple[float, float]]]] = {}
    for c in contours:
        if c["type"] == "hole" and c.get("parent_index") is not None:
            holes_by_parent.setdefault(c["parent_index"], []).append(
                [tuple(p) for p in c["points"]]
            )

    all_points = np.array([p for c in contours for p in c["points"]], dtype=float)
    if len(all_points) == 0:
        raise ValueError("No contour points found to extrude")
    extents = all_points.max(axis=0) - all_points.min(axis=0)
    bbox_diag = float(np.hypot(extents[0], extents[1])) or 100.0

    thickness = max(bbox_diag * 0.08, 4.0)
    bevel = min(thickness * 0.3, bbox_diag * 0.015)
    bevel = min(bevel, thickness * 0.45)

    parts = []
    for idx, c in enumerate(contours):
        if c["type"] != "outer":
            continue
        outer_pts = [tuple(p) for p in c["points"]]
        if len(outer_pts) < 3:
            continue
        hole_pts_list = holes_by_parent.get(idx, [])
        try:
            v, f = _build_panel_mesh(outer_pts, hole_pts_list, thickness, bevel)
        except Exception:
            # Many small/close holes (e.g. a dense line-art shape misread as a
            # logo) can make the beveled inset self-overlap and fail; a sharp
            # (unbeveled) extrusion doesn't shrink/grow the holes at all, so
            # it succeeds far more often. Better a usable mesh without a
            # bevel than no mesh at all.
            try:
                v, f = _build_panel_mesh(outer_pts, hole_pts_list, thickness, 0.0)
            except Exception:
                continue
        parts.append((v, f))

    if not parts:
        raise ValueError("No usable outer contours found for extrusion")

    vertices, faces = concat_geometry(parts)

    # UV is a direct projection of each vertex's original 2D (pixel-space)
    # position onto the artwork image, normalized 0-1 — computed here, before
    # the Y-flip/rescale below change what those x,y values mean spatially.
    image_size = features.get("image_size", {})
    ref_w = float(image_size.get("width") or 1.0)
    ref_h = float(image_size.get("height") or 1.0)
    uv = np.column_stack([vertices[:, 0] / ref_w, vertices[:, 1] / ref_h])

    vertices = vertices.copy()
    vertices[:, 1] *= -1  # image Y-down -> mesh Y-up
    vertices, _scale = normalize_to_unit_scale(vertices, target_size=2.0)

    material = None
    if original_image_path is not None:
        try:
            file_kind = EXTENSION_TO_KIND.get(original_image_path.suffix.lower(), "png")
            artwork = rasterize_artwork(original_image_path, file_kind, (ref_w, ref_h))
            material = trimesh.visual.material.PBRMaterial(
                baseColorTexture=artwork, metallicFactor=0.0, roughnessFactor=0.8
            )
        except Exception:
            material = None

    if material is None:
        color = _sample_average_color(original_image_path) if original_image_path else (60, 60, 60)
        material = trimesh.visual.material.PBRMaterial(
            baseColorFactor=[color[0] / 255, color[1] / 255, color[2] / 255, 1.0],
            metallicFactor=0.05,
            roughnessFactor=0.6,
        )

    visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, visual=visual, process=False)
    mesh.merge_vertices()
    mesh.fix_normals()

    mesh_filename = "mesh.glb"
    mesh.export(str(output_dir / mesh_filename), file_type="glb")

    summary = {
        "vertex_count": int(len(mesh.vertices)),
        "face_count": int(len(mesh.faces)),
        "panel_count": len(parts),
        "thickness": round(thickness, 2),
        "bevel": round(bevel, 2),
    }
    return MeshResult(mesh_filename=mesh_filename, summary=summary)
