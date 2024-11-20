# ========================================================================== #
#                                                                            #
#    KVMD - The main PiKVM daemon.                                           #
#                                                                            #
#    Copyright (C) 2018-2024  Maxim Devaev <mdevaev@gmail.com>               #
#                                                                            #
#    This program is free software: you can redistribute it and/or modify    #
#    it under the terms of the GNU General Public License as published by    #
#    the Free Software Foundation, either version 3 of the License, or       #
#    (at your option) any later version.                                     #
#                                                                            #
#    This program is distributed in the hope that it will be useful,         #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#    GNU General Public License for more details.                            #
#                                                                            #
#    You should have received a copy of the GNU General Public License       #
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.  #
#                                                                            #
# ========================================================================== #


import asyncio

from typing import AsyncGenerator

from ....yamlconf import Section

from .base import BaseInfoSubmanager
from .auth import AuthInfoSubmanager
from .system import SystemInfoSubmanager
from .meta import MetaInfoSubmanager
from .extras import ExtrasInfoSubmanager
from .hw import HwInfoSubmanager
from .fan import FanInfoSubmanager


# =====
class InfoManager:
    def __init__(self, config: Section) -> None:
        self.__subs: dict[str, BaseInfoSubmanager] = {
            "system": SystemInfoSubmanager(config.kvmd.streamer.cmd),
            "auth":   AuthInfoSubmanager(config.kvmd.auth.enabled),
            "meta":   MetaInfoSubmanager(config.kvmd.info.meta),
            "extras": ExtrasInfoSubmanager(config),
            "hw":     HwInfoSubmanager(**config.kvmd.info.hw._unpack()),
            "fan":    FanInfoSubmanager(**config.kvmd.info.fan._unpack()),
        }
        self.__queue: "asyncio.Queue[tuple[str, (dict | None)]]" = asyncio.Queue()

    def get_subs(self) -> set[str]:
        return set(self.__subs)

    async def get_state(self, fields: (list[str] | None)=None) -> dict:
        fields = (fields or list(self.__subs))
        return dict(zip(fields, await asyncio.gather(*[
            self.__subs[field].get_state()
            for field in fields
        ])))

    async def trigger_state(self) -> None:
        await asyncio.gather(*[
            sub.trigger_state()
            for sub in self.__subs.values()
        ])

    async def poll_state(self) -> AsyncGenerator[dict, None]:
        # ==== Granularity table ====
        #   - system -- Partial
        #   - auth   -- Partial
        #   - meta   -- Partial, nullable
        #   - extras -- Partial, nullable
        #   - hw     -- Partial
        #   - fan    -- Partial
        # ===========================

        while True:
            (field, value) = await self.__queue.get()
            yield {field: value}

    async def systask(self) -> None:
        tasks = [
            asyncio.create_task(self.__poller(field))
            for field in self.__subs
        ]
        try:
            await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def __poller(self, field: str) -> None:
        async for state in self.__subs[field].poll_state():
            self.__queue.put_nowait((field, state))
