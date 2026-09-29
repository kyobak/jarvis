"""Music (F6): now-playing panel, voice control, ducking while Jarvis speaks, wake-up playlist."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Protocol

from jarvis.brain.context import Context
from jarvis.brain.timeparse import to_int
from jarvis.brain.tools import Tool, ToolRegistry, schema
from jarvis.core.event_bus import EventBus
from jarvis.core.korean import euro, obj, topic
from jarvis.core.status import StatusBoard

log = logging.getLogger(__name__)

POLL_SEC = 3.0
DUCK_VOLUME = 30


class Player(Protocol):
    name: str

    async def state(self) -> dict[str, Any] | None: ...
    async def play(self) -> None: ...
    async def pause(self) -> None: ...
    async def next(self) -> None: ...
    async def previous(self) -> None: ...
    async def set_volume(self, volume: int) -> None: ...
    async def play_uri(self, uri: str) -> None: ...


PLAY_VERBS = r"(틀어|재생해|들려|켜)\s*(줘|줄래|주세요|줘요)"


class MusicService:
    def __init__(
        self,
        bus: EventBus,
        status: StatusBoard,
        player: Player | None,
        aliases: dict[str, str],
        search: Any = None,  # SpotifySearch, optional
        configured_search: bool = False,
    ) -> None:
        self.bus = bus
        self.status = status
        self.player = player
        self.aliases = {k: v for k, v in aliases.items() if v and "XXXX" not in v and "YYYY" not in v}
        self.search = search
        self.configured_search = configured_search
        self.current: dict[str, Any] | None = None
        self._ducked_from: int | None = None
        self._task: asyncio.Task | None = None
        self._fails = 0

    async def start(self) -> None:
        if self.player is None:
            await self.status.update(integrations={"spotify": "disabled"})
            await self.bus.publish("now_playing", {"title": None})
            return
        await self.refresh()
        self._task = asyncio.create_task(self._poll(), name="music-poll")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(POLL_SEC)
            await self.refresh()

    async def refresh(self) -> None:
        if self.player is None:
            return
        try:
            state = await self.player.state()
            self._fails = 0
        except Exception as e:
            self._fails += 1
            if self._fails == 3:
                log.warning("spotify unreachable: %s", e)
                await self.status.update(integrations={"spotify": "error"})
            return
        self.current = state
        await self.status.update(integrations={"spotify": "mock" if self.player.name == "mock" else "ok"})
        payload = {"title": None} if not state else {**state, "updated_at": int(time.time() * 1000)}
        await self.bus.publish("now_playing", payload)

    # ---- actions ---------------------------------------------------------------------------

    async def control(self, action: str, value: int | None = None) -> str:
        if self.player is None:
            return "Spotify가 연결되지 않았어요."
        p = self.player
        if action == "play":
            await p.play()
            reply = "다시 틀게요."
        elif action == "pause":
            await p.pause()
            reply = "음악을 멈췄어요."
        elif action == "next":
            await p.next()
            reply = "다음 곡으로 넘길게요."
        elif action == "previous":
            await p.previous()
            reply = "이전 곡으로 갈게요."
        elif action == "volume":
            vol = max(0, min(100, int(value if value is not None else 50)))
            await p.set_volume(vol)
            self._ducked_from = None
            reply = f"볼륨을 {euro(str(vol))} 맞췄어요."
        else:
            return "그 동작은 할 수 없어요."
        await asyncio.sleep(0.3)
        await self.refresh()
        return reply

    async def play_request(self, query: str) -> str:
        if self.player is None:
            return "Spotify가 연결되지 않았어요."
        q = query.strip()
        for alias, uri in self.aliases.items():
            if alias in q:
                await self.player.play_uri(uri)
                await self.refresh()
                return f"{alias} 플레이리스트를 틀게요."
        if self.search is None:
            if self.configured_search:
                return "Spotify 검색을 쓰려면 화면의 Spotify 연결을 먼저 해 주세요."
            return "검색 연결이 없어서 등록된 별칭 플레이리스트만 틀 수 있어요."
        try:
            found = await self.search.find(q)
        except Exception as e:
            log.warning("spotify search failed: %s", e)
            return "Spotify 검색에 실패했어요. 잠시 후 다시 말씀해 주세요."
        if not found:
            return f"{q}에 맞는 음악을 찾지 못했어요."
        await self.player.play_uri(found["uri"])
        await self.refresh()
        kind = "플레이리스트" if found["kind"] == "playlist" else "곡"
        return f"{found['name']} {obj(kind)} 틀게요."

    async def duck(self) -> None:
        cur = self.current
        if self.player and cur and cur.get("is_playing") and cur.get("volume", 0) > DUCK_VOLUME:
            self._ducked_from = cur["volume"]
            try:
                await self.player.set_volume(DUCK_VOLUME)
            except Exception:
                self._ducked_from = None

    async def unduck(self) -> None:
        if self.player and self._ducked_from is not None:
            volume, self._ducked_from = self._ducked_from, None
            try:
                await self.player.set_volume(volume)
            except Exception:
                log.warning("could not restore spotify volume")

    async def wake_up(self) -> None:
        uri = self.aliases.get("기상")
        if self.player and uri:
            await self.player.play_uri(uri)
            await self.player.set_volume(80)

    # ---- voice ------------------------------------------------------------------------------

    async def handle(self, text: str, key: str, ctx: Context) -> str | None:
        music = r"(음악|노래|스포티파이|spotify)"
        if re.fullmatch(rf"({music}(좀)?)?(멈춰|멈춰줘|정지|정지해줘|꺼|꺼줘|일시정지|일시정지해줘|그만|그만틀어)", key) and (
            re.match(music, key) or key.startswith(("멈춰", "정지", "일시정지"))
        ):
            return await self.control("pause")
        if re.fullmatch(rf"({music}(좀)?(다시)?(틀어|켜|재생해)(줘|줄래)?|다시(틀어|재생해|켜)(줘|줄래)?|다시재생(해줘)?|재생(해줘)?|계속(틀어|재생해)(줘)?)", key):
            return await self.control("play")
        if re.fullmatch(r"(다음|다음곡|다음노래|넘겨|스킵|skip)(으로)?(넘겨|틀어|해)?(줘)?", key):
            return await self.control("next")
        if re.fullmatch(r"(이전|이전곡|전곡|앞곡|이전노래)(으로)?(틀어|돌려|해)?(줘)?", key):
            return await self.control("previous")
        m = re.search(r"(볼륨|소리|음량)(을|를)?(\d+|[일이삼사오육칠팔구십백]+)(으로|로)?(맞춰|해|줄여|올려|키워)?", key)
        if m:
            raw = m.group(3)
            value = int(raw) if raw.isdigit() else (100 if raw == "백" else to_int(raw) or 50)
            return await self.control("volume", value)
        if re.search(r"(볼륨|소리|음량)(좀)?(키워|올려|크게|높여)", key) or re.search(r"(볼륨|소리|음량)(좀)?(줄여|내려|작게|낮춰)", key):
            up = bool(re.search(r"(키워|올려|크게|높여)", key))
            base = (self.current or {}).get("volume", 50)
            return await self.control("volume", base + (15 if up else -15))
        if re.fullmatch(r"(지금|이|방금)?(나오는|재생중인|틀어진)?(이)?(노래|곡|음악)(제목)?(이|은)?(뭐|뭐야|뭐지|알려줘)", key):
            cur = self.current
            if not cur or not cur.get("title"):
                return "지금 재생 중인 음악이 없어요."
            return f"{cur['artist']}의 {topic(cur['title'])} 지금 재생 중이에요."
        m = re.search(rf"^(.+?)\s*(을|를)?\s*{PLAY_VERBS}\s*[.!?]*$", text)
        if m:
            query = re.sub(r"^(스포티파이에서|스포티파이로|spotify에서)\s*", "", m.group(1)).strip()
            query = re.sub(r"\s*(좀|한번|한 번)$", "", query)
            if query and not re.fullmatch(r"(음악|노래|아무거나|아무 노래|다시|이거|그거|저거|계속|그 노래|이 노래)", query):
                return await self.play_request(query)
        return None

    def register_tools(self, tools: ToolRegistry) -> None:
        async def spotify_control(args: dict[str, Any]) -> dict[str, Any]:
            value = args.get("value")
            return {"result": await self.control(args["action"], None if value in (None, -1) else int(value))}

        async def spotify_play(args: dict[str, Any]) -> dict[str, Any]:
            return {"result": await self.play_request(str(args["query_or_alias"]))}

        async def get_now_playing(_: dict[str, Any]) -> dict[str, Any]:
            cur = self.current or {}
            return {k: cur.get(k) for k in ("title", "artist", "album", "is_playing", "volume")}

        tools.register(Tool(
            "spotify_control", "Spotify 재생 제어. action: play|pause|next|previous|volume, value는 volume일 때 0-100 (그 외 -1).",
            schema({"action": {"type": "string", "enum": ["play", "pause", "next", "previous", "volume"]},
                    "value": {"type": "integer"}}, ["action", "value"]),
            spotify_control,
        ))
        tools.register(Tool(
            "spotify_play", "검색어(예: 잔잔한 재즈) 또는 등록된 별칭(예: 공부)으로 음악을 튼다.",
            schema({"query_or_alias": {"type": "string"}}, ["query_or_alias"]), spotify_play,
        ))
        tools.register(Tool("get_now_playing", "지금 재생 중인 곡 정보.", schema(), get_now_playing))
