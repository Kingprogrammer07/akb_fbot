"""China address response schemas."""
from typing import List, Optional
from pydantic import BaseModel


class ChinaAddressResponse(BaseModel):
    """Structured China warehouse address for the authenticated client."""

    client_code: str
    phone: str
    region: str
    address_line: str
    full_address_string: str
    warning_text: str
    images: List[str]
