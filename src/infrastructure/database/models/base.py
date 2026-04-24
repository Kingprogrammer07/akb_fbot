from datetime import datetime

from sqlalchemy import TIMESTAMP, Integer
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from src.infrastructure.tools.datetime_utils import get_current_time


class Base(DeclarativeBase, AsyncAttrs):
    __abstract__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=get_current_time
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=get_current_time, onupdate=get_current_time
    )
