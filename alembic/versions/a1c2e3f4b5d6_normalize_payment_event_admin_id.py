"""split client_payment_events admin attribution into two single-namespace columns

Revision ID: a1c2e3f4b5d6
Revises: 8d87d0c698bd
Create Date: 2026-09-08 12:00:00.000000

Background
----------
``client_payment_events.approved_by_admin_id`` was written from two different
id namespaces:

  * the POS router (``PaymentPOSService``) wrote ``admin_accounts.id``;
  * ``PaymentService`` and the aiogram admin handlers wrote a Telegram user id.

Every reader — the cashier-log queries in ``ClientPaymentEventDAO`` and the
``cashier_id`` field on ``GET /payments/cashier-log`` and
``GET /payments/all-cashier-logs`` — filters on ``admin_accounts.id``, so the
Telegram-id rows never matched and silently fell out of per-cashier filters.

What this revision does
-----------------------
Rather than picking one namespace and discarding the other, it gives each its
own column:

  * ``approved_by_admin_id``      — ``admin_accounts.id`` only, or NULL.
  * ``approved_by_telegram_id``   — the raw Telegram id (new column).

Discarding the Telegram ids was not an option.  ``is_admin_by_telegram_id``
(``src/bot/utils/admin_access.py``) grants bot admin rights three ways: config
``ADMIN_ACCESS_IDs``, an ``admin_accounts`` row, and legacy ``clients.role``.
Two of those three produce operators with no ``admin_accounts`` row, so for
them the Telegram id is the *only* record of who took the cash.

Upgrade steps (order matters)
-----------------------------
1. Add ``approved_by_telegram_id``.
2. Copy every foreign-namespace value into it, so no Telegram id is lost.
3. Remap the ones that resolve to an admin account, by exact join.
4. NULL out whatever foreign-namespace values remain in
   ``approved_by_admin_id`` — safe only because step 2 preserved them.

Steps 2-4 share the guard ``NOT EXISTS (SELECT 1 FROM admin_accounts WHERE
id = approved_by_admin_id)``: a value that is already a valid AdminAccount PK
is never touched.  That makes the whole revision idempotent and leaves rows
written by the POS router untouched.

Postcondition: ``approved_by_admin_id`` holds an ``admin_accounts.id`` or NULL,
and nothing else.

Downgrade
---------
``approved_by_telegram_id`` doubles as the marker of which rows were
Telegram-sourced, so the reversal is exact: only rows carrying a Telegram id
are restored.  Rows booked through the HTTP flow after this revision shipped
have a NULL there and are left alone, so a late downgrade cannot corrupt
correctly-attributed new rows.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger("alembic.runtime.migration")


# revision identifiers, used by Alembic.
revision: str = 'a1c2e3f4b5d6'
down_revision: Union[str, None] = '8d87d0c698bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "client_payment_events"
_NEW_COL = "approved_by_telegram_id"

# Shared guard: the value is not (yet) an AdminAccount PK, i.e. it is a
# foreign-namespace leftover. Rows written by the POS router never match.
_IS_FOREIGN_NAMESPACE = """
    e.approved_by_admin_id IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM admin_accounts AS a WHERE a.id = e.approved_by_admin_id
    )
"""

# Step 2 — preserve every Telegram id before anything rewrites it.
_PRESERVE_SQL = f"""
UPDATE client_payment_events AS e
SET approved_by_telegram_id = e.approved_by_admin_id
WHERE e.approved_by_telegram_id IS NULL
  AND {_IS_FOREIGN_NAMESPACE}
"""

# Step 3 — Telegram id -> AdminAccount PK, for the ones that resolve.
_REMAP_SQL = f"""
UPDATE client_payment_events AS e
SET approved_by_admin_id = a.id
FROM admin_accounts AS a
JOIN clients AS c ON c.id = a.client_id
WHERE e.approved_by_admin_id = c.telegram_id
  AND {_IS_FOREIGN_NAMESPACE}
"""

# Step 4 — clear what could not be resolved. Guarded on the preserved copy so
# a value can only be cleared once it is safely recorded elsewhere.
_CLEAR_SQL = f"""
UPDATE client_payment_events AS e
SET approved_by_admin_id = NULL
WHERE e.approved_by_telegram_id IS NOT NULL
  AND {_IS_FOREIGN_NAMESPACE}
"""

# Reversal — exact, because the new column marks precisely the Telegram-sourced
# rows. Rows with a NULL there were never in the Telegram namespace.
_RESTORE_SQL = """
UPDATE client_payment_events AS e
SET approved_by_admin_id = e.approved_by_telegram_id
WHERE e.approved_by_telegram_id IS NOT NULL
"""

_COMMENT = (
    "AdminAccount DB primary key (admin_accounts.id) of the admin who booked "
    "this payment. NOT a Telegram ID. NULL = no admin account; see "
    "approved_by_telegram_id."
)
_OLD_COMMENT = "Telegram ID of admin who approved this payment"


def upgrade() -> None:
    """Split the two id namespaces into their own columns."""
    bind = op.get_bind()

    op.add_column(
        _TABLE,
        sa.Column(
            _NEW_COL,
            sa.BigInteger(),
            nullable=True,
            comment=(
                "Telegram user ID of the operator who booked this payment via "
                "the bot. NULL for HTTP-booked payments. Audit-only, never "
                "filtered on."
            ),
        ),
    )

    preserved = bind.execute(sa.text(_PRESERVE_SQL)).rowcount
    remapped = bind.execute(sa.text(_REMAP_SQL)).rowcount
    cleared = bind.execute(sa.text(_CLEAR_SQL)).rowcount

    logger.info(
        "preserved %s Telegram id(s); remapped %s row(s) to an AdminAccount PK; "
        "cleared %s unresolvable row(s) to NULL",
        preserved, remapped, cleared,
    )

    if cleared:
        logger.warning(
            "%s payment event(s) had a Telegram id with no admin_accounts row. "
            "approved_by_admin_id is now NULL for them and they will not appear "
            "in per-cashier log filters; the operator is still identified by "
            "%s. Create admin accounts for those operators to restore them to "
            "the cashier log.",
            cleared, _NEW_COL,
        )

    # Postcondition check — the whole point of the revision.
    leftover = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM client_payment_events AS e
            WHERE e.approved_by_admin_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM admin_accounts AS a
                  WHERE a.id = e.approved_by_admin_id
              )
            """
        )
    ).scalar_one()
    if leftover:
        raise RuntimeError(
            f"{_TABLE}.approved_by_admin_id still holds {leftover} value(s) that "
            f"are not an admin_accounts.id; the namespace split did not complete"
        )

    op.alter_column(
        _TABLE,
        "approved_by_admin_id",
        existing_type=sa.BigInteger(),
        existing_nullable=True,
        comment=_COMMENT,
        existing_comment=_OLD_COMMENT,
    )


def downgrade() -> None:
    """Fold the Telegram ids back into approved_by_admin_id and drop the column."""
    bind = op.get_bind()

    restored = bind.execute(sa.text(_RESTORE_SQL)).rowcount
    logger.info(
        "restored %s row(s) to the Telegram id namespace", restored
    )

    op.alter_column(
        _TABLE,
        "approved_by_admin_id",
        existing_type=sa.BigInteger(),
        existing_nullable=True,
        comment=_OLD_COMMENT,
        existing_comment=_COMMENT,
    )
    op.drop_column(_TABLE, _NEW_COL)
