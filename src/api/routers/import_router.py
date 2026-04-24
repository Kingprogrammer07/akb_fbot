"""Excel import endpoints for Uzbekistan and China databases."""
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Depends
from pydantic import BaseModel

from src.api.services.import_service import ImportService
from src.api.dependencies import get_admin_user
from src.infrastructure.database.models.client import Client

router = APIRouter(prefix="/import", tags=["import"])


class ImportResponse(BaseModel):
    """Import operation response."""
    message: str
    imported_count: int
    errors: List[str] = []


@router.post("/uz", response_model=ImportResponse)
async def import_uz_database(
    request: Request,
    excel_file: UploadFile = File(...),
    _admin: Client = Depends(get_admin_user),
) -> ImportResponse:
    """
    Import Uzbekistan (post-flight) database from Excel file.

    Expected Excel format (2 columns):
    - Column 0: client_id
    - Column 1: track_codes (comma-separated, e.g. "TRK1, TRK2")

    Multiple sheets supported. Each sheet name = flight_name.
    Each comma-separated track code creates a separate cargo item.
    """
    if not excel_file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Only .xlsx and .xls files are allowed."
        )

    try:
        # Get database session from app state
        db_client = request.app.state.db_client

        async for session in db_client.get_session():
            # Read file content
            content = await excel_file.read()

            # Initialize service
            import_service = ImportService(session)

            # Process import
            result = await import_service.import_uz_database(content, excel_file.filename)

        return ImportResponse(
            message=f"Successfully imported {result['imported_count']} items from {result['sheets_processed']} sheets.",
            imported_count=result['imported_count'],
            errors=result.get('errors', [])
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Import failed: {str(e)}"
        )


@router.post("/china", response_model=ImportResponse)
async def import_china_database(
    request: Request,
    excel_file: UploadFile = File(...),
    _admin: Client = Depends(get_admin_user),
) -> ImportResponse:
    """
    Import China (pre-flight) database from Excel file.

    Expected Excel format:
    - Column 0: date
    - Column 1: track_code
    - Column 2: item_name_cn
    - Column 3: item_name_ru
    - Column 4: quantity
    - Column 5: weight_kg
    - Column 6: client_id
    - Column 7: box_number

    Multiple sheets supported. Each sheet name = flight_name.
    Duplicate detection: skips items with same (flight_name, client_id, track_code, date).
    """
    if not excel_file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(
            status_code=400,
            detail="Invalid file format. Only .xlsx and .xls files are allowed."
        )

    try:
        # Get database session from app state
        db_client = request.app.state.db_client

        async for session in db_client.get_session():
            # Read file content
            content = await excel_file.read()

            # Initialize service
            import_service = ImportService(session)

            # Process import
            result = await import_service.import_china_database(content, excel_file.filename)

        return ImportResponse(
            message=f"Successfully imported {result['imported_count']} items from {result['sheets_processed']} sheets.",
            imported_count=result['imported_count'],
            errors=result.get('errors', [])
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Import failed: {str(e)}"
        )
