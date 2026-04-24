"""Query filter helpers for database operations."""
from sqlalchemy import or_, Select

from src.infrastructure.database.models.client_transaction import ClientTransaction


def apply_public_transaction_filter(
    query: Select, include_hidden: bool = False
) -> Select:
    """
    Apply filter to hide internal/system transactions from public-facing queries.
    
    By default, excludes:
    - UZPOST* transactions (internal delivery system transactions)
    - WALLET_ADJ:* transactions (wallet adjustment pseudo-transactions)
    - SYS_ADJ:* transactions (silent admin balance corrections)
    
    These transactions are used for internal bookkeeping and should not be
    visible to end users in transaction lists, statistics, or reports.
    
    Args:
        query: SQLAlchemy Select query to apply filter to
        include_hidden: If True, include all transactions (admin/internal use)
                       If False (default), hide UZPOST and WALLET_ADJ transactions
    
    Returns:
        Modified query with filter applied (or original query if include_hidden=True)
    
    Examples:
        >>> # Public API - hide system transactions
        >>> query = select(ClientTransaction).where(or_(ClientTransaction.client_code == code, ClientTransaction.extra_code == code))
        >>> query = apply_public_transaction_filter(query)
        
        >>> # Admin API - show all transactions including hidden ones
        >>> query = select(ClientTransaction).where(or_(ClientTransaction.client_code == code, ClientTransaction.extra_code == code))
        >>> query = apply_public_transaction_filter(query, include_hidden=True)
    
    Note:
        This filter should NOT be applied to:
        - Balance calculation queries (sum_payment_balance_difference)
        - Direct ID lookups (get_by_id)
        - Transaction creation/deletion operations
    """
    if not include_hidden:
        query = query.where(
            ~ClientTransaction.reys.like("UZPOST%"),
            ~ClientTransaction.reys.like("WALLET_ADJ:%"),
            ~ClientTransaction.reys.like("SYS_ADJ:%")
        )
    return query
