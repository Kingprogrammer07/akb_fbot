"""Staff payment summary for a client's sent cargo in one flight.

``CargoService.calculate_flight_payment`` used to call the async
``get_usd_rate`` without a session and without ``await``, so every priced
cargo failed and the payment-summary route answered with a 500.
"""

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.services.verification import CargoService
from src.infrastructure.database.models.flight_cargo import FlightCargo
from src.infrastructure.database.models.static_data import StaticData

CLIENT_CODE = "A5"
FLIGHT = "M100"
PRICE_PER_KG_USD = 8.0
USD_RATE = 12500.0
EXTRA_CHARGE = 1000
PARCELS = (("2.00", "YT1000000001"), ("0.50", "YT1000000002"))
"""``(weight in kg, track code)`` of each sent parcel."""


async def test_sent_cargo_is_priced_with_the_configured_usd_rate(
    db_session: AsyncSession,
) -> None:
    # A custom rate keeps get_usd_rate away from the currency API.
    db_session.add(
        StaticData(
            id=1,
            use_custom_rate=True,
            custom_usd_rate=USD_RATE,
            extra_charge=EXTRA_CHARGE,
        )
    )
    db_session.add_all(
        FlightCargo(
            flight_name=FLIGHT,
            client_id=CLIENT_CODE,
            photo_file_ids="[]",
            weight_kg=Decimal(weight),
            price_per_kg=Decimal(str(PRICE_PER_KG_USD)),
            is_sent=True,
            comment=track_code,
        )
        for weight, track_code in PARCELS
    )
    await db_session.commit()

    summary = await CargoService.calculate_flight_payment(
        [CLIENT_CODE], FLIGHT, db_session
    )

    assert summary is not None
    assert summary.total_weight == 2.5
    assert summary.price_per_kg_uzs == PRICE_PER_KG_USD * USD_RATE
    # The extra charge is added once per priced parcel.
    assert summary.total_payment == 2.5 * PRICE_PER_KG_USD * USD_RATE + 2 * EXTRA_CHARGE
    assert sorted(summary.track_codes) == [track for _weight, track in PARCELS]
