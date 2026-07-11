from pathlib import Path

import numpy as np
from PIL import Image
from rembg import remove

from app.processing.common import ProcessResult


def process(original_path: Path, output_dir: Path) -> ProcessResult:
    """Isolate the subject from its background using rembg (u2net)."""
    input_bytes = original_path.read_bytes()
    output_bytes = remove(input_bytes)

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
