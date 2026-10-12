from pydantic import BaseModel, ConfigDict
from typing import Optional, Any

class UploadJobResponse(BaseModel):
    id: str
    status: str
    filename: str
    error_message: Optional[str] = None
    document_id: Optional[str] = None
    created_at: Optional[str] = None
    step: Optional[int] = None          # 1-5 processing step
    progress_pct: Optional[float] = None  # 0.0 – 1.0
    progress: Optional[dict] = None       # includes optional evaluation timing
    extracted_data: Optional[Any] = None  # full doc+fields when done

    model_config = ConfigDict(from_attributes=True)

class OCRResult(BaseModel):
    raw_text: str
    confidence_score: float
    language: str
    extracted_fields: dict

class DuplicateCheckResult(BaseModel):
    is_duplicate: bool
    duplicate_of: Optional[str] = None
    similarity_score: Optional[float] = None
    warning: Optional[str] = None
