from logging import getLogger
from typing import Generic, Type, TypeVar

from pydantic import BaseModel
from sqlalchemy import delete, func, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from src.infrastructure.database.models.base import Base

logger = getLogger(__name__)
T = TypeVar('T', bound=Base)


class BaseDAO(Generic[T]):
    """Base DAO for interacting with SQLAlchemy models."""

    def __init__(self, model: Type[T], session: AsyncSession):
        self.model = model
        self.session = session

    async def add(self, values: BaseModel, commit: bool = True) -> T:
        """Add a new record to the database."""
        values_dict = values.model_dump(exclude_unset=True)
        logger.debug(f'Adding {self.model.__name__} with parameters: {values_dict}')
        new_instance = self.model(**values_dict)
        self.session.add(new_instance)
        try:
            await self.session.flush()
            if commit:
                await self.session.commit()
                await self.session.refresh(new_instance)
            else:
                logger.debug(
                    f'Add operation for {self.model.__name__} (ID: {new_instance.id}) is pending commit'
                )
            logger.info(f'Added {self.model.__name__} with ID: {new_instance.id}')
            return new_instance
        except IntegrityError as e:
            await self.session.rollback()
            logger.error(f'Integrity error adding {self.model.__name__}: {e}')
            raise ValueError(f'Failed to add {self.model.__name__}: {str(e)}')
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f'Error adding {self.model.__name__}: {e}')
            raise

    async def find_one_or_none_by_id(self, data_id: int) -> T | None:
        """Find a record by its ID."""
        logger.debug(f'Searching for {self.model.__name__} with ID: {data_id}')
        try:
            query = select(self.model).filter_by(id=data_id)
            result = await self.session.execute(query)
            record = result.scalar_one_or_none()
            return record
        except SQLAlchemyError as e:
            logger.error(f'Error searching for {self.model.__name__} with ID {data_id}: {e}')
            raise

    async def find_one_or_none(self, filters: BaseModel) -> T | None:
        """Find a single record by filters."""
        filter_dict = filters.model_dump(exclude_unset=True)
        for key in filter_dict:
            if not hasattr(self.model, key):
                raise ValueError(f'Invalid filter field: {key}')
        logger.debug(f'Searching for {self.model.__name__} with filters: {filter_dict}')
        try:
            query = select(self.model).filter_by(**filter_dict)
            result = await self.session.execute(query)
            record = result.scalar_one_or_none()
            return record
        except SQLAlchemyError as e:
            logger.error(
                f'Error searching for {self.model.__name__} with filters {filter_dict}: {e}'
            )
            raise

    async def find_all(self, filters: BaseModel | None = None) -> list[T]:
        """Find all records that match the filters."""
        filter_dict = filters.model_dump(exclude_unset=True) if filters else {}
        for key in filter_dict:
            if not hasattr(self.model, key):
                raise ValueError(f'Invalid filter field: {key}')
        logger.debug(f'Finding all {self.model.__name__} with filters: {filter_dict}')
        try:
            query = select(self.model).filter_by(**filter_dict)
            result = await self.session.execute(query)
            records = result.scalars().all()
            return list(records)
        except SQLAlchemyError as e:
            logger.error(f'Error finding all {self.model.__name__}: {e}')
            raise

    async def update(self, filters: BaseModel, values: BaseModel, commit: bool = True) -> int:
        """Update records based on filters."""
        filter_dict = filters.model_dump(exclude_unset=True)
        values_dict = values.model_dump(exclude_unset=True)
        for key in filter_dict:
            if not hasattr(self.model, key):
                raise ValueError(f'Invalid filter field: {key}')
        for key in values_dict:
            if not hasattr(self.model, key):
                raise ValueError(f'Invalid value field: {key}')
        logger.debug(
            f'Updating {self.model.__name__} with filters {filter_dict} and values {values_dict}'
        )
        query = (
            update(self.model)
            .where(*[getattr(self.model, k) == v for k, v in filter_dict.items()])
            .values(**values_dict)
            .execution_options(synchronize_session='fetch')
        )
        try:
            result = await self.session.execute(query)
            if commit:
                await self.session.commit()
            else:
                logger.debug(f'Update operation for {self.model.__name__} is pending commit')
            logger.info(f'Updated {result.rowcount} {self.model.__name__} records')
            return result.rowcount  # noqa
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f'Error updating {self.model.__name__}: {e}')
            raise e

    async def delete(self, filters: BaseModel, commit: bool = True) -> int:
        """Delete records based on filters."""
        filter_dict = filters.model_dump(exclude_unset=True)
        if not filter_dict:
            logger.error('At least one filter is required for deletion')
            raise ValueError('At least one filter is required for deletion')
        for key in filter_dict:
            if not hasattr(self.model, key):
                raise ValueError(f'Invalid filter field: {key}')
        logger.debug(f'Deleting {self.model.__name__} with filters: {filter_dict}')
        query = delete(self.model).filter_by(**filter_dict)
        try:
            result = await self.session.execute(query)
            if commit:
                await self.session.commit()
            else:
                logger.debug(f'Delete operation for {self.model.__name__} is pending commit')
            logger.info(f'Deleted {result.rowcount} {self.model.__name__} records')
            return result.rowcount  # noqa
        except SQLAlchemyError as e:
            await self.session.rollback()
            logger.error(f'Error deleting {self.model.__name__}: {e}')
            raise

    async def count(self, filters: BaseModel | None = None) -> int:
        """Count records based on filters."""
        filter_dict = filters.model_dump(exclude_unset=True) if filters else {}
        for key in filter_dict:
            if not hasattr(self.model, key):
                raise ValueError(f'Invalid filter field: {key}')
        logger.debug(f'Counting {self.model.__name__} records with filters: {filter_dict}')
        try:
            query = select(func.count(self.model.id)).filter_by(**filter_dict)
            result = await self.session.execute(query)
            count = result.scalar()
            logger.info(f'Found {count} {self.model.__name__} records')
            return count
        except SQLAlchemyError as e:
            logger.error(f'Error counting {self.model.__name__} records: {e}')
            raise

    async def paginate(
        self, page: int = 1, page_size: int = 10, filters: BaseModel | None = None
    ) -> list[T]:
        """Retrieve paginated records based on filters."""
        if page < 1 or page_size <= 0:
            raise ValueError('Page and page_size must be positive')
        filter_dict = filters.model_dump(exclude_unset=True) if filters else {}
        for key in filter_dict:
            if not hasattr(self.model, key):
                raise ValueError(f'Invalid filter field: {key}')
        logger.debug(
            f'Paginating {self.model.__name__} with filters {filter_dict}, page {page}, size {page_size}'
        )
        try:
            query = select(self.model).filter_by(**filter_dict)
            result = await self.session.execute(
                query.offset((page - 1) * page_size).limit(page_size)
            )
            records = result.scalars().all()
            logger.info(f'Found {len(records)} {self.model.__name__} records on page {page}')
            return list(records)
        except SQLAlchemyError as e:
            logger.error(f'Error during pagination of {self.model.__name__}: {e}')
            raise
