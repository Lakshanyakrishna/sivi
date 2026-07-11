import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)

    original_filename: Mapped[str] = mapped_column(String)
    stored_filename: Mapped[str] = mapped_column(String)
    file_kind: Mapped[str] = mapped_column(String)  # png | jpg | pdf | svg
    content_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)

    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Pipeline route chosen at ingestion time: real_object | flat_graphic | packaging_dieline
    route: Mapped[str | None] = mapped_column(String, nullable=True)

    # Phase 2 processing state: unprocessed | processing | done | error
    processing_status: Mapped[str] = mapped_column(String, default="unprocessed")
    processing_error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Filename (within storage/processed/{id}/) of the primary preview image for the pipeline result
    processed_preview_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    # Small JSON blob of summary stats (counts etc.) for quick display; full data lives in features.json
    feature_summary: Mapped[str | None] = mapped_column(String, nullable=True)

    # Phase 3 mesh generation state: unbuilt | done | error
    mesh_status: Mapped[str] = mapped_column(String, default="unbuilt")
    mesh_error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Primary mesh (within storage/processed/{id}/): folded state for dielines, the only mesh otherwise
    mesh_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    # Secondary mesh, currently only used by the dieline engine (flat unfolded net)
    mesh_extra_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    mesh_summary: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
