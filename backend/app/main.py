import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import assets
from app.storage import STORAGE_DIR

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sivi API", description="2D to 3D conversion pipeline: ingestion & routing")

# Always allow localhost (dev); ALLOWED_ORIGIN_REGEX adds the deployed frontend's
# origin in production (e.g. r"https://sivi.*\.vercel\.app").
_extra_origin_regex = os.environ.get("ALLOWED_ORIGIN_REGEX")
_origin_regex = r"http://(localhost|127\.0\.0\.1):\d+"
if _extra_origin_regex:
    _origin_regex = f"({_origin_regex})|({_extra_origin_regex})"

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(assets.router)
app.mount("/files", StaticFiles(directory=STORAGE_DIR), name="files")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
