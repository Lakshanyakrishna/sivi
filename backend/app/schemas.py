from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class FileKind(str, Enum):
    png = "png"
    jpg = "jpg"
    pdf = "pdf"
    svg = "svg"


class PipelineRoute(str, Enum):
    real_object = "real_object"
    flat_graphic = "flat_graphic"
    packaging_dieline = "packaging_dieline"


class ProcessingStatus(str, Enum):
    unprocessed = "unprocessed"
    done = "done"
    error = "error"


class MeshStatus(str, Enum):
    unbuilt = "unbuilt"
    done = "done"
    error = "error"


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_filename: str
    file_kind: FileKind
    content_type: str
    size_bytes: int
    width: float | None = None
    height: float | None = None
    page_count: int | None = None
    route: PipelineRoute | None = None
    original_file_url: str
    processing_status: ProcessingStatus
    processing_error: str | None = None
    processed_preview_url: str | None = None
    feature_summary: dict | None = None
    mesh_status: MeshStatus
    mesh_error: str | None = None
    mesh_url: str | None = None
    mesh_extra_url: str | None = None
    mesh_summary: dict | None = None
    created_at: datetime


class SetRouteIn(BaseModel):
    route: PipelineRoute
