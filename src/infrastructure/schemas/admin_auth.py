from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


class CheckUsernameRequest(BaseModel):
    system_username: str = Field(..., min_length=3, max_length=64)


class CheckUsernameResponse(BaseModel):
    role_name: str
    has_passkey: bool


class PinLoginRequest(BaseModel):
    system_username: str = Field(..., min_length=3, max_length=64)
    pin: str = Field(..., min_length=4, max_length=64, description="Raw PIN string")
    device_info: str | None = Field(None, description="Detailed User-Agent or device identifier")


class PinLoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    role_name: str
    admin_id: int
    home_page: str | None = None


class WebAuthnBeginRequest(BaseModel):
    """Initial request to start registering a new passkey."""
    device_name: str = Field("Unknown Device", max_length=128)


class WebAuthnBeginResponse(BaseModel):
    """Registration challenge response from server."""
    options: dict  # JSON serialized PublicKeyCredentialCreationOptions


class WebAuthnCompleteRequest(BaseModel):
    """The client's attestation response (PublicKeyCredential payload)."""
    device_name: str = Field("Unknown Device", max_length=128)
    attestation_response: dict


class WebAuthnCompleteResponse(BaseModel):
    """Successfully registered passkey."""
    message: str


class WebAuthnLoginBeginRequest(BaseModel):
    """Initial request to start logging in via passkey."""
    system_username: str = Field(..., min_length=3, max_length=64)
    device_info: str | None = Field(None)


class WebAuthnLoginBeginResponse(BaseModel):
    """Login challenge response from server."""
    options: dict  # JSON serialized PublicKeyCredentialRequestOptions


class WebAuthnLoginCompleteRequest(BaseModel):
    """The client's assertion response (PublicKeyCredential payload)."""
    system_username: str
    device_info: str | None
    assertion_response: dict


class WebAuthnLoginCompleteResponse(BaseModel):
    """Successfully logged in via passkey. Returns JWT token."""
    access_token: str
    token_type: str = "Bearer"
    role_name: str
    admin_id: int
    home_page: str | None = None


class AdminLogoutRequest(BaseModel):
    """Explicit logout requires sending an empty body or device_info."""
    device_info: str | None = None


class ChangePinRequest(BaseModel):
    """Self-service PIN change."""
    old_pin: str = Field(..., min_length=4, max_length=64)
    new_pin: str = Field(..., min_length=4, max_length=64)


class ResetPinRequest(BaseModel):
    """Super-admin resetting someone else's PIN."""
    new_pin: str = Field(..., min_length=4, max_length=64)


class MessageResponse(BaseModel):
    """Generic success message response."""
    message: str


class ErrorResponse(BaseModel):
    """Generic error response model."""
    detail: str


class MyPasskeysResponse(BaseModel):
    """Passkey registration status for the calling device."""
    has_current_device_passkey: bool
    total_passkeys: int
