"""Schemas for the live calculator endpoint."""
from pydantic import BaseModel, model_validator


class CalculatorRequest(BaseModel):
    """Input schema for cargo cost calculation."""
    is_gabarit: bool
    m: float
    x: float | None = None
    y: float | None = None
    z: float | None = None

    @model_validator(mode="after")
    def validate_dimensions(self):
        if self.is_gabarit:
            if missing := [f for f in ("x", "y", "z") if getattr(self, f) is None]:
                raise ValueError(
                    f"Dimensions {', '.join(missing)} are required when is_gabarit is true"
                )
        return self


class CalculatorResponse(BaseModel):
    """Output schema for cargo cost calculation."""
    chargeable_weight: float
    price_per_kg_usd: float
    price_per_kg_uzs: float
    estimated_price_usd: float
    estimated_price_uzs: float
