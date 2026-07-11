from pathlib import Path

import cv2
import fitz
import numpy as np

from app.processing.common import ProcessResult

MIN_CONTOUR_AREA_FRACTION = 0.0005  # ignore specks smaller than 0.05% of image area


def _load_as_bgr(original_path: Path, file_kind: str) -> np.ndarray:
    if file_kind in ("svg", "pdf"):
        doc = fitz.open(str(original_path))
        pix = doc[0].get_pixmap(dpi=200)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    image = cv2.imread(str(original_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Could not read image at {original_path}")
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _foreground_mask(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    background_is_light = border.mean() > 127

    mode = cv2.THRESH_BINARY_INV if background_is_light else cv2.THRESH_BINARY
    _, mask = cv2.threshold(gray, 0, 255, mode + cv2.THRESH_OTSU)
    return mask


def process(original_path: Path, file_kind: str, output_dir: Path) -> ProcessResult:
    """Grayscale + threshold, then trace outer boundaries and holes with OpenCV."""
    bgr = _load_as_bgr(original_path, file_kind)
    mask = _foreground_mask(bgr)

    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

    image_area = mask.shape[0] * mask.shape[1]
    min_area = image_area * MIN_CONTOUR_AREA_FRACTION

    overlay = bgr.copy()
    contour_features = []
    outer_count = 0
    hole_count = 0

    if hierarchy is not None:
        kept_original_indices = []  # original cv2 contour index per kept entry, in output order
        for i, contour in enumerate(contours):
            area = cv2.contourArea(contour)
            if area < min_area:
                continue

            parent = hierarchy[0][i][3]
            kind = "hole" if parent != -1 else "outer"
            if kind == "outer":
                outer_count += 1
                color = (0, 200, 0)
            else:
                hole_count += 1
                color = (0, 0, 220)

            perimeter = cv2.arcLength(contour, True)
            simplified = cv2.approxPolyDP(contour, 0.005 * perimeter, True)
            points = simplified.reshape(-1, 2).tolist()

            contour_features.append(
                {
                    "type": kind,
                    "area": round(float(area), 1),
                    "points": points,
                    "parent_original_index": int(parent) if kind == "hole" else None,
                }
            )
            kept_original_indices.append(i)
            cv2.drawContours(overlay, [contour], -1, color, 2)

        # Resolve each hole's parent to its position in contour_features (not cv2's
        # original contour index), so downstream consumers (Engine B) can group
        # holes under the outer shape they belong to without re-deriving hierarchy.
        original_to_output = {orig: out for out, orig in enumerate(kept_original_indices)}
        for entry in contour_features:
            orig_parent = entry.pop("parent_original_index")
            entry["parent_index"] = (
                original_to_output.get(orig_parent) if orig_parent is not None else None
            )

    preview_filename = "contours_preview.png"
    cv2.imwrite(str(output_dir / preview_filename), overlay)

    summary = {
        "outer_count": outer_count,
        "hole_count": hole_count,
        "total_contours": outer_count + hole_count,
    }
    features = {
        "image_size": {"width": mask.shape[1], "height": mask.shape[0]},
        "contours": contour_features,
    }

    return ProcessResult(preview_filename=preview_filename, summary=summary, features=features)
