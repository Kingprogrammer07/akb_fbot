import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parent
sys.path.append(str(ROOT_DIR))

from src.config import config  # noqa: E402
from src.infrastructure.database.dao.partner import PartnerDAO  # noqa: E402


@dataclass(frozen=True)
class TargetChat:
    label: str
    chat_id: int


def add_target(targets_by_chat_id: dict[int, list[str]], label: str, chat_id: int | None) -> None:
    if chat_id is None:
        print(f"SKIP {label}: value is empty")
        return

    targets_by_chat_id.setdefault(chat_id, []).append(label)


def load_config_targets() -> dict[int, list[str]]:
    targets_by_chat_id: dict[int, list[str]] = {}

    for field_name in config.telegram.model_fields:
        if not (
            field_name.endswith("_CHANNEL_ID")
            or field_name.endswith("_GROUP_ID")
        ):
            continue

        value = getattr(config.telegram, field_name)
        add_target(targets_by_chat_id, f"config.{field_name}", value)

    return targets_by_chat_id


async def load_targets(session: AsyncSession) -> list[TargetChat]:
    targets_by_chat_id = load_config_targets()

    partners = await PartnerDAO.get_all(session)
    for partner in partners:
        if partner.group_chat_id is None:
            print(
                f"SKIP partner {partner.code} ({partner.display_name}): "
                "group_chat_id is empty"
            )
            continue

        add_target(
            targets_by_chat_id,
            f"partner.{partner.code} ({partner.display_name}).group_chat_id",
            partner.group_chat_id,
        )

    return [
        TargetChat(label=" | ".join(labels), chat_id=chat_id)
        for chat_id, labels in sorted(targets_by_chat_id.items())
    ]


async def test_target(bot: Bot, target: TargetChat) -> bool:
    text = (
        "Test message from AKB bot\n"
        f"Target: {target.label}\n"
        f"Chat ID: {target.chat_id}"
    )
    try:
        await bot.send_message(chat_id=target.chat_id, text=text)
    except TelegramAPIError as exc:
        print(f"FAIL {target.label} [{target.chat_id}]: {type(exc).__name__}: {exc}")
        return False
    except Exception as exc:
        print(f"FAIL {target.label} [{target.chat_id}]: {type(exc).__name__}: {exc}")
        return False

    print(f"OK   {target.label} [{target.chat_id}]")
    return True


async def main() -> None:
    engine = create_async_engine(config.database.database_url, echo=False)
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        async with async_session_maker() as session:
            targets = await load_targets(session)

        if not targets:
            print("No target chats found.")
            return

        bot = Bot(token=config.telegram.TOKEN.get_secret_value())
        try:
            ok_count = 0
            for target in targets:
                if await test_target(bot, target):
                    ok_count += 1

            fail_count = len(targets) - ok_count
            print("-" * 60)
            print(f"Done. OK: {ok_count}, FAIL: {fail_count}, TOTAL: {len(targets)}")
        finally:
            await bot.session.close()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
