from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional

class MatchHighlight(BaseModel):
    field: str
    value: str
    snippet: str

class SearchResultResponse(BaseModel):
    id: str
    filename: str
    doc_type: Optional[str] = None
    folder_name: Optional[str] = None
    uploaded_by: Optional[str] = None
    created_at: Optional[str] = None
    is_tampered: bool = False
    ocr_confidence: Optional[float] = None
    review_status: str = "needs_review"
    match_highlights: List[MatchHighlight] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

class SearchQuery(BaseModel):
    query: str
    department_id: Optional[str] = None
    limit: int = 20
