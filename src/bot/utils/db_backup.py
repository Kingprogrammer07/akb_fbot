"""Database backup utility for PostgreSQL."""
import logging
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from src.config import config

logger = logging.getLogger(__name__)


def create_database_backup() -> Path:
    """
    Create a PostgreSQL database backup using pg_dump.
    
    Returns:
        Path to the created backup file (.dump format)
        
    Raises:
        subprocess.CalledProcessError: If pg_dump fails
        FileNotFoundError: If pg_dump is not found
    """
    # Get database configuration
    db_config = config.database
    
    # Create backup filename with timestamp
    from src.infrastructure.tools.datetime_utils import get_current_time
    timestamp = get_current_time().strftime("%Y-%m-%d_%H-%M-%S")
    backup_filename = f"backup_{db_config.DB}_{timestamp}.dump"
    
    # Use system temp directory or create ./backups directory
    backups_dir = Path("./backups")
    backups_dir.mkdir(exist_ok=True)
    backup_path = backups_dir / backup_filename
    
    # Prepare pg_dump command
    # Using custom format for better compression and restore compatibility
    cmd = [
        "pg_dump",
        "--format=custom",  # Custom format (.dump)
        "--no-owner",  # Don't include ownership commands
        "--no-acl",  # Don't include access privileges
        "--verbose",  # Verbose output
        "--host", db_config.HOST,
        "--port", str(db_config.PORT),
        "--username", db_config.USER,
        "--dbname", db_config.DB,
        "--file", str(backup_path)
    ]
    
    # Set password via environment variable (secure)
    env = os.environ.copy()
    env["PGPASSWORD"] = db_config.PASSWORD.get_secret_value()
    
    logger.info(f"Creating database backup: {backup_path}")
    logger.debug(f"Backup command: pg_dump --format=custom --host={db_config.HOST} --port={db_config.PORT} --username={db_config.USER} --dbname={db_config.DB}")
    
    try:
        # Run pg_dump
        result = subprocess.run(
            cmd,
            env=env,
            check=True,
            capture_output=True,
            text=True
        )
        
        # Log verbose output if available
        if result.stdout:
            logger.debug(f"pg_dump output: {result.stdout}")
        
        # Verify backup file was created
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file was not created: {backup_path}")
        
        file_size = backup_path.stat().st_size
        logger.info(f"Backup created successfully: {backup_path} ({file_size} bytes)")
        
        return backup_path
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or str(e)
        logger.error(f"pg_dump failed: {error_msg}")
        # Clean up partial backup if exists
        if backup_path.exists():
            backup_path.unlink()
        raise
    except FileNotFoundError as e:
        if "pg_dump" in str(e):
            logger.error("pg_dump command not found. Please install PostgreSQL client tools.")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during backup: {e}", exc_info=True)
        # Clean up partial backup if exists
        if backup_path.exists():
            backup_path.unlink()
        raise


def cleanup_backup_file(backup_path: Path) -> None:
    """
    Delete backup file after sending.
    
    Args:
        backup_path: Path to backup file to delete
    """
    try:
        if backup_path.exists():
            backup_path.unlink()
            logger.info(f"Backup file deleted: {backup_path}")
    except Exception as e:
        logger.warning(f"Failed to delete backup file {backup_path}: {e}")

