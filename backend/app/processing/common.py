from dataclasses import dataclass
from typing import Any


@dataclass
class ProcessResult:
    preview_filename: str
    summary: dict[str, Any]
    features: dict[str, Any]
