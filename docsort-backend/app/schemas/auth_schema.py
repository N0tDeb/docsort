from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: Optional[str] = None
    department_code: Optional[str] = None
    # Optional department UUID accepted by the API. Standard clients should
    # send department_code and let the backend resolve the UUID.
    department_id: Optional[str] = None
    designation: Optional[str] = None
    employee_id: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt_limit(cls, value: str) -> str:
        # bcrypt intentionally considers only the first 72 bytes. Reject longer
        # inputs instead of silently treating distinct passwords as equivalent.
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 UTF-8 bytes")
        return value



class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "user"


class MessageResponse(BaseModel):
    message: str


class CurrentUserResponse(BaseModel):
    id: str
    email: EmailStr
    role: str = "user"
    department_id: Optional[str] = None
    name: Optional[str] = None
    designation: Optional[str] = None
