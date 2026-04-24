from datetime import date
from typing import Optional
from pydantic import BaseModel, Field


class StageAvgTime(BaseModel):
    stage_name: str
    avg_days: float = Field(..., description="Average days for this stage")


class DeliveryTypeStat(BaseModel):
    delivery_type: str
    count: int
    percentage: float


class BottleneckInfo(BaseModel):
    stage_name: str
    avg_days: float


class OperationalStatsResponse(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    total_cargos_analyzed: int

    stages: list[StageAvgTime]
    delivery_types: list[DeliveryTypeStat]
    bottlenecks: list[BottleneckInfo]