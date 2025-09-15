

import httpx
import time
import threading
from typing import Dict

class GuardedClient(httpx.AsyncClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hard_closed = False
        self._lock = threading.Lock()

    def _ensure_open(self):
        if self._hard_closed:
            raise RuntimeError("This HTTP client has been closed and cannot be reused.")

    # Block *any* request once closed
    async def request(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ request ***** {self._hard_closed} *********")
        self._ensure_open()
        return await super().request(*args, **kwargs)

    async def send(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ send **** {self._hard_closed} **********")
        self._ensure_open()
        return await super().send(*args, **kwargs)

    async def stream(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ stream **** {self._hard_closed} **********")
        self._ensure_open()
        return await super().stream(*args, **kwargs)

    async def put(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ put **** {self._hard_closed} **********")
        self._ensure_open()
        return await super().put(*args, **kwargs)

    async def get(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ get **** {self._hard_closed} **********")
        self._ensure_open()
        return await super().get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ post **** {self._hard_closed} **********")
        self._ensure_open()
        return await super().post(*args, **kwargs)

    async def aclose(self):
        with self._lock:
            if not self._hard_closed:
                self._hard_closed = True
                await super().aclose()


class GlobalClient:

    client: GuardedClient = None
    waiter: threading.Thread = None
    ai_client = None

    clients: Dict[int, httpx.Client] = {}

    @classmethod
    def get_client(cls, key: int):
        client: httpx.Client = cls.clients.get(key, None)
        if client is None:
            raise RuntimeError(f"No httpx client for key: {key}")
        return client

    @classmethod
    def put_client(cls, key: int, client: GuardedClient):
        cls.clients[key] = client
        return client

    @classmethod
    def make_client(cls) -> GuardedClient:
        client: GuardedClient = GuardedClient()
        return client



    # @classmethod
    # async def close_client(cls):
    #     if cls.client is not None:
    #         try:
    #             await cls.client.aclose()
    #         except Exception as exc:
    #             print(f">>>>>>>>>>>>>>>>>FAIL to close: {exc}")
    #         finally:
    #             print(f">>>>>>CLOSED HTTP_CLIENT={id(cls.client)} {cls.client} {cls.client._hard_closed}")

    # @classmethod
    # def save_open_ai_client(cls, client):
    #     cls.ai_client = client
    #
    # @classmethod
    # def get_open_ai_client(cls):
    #     return cls.ai_client




