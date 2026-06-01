import uuid
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str
    name: str
    org_name: str


class TokenResponse(BaseModel):
    token: str
    user: "UserResponse"


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    name: str
    role: str
    org_id: uuid.UUID | None
    is_active: bool
    must_change_password: bool = False

    class Config:
        from_attributes = True


class InviteRequest(BaseModel):
    username: str
    name: str
    password: str
    role: str = "viewer"
    sites_access: list[uuid.UUID] = []


class ChangePasswordRequest(BaseModel):
    new_password: str


class UpdateUserRequest(BaseModel):
    name: str | None = None
    username: str | None = None
    role: str | None = None
    is_active: bool | None = None
    org_id: uuid.UUID | None = None
    must_change_password: bool | None = None
    sites_access: list[uuid.UUID] | None = None
