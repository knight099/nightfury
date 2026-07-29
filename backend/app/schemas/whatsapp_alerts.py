from pydantic import BaseModel


class WhatsAppAlertContact(BaseModel):
    id: str
    number: str
    enabled: bool


class CreateWhatsAppAlertContactRequest(BaseModel):
    number: str


class UpdateWhatsAppAlertContactRequest(BaseModel):
    number: str | None = None
    enabled: bool | None = None
