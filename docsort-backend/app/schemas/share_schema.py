from pydantic import BaseModel, Field
from typing import Optional


class ShareLinkCreate(BaseModel):
    document_id: str
    expires_in_hours: int = Field(default=24, ge=1, le=168)
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class ShareLinkResponse(BaseModel):
    share_id: str
    url: str
    expires_at: str


class ShareLinkAccess(BaseModel):
    password: Optional[str] = Field(default=None, max_length=128)


class ShareLinkSummary(BaseModel):
    share_id: str
    expires_at: str
    is_active: bool
    created_at: Optional[str] = None
    password_protected: bool


class ShareLinkRevocationResponse(BaseModel):
    share_id: str
    is_active: bool
