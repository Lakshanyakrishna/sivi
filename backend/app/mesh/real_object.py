from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter

from app.mesh.common import MeshResult, normalize_to_unit_scale

# Coarser than this and thin structures (chair legs, spindles, handles) shrink to
# sub-1-cell width: _build_surface only emits a face when all 4 corners of a grid
# quad are inside the mask, so a 1-cell-wide strip produces zero faces and the
# subject fragments into disconnected slivers instead of a continuous shape.
MAX_GRID_DIM = 220
MAX_DEPTH_FRACTION = 0.35  # front bulge depth as a fraction of the silhouette's shorter side
BACK_DEPTH_RATIO = 0.55  # back bulge is shallower than the front


def _downsample(rgba: np.ndarray, max_dim: int) -> np.ndarray:
    h, w = rgba.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    new_w, new_h = max(2, int(round(w * scale))), max(2, int(round(h * scale)))
    return np.array(Image.fromarray(rgba).resize((new_w, new_h), Image.BILINEAR))


def _build_surface(
    xx: np.ndarray, yy: np.ndarray, height: np.ndarray, uv: np.ndarray, mask: np.ndarray, flip_normal: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    grid_h, grid_w = mask.shape
    verts = np.stack([xx.astype(float), -yy.astype(float), height], axis=-1).reshape(-1, 3)
    uvs = uv.reshape(-1, 2)

    quad_ok = mask[:-1, :-1] & mask[:-1, 1:] & mask[1:, :-1] & mask[1:, 1:]
    r, c = np.where(quad_ok)
    i00 = r * grid_w + c
    i01 = r * grid_w + (c + 1)
    i10 = (r + 1) * grid_w + c
    i11 = (r + 1) * grid_w + (c + 1)
    if flip_normal:
        faces = np.concatenate(
            [np.stack([i00, i11, i01], axis=1), np.stack([i00, i10, i11], axis=1)]
        )
    else:
        faces = np.concatenate(
            [np.stack([i00, i01, i11], axis=1), np.stack([i00, i11, i10], axis=1)]
        )

    return verts, uvs, faces if len(faces) else np.zeros((0, 3), dtype=int)


def generate(cutout_path: Path, output_dir: Path) -> MeshResult:
    """Heuristic 2D->3D "inflation": treat the alpha-mask silhouette's distance
    transform as a height field, bulge front+back surfaces from it, and texture
    both with the original (background-removed) photo.

    This is a fast, dependency-light stand-in for a learned single-image 3D
    reconstruction model (TripoSR/LRM/Shap-E) — it fabricates plausible rounded
    volume and back geometry from the silhouette alone, not true multi-view or
    learned depth. Swap in a real model later by replacing this function's body;
    the (cutout_path, output_dir) -> MeshResult contract stays the same.
    """
    with Image.open(cutout_path) as im:
        rgba_full = np.array(im.convert("RGBA"))

    alpha_full = rgba_full[:, :, 3]
    ys, xs = np.where(alpha_full > 10)
    if len(xs) == 0:
        raise ValueError("Cutout has no visible (non-transparent) subject")

    pad = 4
    x0, x1 = max(0, int(xs.min()) - pad), min(rgba_full.shape[1], int(xs.max()) + pad + 1)
    y0, y1 = max(0, int(ys.min()) - pad), min(rgba_full.shape[0], int(ys.max()) + pad + 1)
    cropped = rgba_full[y0:y1, x0:x1]

    color_arr = _downsample(cropped, MAX_GRID_DIM)
    mask = color_arr[:, :, 3] > 10
    grid_h, grid_w = mask.shape

    dist = distance_transform_edt(mask)
    # Smooth before use: on thin structures (chair legs, spindles) the raw distance
    # transform can jump sharply between adjacent cells, which would otherwise turn
    # into jagged spikes rather than a rounded profile. Re-zero outside the mask
    # afterward so blur doesn't leak height into the background.
    dist = gaussian_filter(dist, sigma=0.8) * mask

    # Height is proportional to the LOCAL distance-to-edge, not distance normalized
    # against the silhouette's single widest point. A subject like a chair spans
    # wildly different local thicknesses (a seat vs. a leg vs. a spindle) — normalizing
    # by the global max and then taking sqrt (as earlier versions did) pulls thin
    # regions' height up toward the thick region's scale (sqrt compresses the ratio),
    # producing bulges several times taller than the region is wide. Scaling directly
    # off local distance instead makes a tube of local half-width R bulge to
    # height ~= R, i.e. an actual round cross-section at whatever scale it occurs.
    # max_depth is only a safety ceiling for degenerate/near-circular silhouettes.
    short_side = min(grid_h, grid_w)
    max_depth = short_side * MAX_DEPTH_FRACTION
    depth_scale = 1.2
    front_height = np.minimum(depth_scale * dist, max_depth)
    back_height = -np.minimum(depth_scale * dist, max_depth) * BACK_DEPTH_RATIO

    xx, yy = np.meshgrid(np.arange(grid_w), np.arange(grid_h))
    uv = np.stack([xx / max(grid_w - 1, 1), yy / max(grid_h - 1, 1)], axis=-1)

    front_v, front_uv, front_f = _build_surface(xx, yy, front_height, uv, mask, flip_normal=False)
    back_v, back_uv, back_f = _build_surface(xx, yy, back_height, uv, mask, flip_normal=True)

    vertices = np.vstack([front_v, back_v])
    uvs = np.vstack([front_uv, back_uv])
    faces = np.vstack([front_f, back_f + len(front_v)])

    vertices, _scale_factor = normalize_to_unit_scale(vertices, target_size=2.0)

    # Extend foreground colors into the transparent background before texturing.
    # Otherwise GPU texture sampling/mipmapping at the silhouette edge blends in
    # the (often black) background RGB, producing a dark halo around the mesh.
    _, (nearest_y, nearest_x) = distance_transform_edt(~mask, return_indices=True)
    extended_rgb = color_arr[:, :, :3][nearest_y, nearest_x]
    color_rgb = Image.fromarray(extended_rgb, mode="RGB")
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=color_rgb, metallicFactor=0.0, roughnessFactor=0.9
    )
    visual = trimesh.visual.TextureVisuals(uv=uvs, material=material)

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, visual=visual, process=False)
    mesh.merge_vertices()
    mesh.fix_normals()

    mesh_filename = "mesh.glb"
    mesh.export(str(output_dir / mesh_filename), file_type="glb")

    summary = {
        "vertex_count": int(len(mesh.vertices)),
        "face_count": int(len(mesh.faces)),
        "method": "silhouette_distance_transform_inflation",
        "note": (
            "Heuristic reconstruction from the subject's silhouette, not a learned "
            "3D model — back geometry is inferred, not observed."
        ),
    }
    return MeshResult(mesh_filename=mesh_filename, summary=summary)
