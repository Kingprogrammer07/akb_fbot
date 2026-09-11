"""
Admin identity resolution across the Telegram and AdminAccount id namespaces.

The project addresses admins by two different ids:

* **Telegram id** — what aiogram handlers see (``message.from_user.id``).
* **AdminAccount PK** — ``admin_accounts.id``, what the Admin JWT carries
  (``AdminJWTPayload.admin_id``) and what audit columns store.

Audit columns such as ``client_payment_events.approved_by_admin_id`` are defined
in the **AdminAccount PK** namespace, because that is what the RBAC layer and the
cashier-log queries filter on.  Bot handlers must therefore translate before
writing, which is what this module is for.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.dao.admin_account import AdminAccountDAO

logger = logging.getLogger(__name__)


async def resolve_admin_pk_by_telegram_id(
    session: AsyncSession,
    telegram_id: int | None,
) -> int | None:
    """
    Translate a Telegram user id into the AdminAccount primary key.

    Use this before writing any audit column that stores an AdminAccount PK from
    a bot handler.  Storing the raw Telegram id instead would put two id
    namespaces in one column and make cashier-log filtering silently wrong.

    Returns ``None`` when the id cannot be resolved (no ``from_user``, or a
    Telegram admin with no ``admin_accounts`` row — ``is_admin_by_telegram_id``
    also grants access via config ``ADMIN_ACCESS_IDs`` and legacy
    ``clients.role``, neither of which creates one).  ``None`` is deliberate: a
    NULL reads as "no admin account", whereas a Telegram id written into a PK
    column reads as *some other admin*.

    Callers writing an audit row must pass the raw Telegram id alongside, into
    ``approved_by_telegram_id``, so the operator stays identifiable when this
    returns ``None``.
    """
    if not telegram_id:
        return None

    admin_pk = await AdminAccountDAO.get_id_by_telegram_id(session, telegram_id)

    if admin_pk is None:
        logger.warning(
            "No admin_accounts row for telegram_id=%s; approved_by_admin_id "
            "will be NULL, so this action is excluded from per-cashier log "
            "filters (the operator remains identified by "
            "approved_by_telegram_id). Create an admin account for this "
            "operator to restore them to the cashier log.",
            telegram_id,
        )

    return admin_pk
