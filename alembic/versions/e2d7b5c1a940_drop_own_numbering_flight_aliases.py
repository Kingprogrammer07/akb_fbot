"""partner: drop the masks minted for flights already named in a partner's own numbering

Revision ID: e2d7b5c1a940
Revises: d4b9e7a1c2f5
Create Date: 2026-09-19 00:00:00.000000

The China import names each worksheet after the number AKB tells its clients,
so ``cargo_items`` holds flights called ``AKB285``.  The ``d4b9e7a1c2f5``
backfill and the minting that followed treated those as unmasked real flights
and gave each a second number: from 11 September AKB's clients saw ``AKB285``
as ``AKB359``, and the numbers they already knew pointed at other flights -
typing ``AKB283`` into the cashier search resolved to real flight ``AKB209``.

``FlightMaskService.is_own_mask_name`` now renders such a name unchanged and
mints nothing for it, so these rows only misdirect ``mask_to_real``.  This
revision deletes exactly them: an alias whose real flight name is the owning
partner's own ``CODE<digits>`` form and whose mask differs from it.  Every
other alias is left alone - ``M280 -> AKB280``, admin overrides, and the masks
other partners carry for that same flight, which are the point of the layer.
Each deleted pair is logged, so the deploy output keeps the translation
(``AKB359`` was real flight ``AKB285``) for the curators answering clients.

``downgrade()`` is a no-op.  The rows are wrong by construction, the code no
longer creates them, and the code that ran before ``d4b9e7a1c2f5`` rendered
these names unchanged too, so a rollback needs nothing restored.
"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2d7b5c1a940"
down_revision: Union[str, None] = "d4b9e7a1c2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


logger = logging.getLogger("alembic.runtime.migration")

_OWN_NUMBERING_ALIASES = sa.text(
    """
    SELECT a.id, p.code, a.real_flight_name, a.mask_flight_name
    FROM partner_flight_aliases a
    JOIN partners p ON p.id = a.partner_id
    WHERE a.mask_flight_name <> a.real_flight_name
      -- A code with a regex metacharacter would not mean what it reads as.
      AND p.code ~ '^[A-Za-z0-9]+$'
      AND upper(a.real_flight_name) ~ ('^' || upper(p.code) || '[0-9]+$')
    ORDER BY a.id
    """
)


def upgrade() -> None:
    conn = op.get_bind()
    doomed = conn.execute(_OWN_NUMBERING_ALIASES).all()
    if not doomed:
        logger.info("drop own-numbering aliases: nothing to delete")
        return

    for row in doomed:
        logger.info(
            "drop own-numbering alias: partner %s showed real flight %s as %s",
            row.code,
            row.real_flight_name,
            row.mask_flight_name,
        )
    conn.execute(
        sa.text("DELETE FROM partner_flight_aliases WHERE id = ANY(:ids)"),
        {"ids": [row.id for row in doomed]},
    )
    logger.info("dropped %d own-numbering flight aliases", len(doomed))


def downgrade() -> None:
    """Nothing to restore: see the module docstring."""
