from pydantic import BaseModel


class IceServer(BaseModel):
    urls: str
    username: str | None = None
    credential: str | None = None


class IceServersResponse(BaseModel):
    iceServers: list[IceServer]
