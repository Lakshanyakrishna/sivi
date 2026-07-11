import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree as SafeET
from fastapi import HTTPException, UploadFile
from PIL import Image
from pypdf import PdfReader

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
PROCESSED_DIR = STORAGE_DIR / "processed"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def processed_dir_for(asset_id: str) -> Path:
    d = PROCESSED_DIR / asset_id
    d.mkdir(parents=True, exist_ok=True)
    return d

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
CHUNK_SIZE = 1024 * 1024

EXTENSION_TO_KIND = {
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".pdf": "pdf",
    ".svg": "svg",
}


@dataclass
class ExtractedFile:
    stored_filename: str
    file_kind: str
    size_bytes: int
    width: float | None
    height: float | None
    page_count: int | None


def _kind_from_filename(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    kind = EXTENSION_TO_KIND.get(ext)
    if kind is None:
        allowed = ", ".join(sorted({e for e in EXTENSION_TO_KIND}))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext or '(none)'}'. Allowed: {allowed}",
        )
    return kind


def _read_svg_dimensions(path: Path) -> tuple[float | None, float | None]:
    try:
        root = SafeET.parse(str(path)).getroot()
    except Exception:
        return None, None

    def _num(value: str | None) -> float | None:
        if not value:
            return None
        match = re.match(r"[-+]?[0-9]*\.?[0-9]+", value.strip())
        return float(match.group()) if match else None

    width = _num(root.attrib.get("width"))
    height = _num(root.attrib.get("height"))

    if width is None or height is None:
        view_box = root.attrib.get("viewBox")
        if view_box:
            parts = view_box.replace(",", " ").split()
            if len(parts) == 4:
                width = width or _num(parts[2])
                height = height or _num(parts[3])

    return width, height


def _extract_metadata(kind: str, path: Path) -> tuple[float | None, float | None, int | None]:
    if kind in ("png", "jpg"):
        with Image.open(path) as img:
            w, h = img.size
            return float(w), float(h), None

    if kind == "pdf":
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        width = height = None
        if page_count > 0:
            box = reader.pages[0].mediabox
            width, height = float(box.width), float(box.height)
        return width, height, page_count

    if kind == "svg":
        width, height = _read_svg_dimensions(path)
        return width, height, None

    return None, None, None


async def save_upload(upload_file: UploadFile) -> ExtractedFile:
    kind = _kind_from_filename(upload_file.filename or "")
    ext = Path(upload_file.filename or "").suffix.lower()
    if ext == ".jpeg":
        ext = ".jpg"

    stored_filename = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / stored_filename

    size_bytes = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await upload_file.read(CHUNK_SIZE):
                size_bytes += len(chunk)
                if size_bytes > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail="File exceeds 50MB limit")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise

    if size_bytes == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        width, height, page_count = _extract_metadata(kind, dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}") from exc

    return ExtractedFile(
        stored_filename=stored_filename,
        file_kind=kind,
        size_bytes=size_bytes,
        width=width,
        height=height,
        page_count=page_count,
    )
