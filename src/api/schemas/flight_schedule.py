"""Pydantic schemas for the Flight Schedule API."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

_FlightType = Literal["avia", "aksiya"]
_FlightStatus = Literal["arrived", "scheduled", "delayed"]


class FlightScheduleItem(BaseModel):
    """Single schedule entry returned by the API."""

    model_config = {"from_attributes": True}

    id: int
    flight_name: str
    flight_date: date
    type: _FlightType
    status: _FlightStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


class FlightScheduleListResponse(BaseModel):
    """Full year schedule returned by GET /flight-schedule."""

    year: int
    total: int
    items: list[FlightScheduleItem]


class CreateFlightScheduleRequest(BaseModel):
    """Body for POST /flight-schedule."""

    flight_name: str = Field(..., min_length=1, max_length=255)
    flight_date: date
    type: _FlightType
    status: _FlightStatus = "scheduled"
    notes: str | None = Field(None, max_length=1000)


class UpdateFlightScheduleRequest(BaseModel):
    """Body for PUT /flight-schedule/{id} — all fields optional (sparse update)."""

    flight_name: str | None = Field(None, min_length=1, max_length=255)
    flight_date: date | None = None
    type: _FlightType | None = None
    status: _FlightStatus | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UpdateFlightScheduleRequest":
        if all(
            v is None
            for v in (self.flight_name, self.flight_date, self.type, self.status, self.notes)
        ):
            raise ValueError("At least one field must be provided for update.")
        return self


class DeleteFlightScheduleResponse(BaseModel):
    """Response for DELETE /flight-schedule/{id}."""

    deleted_id: int
    message: str
