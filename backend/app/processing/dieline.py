import re
from pathlib import Path
from typing import Any

import cv2
import fitz
import numpy as np
from defusedxml import ElementTree as SafeET
from PIL import Image, ImageDraw

from app.processing.common import ProcessResult

CUT_COLOR = (0, 170, 0)  # green, drawn on preview
FOLD_COLOR = (40, 90, 255)  # blue-ish, drawn on preview
UNKNOWN_COLOR = (140, 140, 140)  # gray, drawn on preview

_NAMED_COLORS = {
    "red": (1.0, 0.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "black": (0.0, 0.0, 0.0),
    "white": (1.0, 1.0, 1.0),
    "green": (0.0, 0.5, 0.0),
    "none": None,
}


def classify_color(rgb: tuple[float, float, float] | None) -> str:
    if rgb is None:
        return "other"
    r, g, b = rgb
    if r > 0.5 and r > g * 1.4 and r > b * 1.4:
        return "red"
    if b > 0.5 and b > r * 1.3 and b > g * 1.1:
        return "blue"
    if g > 0.4 and g > r * 1.3 and g > b * 1.3:
        return "green"
    return "other"


def classify_line(color_class: str, dashed: bool) -> str:
    # Red is cut regardless of dash state: a dashed-red perforation still
    # severs the material for our purposes (no hinge either way), and dash
    # detection on the raster path is unreliable enough at large image sizes
    # that requiring "not dashed" produces false "unknown" classifications
    # for lines that are actually solid (confirmed against a real
    # 4000x4000px dieline scan).
    if color_class == "red":
        return "cut"
    if color_class == "blue" and dashed:
        return "fold"
    # Solid green is a common alternate fold convention in real packaging
    # dielines (no dashing at all) — treat it as fold regardless of dash state.
    if color_class == "green":
        return "fold"
    return "unknown"


def _preview_color(line_type: str) -> tuple[int, int, int]:
    """RGB color for a line type — use directly with PIL, reverse for OpenCV (BGR)."""
    return {"cut": CUT_COLOR, "fold": FOLD_COLOR}.get(line_type, UNKNOWN_COLOR)


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")
_PATH_CMD_RE = re.compile(r"([MLHVZCSQTAmlhvzcsqta])([^MLHVZCSQTAmlhvzcsqta]*)")


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_style_prop(style: str, prop: str) -> str | None:
    for part in style.split(";"):
        if ":" not in part:
            continue
        key, _, value = part.partition(":")
        if key.strip() == prop:
            return value.strip()
    return None


def _get_attr(el, name: str) -> str | None:
    style = el.attrib.get("style")
    if style:
        val = _parse_style_prop(style, name)
        if val is not None:
            return val
    return el.attrib.get(name)


def _parse_svg_color(value: str | None) -> tuple[float, float, float] | None:
    if not value or value == "none":
        return None
    value = value.strip()
    if value in _NAMED_COLORS:
        return _NAMED_COLORS[value]
    if value.startswith("#"):
        hex_part = value[1:]
        if len(hex_part) == 3:
            hex_part = "".join(c * 2 for c in hex_part)
        if len(hex_part) == 6:
            r, g, b = (int(hex_part[i : i + 2], 16) / 255 for i in (0, 2, 4))
            return (r, g, b)
    match = re.match(r"rgb\(([^)]+)\)", value)
    if match:
        parts = [float(p.strip().rstrip("%")) for p in match.group(1).split(",")]
        return tuple(p / 255 for p in parts)  # type: ignore[return-value]
    return None


def _parse_path_d(d: str) -> tuple[list[tuple[float, float]], bool]:
    points: list[tuple[float, float]] = []
    approximated = False
    cx = cy = start_x = start_y = 0.0

    for cmd, argstr in _PATH_CMD_RE.findall(d):
        nums = [float(n) for n in _NUM_RE.findall(argstr)]
        is_relative = cmd.islower()
        upper = cmd.upper()

        def resolve(x: float, y: float) -> tuple[float, float]:
            if is_relative:
                return cx + x, cy + y
            return x, y

        if upper == "M":
            for i in range(0, len(nums) - 1, 2):
                x, y = resolve(nums[i], nums[i + 1])
                if i == 0:
                    start_x, start_y = x, y
                points.append((x, y))
                cx, cy = x, y
        elif upper == "L":
            for i in range(0, len(nums) - 1, 2):
                x, y = resolve(nums[i], nums[i + 1])
                points.append((x, y))
                cx, cy = x, y
        elif upper == "H":
            for x in nums:
                nx = cx + x if is_relative else x
                points.append((nx, cy))
                cx = nx
        elif upper == "V":
            for y in nums:
                ny = cy + y if is_relative else y
                points.append((cx, ny))
                cy = ny
        elif upper == "Z":
            points.append((start_x, start_y))
            cx, cy = start_x, start_y
        elif upper in ("C", "S", "Q", "T", "A"):
            approximated = True
            step = {"C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}[upper]
            for i in range(0, len(nums) - step + 1, step):
                x, y = resolve(nums[i + step - 2], nums[i + step - 1])
                points.append((x, y))
                cx, cy = x, y

    return points, approximated


def _get_view_box(root) -> tuple[float, float, float, float]:
    view_box = root.attrib.get("viewBox")
    if view_box:
        parts = [float(p) for p in view_box.replace(",", " ").split()]
        if len(parts) == 4:
            return tuple(parts)  # type: ignore[return-value]

    def _num(value: str | None) -> float | None:
        if not value:
            return None
        m = re.match(r"[-+]?[0-9]*\.?[0-9]+", value.strip())
        return float(m.group()) if m else None

    width = _num(root.attrib.get("width")) or 100.0
    height = _num(root.attrib.get("height")) or 100.0
    return (0.0, 0.0, width, height)


_LINE_TAGS = {"line", "polyline", "polygon", "path", "rect"}


def _element_geometry(tag: str, el) -> list[tuple[float, float]]:
    if tag == "line":
        return [
            (float(el.attrib.get("x1", 0)), float(el.attrib.get("y1", 0))),
            (float(el.attrib.get("x2", 0)), float(el.attrib.get("y2", 0))),
        ]
    if tag in ("polyline", "polygon"):
        raw = el.attrib.get("points", "").replace(",", " ").split()
        nums = [float(n) for n in raw]
        points = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
        # Unlike <polyline>, <polygon> implicitly closes (connects the last
        # point back to the first) — without this, the boundary ring is
        # missing its closing edge and downstream polygonization silently
        # merges the panel adjacent to that gap with the exterior.
        if tag == "polygon" and points and points[0] != points[-1]:
            points.append(points[0])
        return points
    if tag == "rect":
        x = float(el.attrib.get("x", 0))
        y = float(el.attrib.get("y", 0))
        w = float(el.attrib.get("width", 0))
        h = float(el.attrib.get("height", 0))
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    if tag == "path":
        points, _ = _parse_path_d(el.attrib.get("d", ""))
        return points
    return []


def _extract_svg_lines(svg_path: Path) -> tuple[list[dict[str, Any]], tuple[float, float, float, float]]:
    root = SafeET.parse(str(svg_path)).getroot()
    view_box = _get_view_box(root)
    lines = []

    for el in root.iter():
        tag = _local_tag(el.tag)
        if tag not in _LINE_TAGS:
            continue

        stroke = _get_attr(el, "stroke")
        if stroke is None or stroke == "none":
            continue

        color = _parse_svg_color(stroke)
        color_class = classify_color(color)
        dasharray = _get_attr(el, "stroke-dasharray")
        dashed = bool(dasharray and dasharray not in ("none", "0"))
        line_type = classify_line(color_class, dashed)

        points = _element_geometry(tag, el)
        if len(points) < 2:
            continue

        lines.append(
            {
                "type": line_type,
                "color": stroke,
                "dashed": dashed,
                "points": [[round(x, 2), round(y, 2)] for x, y in points],
            }
        )

    return lines, view_box


def process_svg(svg_path: Path, output_dir: Path) -> ProcessResult:
    lines, (min_x, min_y, vb_w, vb_h) = _extract_svg_lines(svg_path)

    doc = fitz.open(str(svg_path))
    pix = doc[0].get_pixmap(dpi=200)
    background = Image.frombytes(
        "RGB" if pix.n == 3 else "RGBA", (pix.width, pix.height), pix.samples
    ).convert("RGB")
    scale = pix.width / vb_w if vb_w else 1.0

    draw = ImageDraw.Draw(background)
    for line in lines:
        pts = [((x - min_x) * scale, (y - min_y) * scale) for x, y in line["points"]]
        draw.line(pts, fill=_preview_color(line["type"]), width=3)

    preview_filename = "dieline_preview.png"
    background.save(output_dir / preview_filename)

    summary = _summarize(lines, source="svg_vector")
    features = {"view_box": {"min_x": min_x, "min_y": min_y, "width": vb_w, "height": vb_h}, "lines": lines}
    return ProcessResult(preview_filename=preview_filename, summary=summary, features=features)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _extract_pdf_lines(pdf_path: Path) -> tuple[list[dict[str, Any]], tuple[float, float]]:
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    lines = []

    for drawing in page.get_drawings():
        color = drawing.get("color")
        if color is None:
            continue
        color_class = classify_color(tuple(color))
        dashes = drawing.get("dashes", "")
        dashed = bool(dashes and dashes.strip() not in ("", "[] 0"))
        line_type = classify_line(color_class, dashed)

        seen_segments: set[frozenset[tuple[float, float]]] = set()

        for item in drawing.get("items", []):
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                key = frozenset({(round(p1.x, 2), round(p1.y, 2)), (round(p2.x, 2), round(p2.y, 2))})
                if key in seen_segments:
                    continue  # fitz emits straight lines as a there-and-back pair of items
                seen_segments.add(key)
                points = [(p1.x, p1.y), (p2.x, p2.y)]
            elif kind == "re":
                rect = item[1]
                points = [
                    (rect.x0, rect.y0),
                    (rect.x1, rect.y0),
                    (rect.x1, rect.y1),
                    (rect.x0, rect.y1),
                    (rect.x0, rect.y0),
                ]
            elif kind == "c":
                points = [(item[1].x, item[1].y), (item[4].x, item[4].y)]
            else:
                continue

            lines.append(
                {
                    "type": line_type,
                    "color": [round(c, 3) for c in color],
                    "dashed": dashed,
                    "points": [[round(x, 2), round(y, 2)] for x, y in points],
                }
            )

    return lines, (page.rect.width, page.rect.height)


def process_pdf(pdf_path: Path, output_dir: Path) -> ProcessResult:
    lines, (page_w, page_h) = _extract_pdf_lines(pdf_path)

    doc = fitz.open(str(pdf_path))
    pix = doc[0].get_pixmap(dpi=200)
    background = Image.frombytes(
        "RGB" if pix.n == 3 else "RGBA", (pix.width, pix.height), pix.samples
    ).convert("RGB")
    scale = pix.width / page_w if page_w else 1.0

    draw = ImageDraw.Draw(background)
    for line in lines:
        pts = [(x * scale, y * scale) for x, y in line["points"]]
        draw.line(pts, fill=_preview_color(line["type"]), width=3)

    preview_filename = "dieline_preview.png"
    background.save(output_dir / preview_filename)

    summary = _summarize(lines, source="pdf_vector")
    features = {"page_size": {"width": page_w, "height": page_h}, "lines": lines}
    return ProcessResult(preview_filename=preview_filename, summary=summary, features=features)


# ---------------------------------------------------------------------------
# Raster (PNG) — best-effort CV fallback
# ---------------------------------------------------------------------------

_REFERENCE_DIAGONAL = 500.0  # the ~400x300 scale these defaults were tuned against


def _hough_kwargs(diagonal: float) -> dict:
    """Hough line parameters scaled to the image's own size. A fixed pixel
    length/gap tuned for a ~400x300 test image fragments every real edge into
    dozens of tiny segments on a multi-thousand-pixel scan (confirmed: a
    4079x4029 dieline produced 58 merged "cut" segments where the actual
    artwork only has a handful of straight edges), because segments more than
    ~10px apart stop merging back into one line at that resolution."""
    scale = max(diagonal / _REFERENCE_DIAGONAL, 1.0)
    return dict(
        rho=1,
        theta=np.pi / 180,
        threshold=30,
        minLineLength=max(20 * scale, 20),
        maxLineGap=max(8 * scale, 8),
    )


def _color_mask(hsv: np.ndarray, color: str) -> np.ndarray:
    if color == "red":
        lower1 = cv2.inRange(hsv, (0, 80, 50), (10, 255, 255))
        lower2 = cv2.inRange(hsv, (170, 80, 50), (180, 255, 255))
        return cv2.bitwise_or(lower1, lower2)
    if color == "green":
        return cv2.inRange(hsv, (40, 80, 50), (85, 255, 255))
    return cv2.inRange(hsv, (100, 80, 50), (130, 255, 255))


def _merge_collinear_segments(
    segments: np.ndarray,
    angle_tol_deg: float = 6.0,
    dist_tol: float = 10.0,
    gap_tol: float = 60.0,
) -> list[tuple[float, float, float, float]]:
    """Collapse near-duplicate/collinear Hough segments (common on thick or dashed
    strokes) into single spanning segments, grouped by direction + perpendicular offset.

    Segments that share a direction/offset but sit far apart along the line itself are
    NOT bridged into one segment: two unrelated marks (e.g. a real dash and an
    unrelated scan artifact) can coincidentally lie on the same infinite line, and
    spanning the empty gap between them fabricates a line where no pixels exist. Only
    chain-merge segments whose along-line gap is small enough to plausibly be dashes
    of the same stroke (gap_tol).
    """
    lines = []
    for x1, y1, x2, y2 in segments:
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        theta = np.radians(angle + 90)
        rho = x1 * np.cos(theta) + y1 * np.sin(theta)
        lines.append({"angle": angle, "rho": rho, "pts": (x1, y1, x2, y2)})

    used = [False] * len(lines)
    merged = []
    for i, li in enumerate(lines):
        if used[i]:
            continue
        group = [li]
        used[i] = True
        for j in range(i + 1, len(lines)):
            if used[j]:
                continue
            lj = lines[j]
            angle_diff = abs(li["angle"] - lj["angle"]) % 180
            angle_diff = min(angle_diff, 180 - angle_diff)
            if angle_diff <= angle_tol_deg and abs(li["rho"] - lj["rho"]) <= dist_tol:
                group.append(lj)
                used[j] = True

        angle_rad = np.radians(float(np.mean([g["angle"] for g in group])))
        dx, dy = np.cos(angle_rad), np.sin(angle_rad)

        # Chain-merge at the segment level (never split a single raw segment's own
        # endpoints apart, however long it already is) — only bridge the gap BETWEEN
        # consecutive segments, and only if that gap is small enough to plausibly be
        # a dash gap within one stroke, not a coincidentally-collinear unrelated mark.
        seg_spans = []
        for g in group:
            gx1, gy1, gx2, gy2 = g["pts"]
            p1, p2 = (gx1, gy1), (gx2, gy2)
            proj1, proj2 = p1[0] * dx + p1[1] * dy, p2[0] * dx + p2[1] * dy
            if proj1 > proj2:
                p1, p2, proj1, proj2 = p2, p1, proj2, proj1
            seg_spans.append((proj1, proj2, p1, p2))
        seg_spans.sort(key=lambda s: s[0])

        chain_min_proj, chain_max_proj, chain_start, chain_end = seg_spans[0]
        for proj1, proj2, p1, p2 in seg_spans[1:]:
            if proj1 - chain_max_proj > gap_tol:
                merged.append((chain_start[0], chain_start[1], chain_end[0], chain_end[1]))
                chain_min_proj, chain_start = proj1, p1
            if proj2 > chain_max_proj:
                chain_max_proj, chain_end = proj2, p2
        merged.append((chain_start[0], chain_start[1], chain_end[0], chain_end[1]))

    return merged


def _is_dashed(mask: np.ndarray, p1: tuple[int, int], p2: tuple[int, int]) -> bool:
    length = int(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
    if length < 4:
        return False
    xs = np.linspace(p1[0], p2[0], length).astype(int)
    ys = np.linspace(p1[1], p2[1], length).astype(int)
    xs = np.clip(xs, 0, mask.shape[1] - 1)
    ys = np.clip(ys, 0, mask.shape[0] - 1)
    on_ratio = float((mask[ys, xs] > 0).mean())
    return on_ratio < 0.85


def process_raster(image_path: Path, output_dir: Path) -> ProcessResult:
    bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"Could not read image at {image_path}")
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    overlay = bgr.copy()
    lines = []

    diagonal = float(np.hypot(bgr.shape[0], bgr.shape[1]))
    scale = max(diagonal / _REFERENCE_DIAGONAL, 1.0)
    hough_kwargs = _hough_kwargs(diagonal)
    dist_tol = 10.0 * scale
    gap_tol = 60.0 * scale
    dilate_size = int(min(max(round(3 * scale), 3), 15))

    for color_name in ("red", "blue", "green"):
        mask = _color_mask(hsv, color_name)
        mask = cv2.dilate(mask, np.ones((dilate_size, dilate_size), np.uint8), iterations=1)
        segments = cv2.HoughLinesP(mask, **hough_kwargs)
        if segments is None:
            continue

        for x1, y1, x2, y2 in _merge_collinear_segments(
            segments.reshape(-1, 4), dist_tol=dist_tol, gap_tol=gap_tol
        ):
            x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
            dashed = _is_dashed(mask, (x1, y1), (x2, y2))
            line_type = classify_line(color_name, dashed)
            lines.append(
                {
                    "type": line_type,
                    "color": color_name,
                    "dashed": dashed,
                    "points": [[x1, y1], [x2, y2]],
                }
            )
            cv2.line(overlay, (x1, y1), (x2, y2), _preview_color(line_type)[::-1], 2)

    preview_filename = "dieline_preview.png"
    cv2.imwrite(str(output_dir / preview_filename), overlay)

    summary = _summarize(lines, source="raster_cv")
    summary["confidence"] = "low"
    summary["note"] = (
        "Raster dielines are detected with color-based Hough line fitting; "
        "vector (SVG/PDF) input gives far more reliable results."
    )
    features = {"image_size": {"width": bgr.shape[1], "height": bgr.shape[0]}, "lines": lines}
    return ProcessResult(preview_filename=preview_filename, summary=summary, features=features)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _summarize(lines: list[dict[str, Any]], source: str) -> dict[str, Any]:
    cut = sum(1 for l in lines if l["type"] == "cut")
    fold = sum(1 for l in lines if l["type"] == "fold")
    unknown = sum(1 for l in lines if l["type"] == "unknown")
    return {
        "cut_count": cut,
        "fold_count": fold,
        "unknown_count": unknown,
        "total_lines": len(lines),
        "source": source,
    }


def process(original_path: Path, file_kind: str, output_dir: Path) -> ProcessResult:
    if file_kind == "svg":
        return process_svg(original_path, output_dir)
    if file_kind == "pdf":
        return process_pdf(original_path, output_dir)
    return process_raster(original_path, output_dir)
