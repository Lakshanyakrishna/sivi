import io
import json
import shutil

import fitz
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.mesh.common import rasterize_artwork
from app.models import Asset
from app.schemas import AssetOut, SetRouteIn
from app.storage import UPLOAD_DIR, processed_dir_for, save_upload

router = APIRouter(prefix="/api/assets", tags=["assets"])


def asset_to_out(asset: Asset) -> AssetOut:
    preview_url = None
    if asset.processed_preview_filename:
        preview_url = f"/files/processed/{asset.id}/{asset.processed_preview_filename}"

    mesh_url = None
    if asset.mesh_filename:
        mesh_url = f"/files/processed/{asset.id}/{asset.mesh_filename}"

    mesh_extra_url = None
    if asset.mesh_extra_filename:
        mesh_extra_url = f"/files/processed/{asset.id}/{asset.mesh_extra_filename}"

    summary = json.loads(asset.feature_summary) if asset.feature_summary else None
    mesh_summary = json.loads(asset.mesh_summary) if asset.mesh_summary else None

    return AssetOut(
        id=asset.id,
        original_filename=asset.original_filename,
        file_kind=asset.file_kind,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        page_count=asset.page_count,
        route=asset.route,
        original_file_url=f"/files/uploads/{asset.stored_filename}",
        processing_status=asset.processing_status,
        processing_error=asset.processing_error,
        processed_preview_url=preview_url,
        feature_summary=summary,
        mesh_status=asset.mesh_status,
        mesh_error=asset.mesh_error,
        mesh_url=mesh_url,
        mesh_extra_url=mesh_extra_url,
        mesh_summary=mesh_summary,
        created_at=asset.created_at,
    )


@router.post("/upload", response_model=AssetOut)
async def upload_asset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> AssetOut:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    extracted = await save_upload(file)

    asset = Asset(
        original_filename=file.filename,
        stored_filename=extracted.stored_filename,
        file_kind=extracted.file_kind,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=extracted.size_bytes,
        width=extracted.width,
        height=extracted.height,
        page_count=extracted.page_count,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset_to_out(asset)


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(asset_id: str, db: Session = Depends(get_db)) -> AssetOut:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset_to_out(asset)


@router.post("/{asset_id}/route", response_model=AssetOut)
def set_asset_route(asset_id: str, body: SetRouteIn, db: Session = Depends(get_db)) -> AssetOut:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    new_route = body.route.value
    if asset.route != new_route:
        # Phase 2/3 outputs (preview filenames, feature summaries, mesh files)
        # are only meaningful for the route they were generated under. Without
        # this, switching routes after processing leaves stale state around —
        # e.g. an asset re-routed to real_object would still point at a
        # previous run's dieline mesh file.
        asset.route = new_route
        asset.processing_status = "unprocessed"
        asset.processing_error = None
        asset.processed_preview_filename = None
        asset.feature_summary = None
        asset.mesh_status = "unbuilt"
        asset.mesh_error = None
        asset.mesh_filename = None
        asset.mesh_extra_filename = None
        asset.mesh_summary = None

        output_dir = processed_dir_for(asset.id)
        shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

    db.commit()
    db.refresh(asset)
    return asset_to_out(asset)


@router.post("/{asset_id}/process", response_model=AssetOut)
def process_asset(asset_id: str, db: Session = Depends(get_db)) -> AssetOut:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.route is None:
        raise HTTPException(status_code=400, detail="Asset must be routed before processing")

    original_path = UPLOAD_DIR / asset.stored_filename
    output_dir = processed_dir_for(asset.id)

    try:
        # Each route's processing module pulls in a distinct, heavy dependency
        # stack (opencv/rembg/onnxruntime, or opencv/scikit-image, or
        # opencv/shapely/networkx) — importing all three eagerly at app startup
        # was pushing baseline memory to ~480MB/512MB on a constrained deploy
        # tier before a single request ran. Importing only the route actually
        # used keeps a given container from paying for engines it never touches.
        if asset.route == "real_object":
            if asset.file_kind not in ("png", "jpg"):
                raise ValueError("Real Object pipeline requires a PNG or JPG photo")
            from app.processing import real_object

            result = real_object.process(original_path, output_dir)
        elif asset.route == "flat_graphic":
            from app.processing import flat_graphic

            result = flat_graphic.process(original_path, asset.file_kind, output_dir)
        elif asset.route == "packaging_dieline":
            from app.processing import dieline

            result = dieline.process(original_path, asset.file_kind, output_dir)
        else:
            raise ValueError(f"Unknown route '{asset.route}'")
    except Exception as exc:
        asset.processing_status = "error"
        asset.processing_error = str(exc)
        db.commit()
        db.refresh(asset)
        raise HTTPException(status_code=422, detail=f"Processing failed: {exc}") from exc

    asset.processing_status = "done"
    asset.processing_error = None
    asset.processed_preview_filename = result.preview_filename
    asset.feature_summary = json.dumps(result.summary)
    (output_dir / "features.json").write_text(json.dumps(result.features))

    db.commit()
    db.refresh(asset)
    return asset_to_out(asset)


@router.get("/{asset_id}/features")
def get_asset_features(asset_id: str, db: Session = Depends(get_db)) -> dict:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    features_path = processed_dir_for(asset.id) / "features.json"
    if not features_path.exists():
        raise HTTPException(status_code=404, detail="Asset has not been processed yet")

    return json.loads(features_path.read_text())


@router.post("/{asset_id}/generate-mesh", response_model=AssetOut)
def generate_mesh(asset_id: str, db: Session = Depends(get_db)) -> AssetOut:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    if asset.processing_status != "done":
        raise HTTPException(
            status_code=400, detail="Asset must complete Phase 2 processing before mesh generation"
        )

    output_dir = processed_dir_for(asset.id)
    features_path = output_dir / "features.json"
    features = json.loads(features_path.read_text()) if features_path.exists() else {}

    try:
        if asset.route == "real_object":
            from app.mesh import real_object as mesh_real_object

            cutout_path = output_dir / asset.processed_preview_filename
            result = mesh_real_object.generate(cutout_path, output_dir)
        elif asset.route == "flat_graphic":
            from app.mesh import flat_graphic as mesh_flat_graphic

            original_path = UPLOAD_DIR / asset.stored_filename
            result = mesh_flat_graphic.generate(features, original_path, output_dir)
        elif asset.route == "packaging_dieline":
            from app.mesh import dieline as mesh_dieline

            original_path = UPLOAD_DIR / asset.stored_filename
            result = mesh_dieline.generate(features, original_path, output_dir)
        else:
            raise ValueError(f"Unknown route '{asset.route}'")
    except Exception as exc:
        asset.mesh_status = "error"
        asset.mesh_error = str(exc)
        db.commit()
        db.refresh(asset)
        raise HTTPException(status_code=422, detail=f"Mesh generation failed: {exc}") from exc

    asset.mesh_status = "done"
    asset.mesh_error = None
    asset.mesh_filename = result.mesh_filename
    asset.mesh_extra_filename = result.extra_filename
    asset.mesh_summary = json.dumps(result.summary)
    if result.features is not None:
        (output_dir / "mesh_features.json").write_text(json.dumps(result.features))

    db.commit()
    db.refresh(asset)
    return asset_to_out(asset)


@router.get("/{asset_id}/mesh-features")
def get_mesh_features(asset_id: str, db: Session = Depends(get_db)) -> dict:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    mesh_features_path = processed_dir_for(asset.id) / "mesh_features.json"
    if not mesh_features_path.exists():
        raise HTTPException(status_code=404, detail="Asset has no mesh feature data")

    return json.loads(mesh_features_path.read_text())


@router.get("/{asset_id}/artwork.png")
def get_asset_artwork(asset_id: str, db: Session = Depends(get_db)) -> Response:
    """A clean (no overlay) raster of the original upload, for use as a Three.js
    texture on the client — vector inputs are rendered at a fixed target width;
    raster inputs are returned as-is (re-encoded to PNG)."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    original_path = UPLOAD_DIR / asset.stored_filename

    if asset.file_kind in ("svg", "pdf"):
        page = fitz.open(str(original_path))[0]
        reference_size = (page.rect.width, page.rect.height)
    else:
        reference_size = (1.0, 1.0)  # unused for raster inputs

    image = rasterize_artwork(original_path, asset.file_kind, reference_size)

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
