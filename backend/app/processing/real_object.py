import gc
import io
from pathlib import Path

import numpy as np
from PIL import Image
from rembg import new_session, remove

from app.processing.common import ProcessResult

# u2netp is rembg's ~4.7MB "portable" model vs. u2net's 176MB default — the full
# model's onnxruntime inference session can need several hundred MB of working
# memory on top of its own weights, which reliably OOMs on memory-constrained
# hosts (e.g. a 512MB deploy tier). u2netp trades some segmentation precision
# for a much smaller session, which is the tradeoff that matters here.
_SESSION = new_session("u2netp")

# Downscaling before rembg cuts both its processing memory (proportional to
# pixel count) and latency; subject silhouettes don't need original photo
# resolution; Phase 3's real_object mesh grid is capped far below this anyway.
_MAX_INPUT_DIM = 1600


def _downscaled_bytes(path: Path) -> bytes:
    with Image.open(path) as img:
        img = img.convert("RGB")
        scale = min(1.0, _MAX_INPUT_DIM / max(img.size))
        if scale < 1.0:
            new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
            img = img.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def process(original_path: Path, output_dir: Path) -> ProcessResult:
    """Isolate the subject from its background using rembg (u2netp)."""
    input_bytes = _downscaled_bytes(original_path)
    output_bytes = remove(input_bytes, session=_SESSION)
    del input_bytes
    gc.collect()

    preview_filename = "cutout.png"
    output_path = output_dir / preview_filename
    output_path.write_bytes(output_bytes)

    with Image.open(output_path) as img:
        img = img.convert("RGBA")
        width, height = img.size
        alpha = np.array(img.getchannel("A"))

    mask = alpha > 10
    coverage_pct = round(float(mask.mean()) * 100, 1)

    bbox: dict[str, int] | None = None
    if mask.any():
        ys, xs = np.where(mask)
        bbox = {
            "x": int(xs.min()),
            "y": int(ys.min()),
            "width": int(xs.max() - xs.min() + 1),
            "height": int(ys.max() - ys.min() + 1),
        }

    summary = {"subject_coverage_pct": coverage_pct, "subject_bbox": bbox}
    features = {
        "image_size": {"width": width, "height": height},
        "subject_bbox": bbox,
        "subject_coverage_pct": coverage_pct,
    }

    return ProcessResult(preview_filename=preview_filename, summary=summary, features=features)
