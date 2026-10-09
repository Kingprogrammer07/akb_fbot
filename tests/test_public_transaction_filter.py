"""The client-facing transaction filter hides exactly the hidden bookkeeping rows.

``BONUS:`` and ``PENALTY:`` rows name no flight either, but clients see them,
so the filter must leave them in.
"""

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql.asyncpg import dialect as asyncpg_dialect

from src.infrastructure.database.dao.filters import apply_public_transaction_filter
from src.infrastructure.database.models.client_transaction import (
    HIDDEN_REYS_PREFIXES,
    NON_FLIGHT_REYS_PREFIXES,
    ClientTransaction,
)


def _sql(query: Select) -> str:
    return str(
        query.compile(dialect=asyncpg_dialect(), compile_kwargs={"literal_binds": True})
    )


def test_public_filter_hides_the_hidden_bookkeeping_rows_only() -> None:
    sql = _sql(apply_public_transaction_filter(select(ClientTransaction)))

    for prefix in ("UZPOST", "WALLET_ADJ:", "SYS_ADJ:"):
        assert f"client_transaction_data.reys NOT LIKE '{prefix}%'" in sql
    assert sql.count("NOT LIKE") == 3
    assert "BONUS" not in sql
    assert "PENALTY" not in sql


def test_including_hidden_rows_leaves_the_query_unfiltered() -> None:
    query = select(ClientTransaction)

    assert _sql(apply_public_transaction_filter(query, include_hidden=True)) == _sql(
        query
    )


def test_every_hidden_prefix_is_a_non_flight_prefix() -> None:
    assert set(HIDDEN_REYS_PREFIXES) < set(NON_FLIGHT_REYS_PREFIXES)
    assert set(NON_FLIGHT_REYS_PREFIXES) - set(HIDDEN_REYS_PREFIXES) == {
        "BONUS:",
        "PENALTY:",
    }
