import asyncio
import logging
from typing import Callable, Awaitable, Dict, Any

from aiogram import BaseMiddleware
from aiogram.types import Message

logger = logging.getLogger(__name__)


class AlbumMiddleware(BaseMiddleware):
    """Middleware to collect media group messages into albums without breaking DB sessions."""

    def __init__(self, latency: float = 0.5):
        self.latency = latency
        self.album_data: Dict[str, list[Message]] = {}
        # Yangi xabar kelgan vaqtni saqlaymiz (debouncing uchun)
        self.album_last_time: Dict[str, float] = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        # Media guruh bo'lmasa, odatiy davom etamiz
        if not isinstance(event, Message) or not event.media_group_id:
            return await handler(event, data)

        media_group_id = event.media_group_id
        current_time = asyncio.get_event_loop().time()

        # 1. Agar bu albomdagi BIRINCHI rasm bo'lsa
        if media_group_id not in self.album_data:
            self.album_data[media_group_id] = [event]
            self.album_last_time[media_group_id] = current_time
            logger.debug(f"Created new album collection for {media_group_id}")

            # Diqqat! Async task yaratmaymiz. Birinchi xabarning zanjirini
            # ushlab turamiz, shunda DatabaseMiddleware sessiyani yopmaydi!
            try:
                while True:
                    await asyncio.sleep(0.1) # Tez-tez tekshiramiz
                    # Oxirgi rasm kelganidan beri qancha vaqt o'tdi?
                    time_since_last = asyncio.get_event_loop().time() - self.album_last_time.get(media_group_id, current_time)
                    
                    if time_since_last >= self.latency:
                        break # Kutish vaqti tugadi, pastga o'tamiz

                # Barcha rasmlarni olib, tozalaymiz
                album = self.album_data.pop(media_group_id, [])
                self.album_last_time.pop(media_group_id, None)

                if not album:
                    return None

                logger.info(f"Processing album {media_group_id} with {len(album)} messages")

                # Barcha rasmlarni yuborib, asl handler'ni chaqiramiz. 
                # (Bu vaqtda DB sessiya hali ochiq!)
                handler_data = data.copy()
                handler_data["album"] = album

                return await handler(album[0], handler_data)

            except Exception as e:
                logger.error(f"Error processing album {media_group_id}: {e}", exc_info=True)
                self.album_data.pop(media_group_id, None)
                self.album_last_time.pop(media_group_id, None)
                return None

        # 2. Agar bu albomdagi 2, 3 va keyingi rasmlar bo'lsa
        else:
            self.album_data[media_group_id].append(event)
            # Yangi rasm kelgani uchun taymerni boshiga qaytaramiz (reset)
            self.album_last_time[media_group_id] = current_time
            logger.debug(f"Album {media_group_id} now has {len(self.album_data[media_group_id])} messages")

            # Ularni to'xtatamiz (return None). Ularning DB sessiyasi bemalol yopilaveradi, 
            # chunki 1-rasm o'zining sessiyasini ushlab turibdi.
            return None