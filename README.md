# Sivi — 2D to 3D

Converts 2D graphics/photos into 3D-ready assets.

## Phase 1 — Ingestion & Intent Routing

- **Upload Module**: accepts PNG, JPG, PDF, SVG. Extracts basic metadata
  (image/PDF page dimensions, PDF page count, SVG width/height/viewBox).
- **Routing Switch**: manual UI toggle to tag each upload as one of
  `Real Object`, `Flat Graphic`, or `Packaging Dieline`, stored against the
  asset for the next phase to consume.

## Phase 2 — Pre-processing & Feature Extraction

Once routed, `POST /api/assets/{id}/process` runs the pipeline for that route:

- **Real Object** (`app/processing/real_object.py`): background removal via
  `rembg` (u2net). Saves an RGBA cutout and reports subject coverage % and
  bounding box. Requires a PNG/JPG input.
- **Flat Graphic** (`app/processing/flat_graphic.py`): grayscale + Otsu
  threshold, then OpenCV `findContours` with hierarchy to separate the outer
  boundary from internal holes. Vector inputs (SVG/PDF) are rasterized first
  via PyMuPDF. Saves a contour-overlay preview (green = outer, red = hole)
  and the simplified polygon points.
- **Packaging Dieline** (`app/processing/dieline.py`): extracts line data and
  classifies each as `cut` / `fold` / `unknown` using the rule *solid red =
  cut, dashed blue = fold*:
  - SVG: walks path/line/polyline/polygon/rect elements, reading
    `stroke` + `stroke-dasharray` (a minimal path-`d` parser handles
    M/L/H/V/Z and approximates curves by their endpoints).
  - PDF: uses PyMuPDF's `get_drawings()` for vector paths with real stroke
    color/dash info — no rasterization needed.
  - PNG (raster fallback): HSV color masks (red/blue) + Hough line detection,
    with collinear-segment merging and gap-sampling to guess dashed vs solid.
    Flagged `confidence: "low"` — this path is inherently less reliable than
    vector input, per the nature of the problem.

Results are stored as: a small `feature_summary` (counts, shown in the DB and
UI) and a full `features.json` per asset (`GET /api/assets/{id}/features`)
with the raw contour/line coordinate data for the next phase to consume.

## Phase 3 — The Tri-Modal 3D Generation Engine

Once Phase 2 has run, `POST /api/assets/{id}/generate-mesh` builds a GLB mesh
using the engine for that route:

- **Engine A — Real Object** (`app/mesh/real_object.py`): **not a real learned
  3D model.** TripoSR/LRM/Shap-E need GPU compute and multi-GB downloads that
  won't run reliably in this environment, so this is a heuristic stand-in:
  a distance-transform of the rembg cutout's alpha mask becomes a height
  field, bulged into front + back surfaces (the back shallower, since it's
  fabricated, not observed) that share a seam at the silhouette edge, then
  UV-mapped and textured with the original photo. Swap in a real model later
  by replacing this function's body — the `(cutout_path, output_dir) ->
  MeshResult` contract stays the same.
- **Engine B — Flat Graphic** (`app/mesh/flat_graphic.py`): earcut-triangulates
  the Phase 2 contour polygons (via `trimesh`/`mapbox_earcut`), extrudes them
  into solid panels, and bevels the edges — a vertex-bisector polygon offset
  builds the inset rings, connected to the full-size rings by ruled-surface
  strips, so holes bevel correctly too (they grow rather than shrink).
  Produces a single watertight, honest-volume mesh.
- **Engine C — Packaging Dieline** (`app/mesh/dieline.py`): the graph-traversal
  problem. Classified lines are noded and partitioned into panel polygons via
  shapely's `polygonize`; panel-boundary edges are matched back against the
  original cut/fold lines to build an adjacency graph; a spanning tree rooted
  at the largest panel (via `networkx`) gives the kinematic hierarchy. Folding
  is a recursive rigid-transform composition — each child's world matrix is
  its parent's matrix, further rotated about the shared hinge axis (now in
  the parent's already-transformed position) — so a fold at any node carries
  every descendant with it automatically. Exports both the flat net and a
  folded-90° state as separate GLBs, plus the full panel/hinge graph as
  `mesh_features.json` (`GET /api/assets/{id}/mesh-features`).
  **Known limitations:**
  - Fold direction (mountain vs. valley) isn't recoverable from color/dash
    classification alone, so every hinge folds the same conventional way, and
    panels are not checked for collisions while folding — a real box net may
    need some hinges flipped by hand.
  - The fold angle is a fixed 90° for every hinge, not computed per-hinge from
    geometry. Verified against classic nets (see `/tmp/net_*.svg` test
    fixtures): a **cube net closes perfectly** (90° is exactly correct for a
    cube's faces), but a **square pyramid net does not fully close** (each
    triangular face needs an angle less than 90°, dependent on the
    base/height ratio) and a **triangular prism's side walls only reach a 90°
    "V"** instead of sealing (needs 120° between each side). This is a
    deliberate scope decision, not a bug: real packaging dielines are almost
    universally rectangular cartons, where 90° is correct. Non-rectangular
    solids would need per-hinge target angles derived from the panel
    geometry, which isn't implemented.

## Phase 4 — UV Mapping & Texturing

- **Engine A**: already textured in Phase 3 — the photo is UV-mapped directly
  onto the inflated front/back surfaces (`app/mesh/real_object.py`).
- **Engine B**: `app/mesh/flat_graphic.py` now projects each vertex's original
  pixel-space (x, y) directly onto the rasterized artwork (`GET
  /api/assets/{id}/artwork.png`), normalized to 0-1 by the source image's own
  dimensions — a real UV projection, not a sampled average color.
- **Engine C**: each panel is split into two geometries — an **outside**
  face (the flat sheet's single printed face — the same face is "outside" for
  every panel once folded, so no per-panel guessing is needed) UV-mapped onto
  the artwork, and an **inside** face + raw edge walls in flat kraft-brown
  (`CARDBOARD_COLOR`), with no texture. `app/mesh/common.py::rasterize_artwork`
  renders vector inputs (SVG/PDF) via PyMuPDF at a fixed target width; raster
  inputs are used as-is. UV is always normalized against the *original*
  coordinate space (SVG viewBox / PDF page size / image pixels) via
  `_reference_box`, not the rasterization's own pixel size, so it stays
  correct regardless of render resolution.

## Phase 5 — Interactive Web Viewer & Export

The frontend replaced `<model-viewer>` with a custom Three.js viewer
(`frontend/src/lib/three-scene.ts` + `frontend/src/components/three/`) —
shadow-casting lighting, `OrbitControls`, and per-engine live interactivity:

- **Engine A** (`EngineAViewer.tsx`): loads the static GLB via `GLTFLoader`.
  No live parameters here — Engine A doesn't expose extrusion knobs.
- **Engine B** (`EngineBViewer.tsx`): rebuilds Phase 2's contour polygons as
  `THREE.Shape`s (with holes) client-side and extrudes them with
  `THREE.ExtrudeGeometry`, whose `depth`/`bevelThickness`/`bevelSize` are
  driven live by sliders — dragging one disposes the old geometry and swaps
  in a new one on the same mesh, no server round-trip. A custom `UVGenerator`
  projects onto the real artwork dimensions (not the shape's own bounding
  box, which `ExtrudeGeometry`'s default `WorldUVGenerator` uses verbatim,
  unnormalized).
- **Engine C** (`EngineCViewer.tsx`): the kinematic tree
  (`frontend/src/lib/kinematic-tree.ts`, a BFS mirroring the backend's
  spanning tree) is rebuilt as **nested pivot groups** — each non-root panel's
  `Group` sits at its hinge point (in its parent's local frame, i.e. offset by
  the *delta* between its own and its parent's hinge — not the raw absolute
  point, which double-counts translation for anything deeper than one level)
  with its content offset by the inverse, so Three.js's own scene-graph
  composition handles "rotate a node and everything under it" for free — no
  manual matrix math needed, unlike the Python engine. A single fold-angle
  slider (0–180°) sets every pivot group's quaternion directly.
- **Export**: every viewer's "Download .glb" button runs Three.js's
  `GLTFExporter` (`exportObjectAsGlb` in `three-scene.ts`) on the *live*
  scene — whatever thickness/bevel/fold-angle is currently showing is exactly
  what gets exported, not a re-fetch of the original server-rendered file.

## Stack

- `backend/` — FastAPI + SQLAlchemy (SQLite). Pillow/pypdf/defusedxml for
  ingestion metadata; rembg, OpenCV, PyMuPDF (fitz) for Phase 2 processing;
  trimesh, mapbox_earcut, shapely, scipy, networkx for Phase 3/4 mesh
  generation and texturing.
- `frontend/` — Next.js (App Router) + TypeScript + Tailwind, Three.js for
  in-browser GLB rendering/interaction/export.

## Running locally

**Backend** (http://localhost:8000):

```bash
cd backend
python3 -m venv .venv          # first time only
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Note: the first `real_object` run downloads the u2net model (~176MB) to
`~/.u2net/`, so it needs network access once.

**Frontend** (http://localhost:3000):

```bash
cd frontend
npm install                     # first time only
npm run dev
```

The frontend reads the backend URL from `frontend/.env.local`
(`NEXT_PUBLIC_API_URL`, defaults to `http://localhost:8000`).

## API

- `POST /api/assets/upload` — multipart upload, returns the asset with
  extracted metadata.
- `POST /api/assets/{id}/route` — set the pipeline route
  (`real_object` | `flat_graphic` | `packaging_dieline`).
- `POST /api/assets/{id}/process` — run the Phase 2 pipeline for the asset's
  route; returns the asset with `processing_status`, a preview image URL, and
  `feature_summary`.
- `GET /api/assets/{id}/features` — full feature data (contour polygons or
  classified line segments) for the asset.
- `POST /api/assets/{id}/generate-mesh` — run the Phase 3 engine for the
  asset's route; returns the asset with `mesh_status`, `mesh_url` (folded
  state for dielines, the only mesh otherwise), `mesh_extra_url` (dieline flat
  net), and `mesh_summary`.
- `GET /api/assets/{id}/mesh-features` — full kinematic tree (panels + hinges)
  for a dieline asset.
- `GET /api/assets/{id}/artwork.png` — clean (no overlay) raster of the
  original upload, for the frontend's Three.js viewers to use as a texture.
- `GET /api/assets/{id}` — fetch an asset.
- Processed/original/mesh files are served statically under `/files/...`.
