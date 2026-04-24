import bcrypt

def hash_pin(pin: str) -> str:
    """
    Generate a secure bcrypt hash for a plaintext PIN.
    """
    salt = bcrypt.gensalt()
    # bcrypt requires bytes, so encode both ways. 
    # Return string to store in SQLAlchemy String column.
    hashed_bytes = bcrypt.hashpw(pin.encode('utf-8'), salt)
    return hashed_bytes.decode('utf-8')

def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """
    Verify a plaintext PIN against a stored bcrypt hash.
    """
    try:
        return bcrypt.checkpw(
            plain_pin.encode('utf-8'), 
            hashed_pin.encode('utf-8')
        )
    except ValueError:
        # Expected if the hash format is invalid
        return False
