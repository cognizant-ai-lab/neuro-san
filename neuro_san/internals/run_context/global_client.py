

import httpx
import time
import threading

class GuardedClient:
    def __init__(self, *args, **kwargs):
        self._orig: httpx.Client = httpx.Client(*args, **kwargs)
        self._hard_closed = False
        self._lock = threading.Lock()

    def _ensure_open(self):
        if self._hard_closed:
            raise RuntimeError("This HTTP client has been closed and cannot be reused.")

    # Block *any* request once closed
    def request(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ request ***** {self._hard_closed} *********")
        self._ensure_open()
        return self._orig.request(*args, **kwargs)

    def send(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ send **** {self._hard_closed} **********")
        self._ensure_open()
        return self._orig.send(*args, **kwargs)

    def stream(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ stream **** {self._hard_closed} **********")
        self._ensure_open()
        return self._orig.stream(*args, **kwargs)

    def put(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ put **** {self._hard_closed} **********")
        self._ensure_open()
        return self._orig.put(*args, **kwargs)

    def get(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ get **** {self._hard_closed} **********")
        self._ensure_open()
        return self._orig.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        print(f"^^^^^^^^^^^^^ post **** {self._hard_closed} **********")
        self._ensure_open()
        return self._orig.post(*args, **kwargs)

# class GuardedClient(httpx.Client):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self._hard_closed = False
#         self._lock = threading.Lock()
#
#     def _ensure_open(self):
#         if self._hard_closed:
#             raise RuntimeError("This HTTP client has been closed and cannot be reused.")
#
#     # Block *any* request once closed
#     def request(self, *args, **kwargs):
#         print(f"^^^^^^^^^^^^^ request ***** {self._hard_closed} *********")
#         self._ensure_open()
#         return super().request(*args, **kwargs)
#
#     def send(self, *args, **kwargs):
#         print(f"^^^^^^^^^^^^^ send **** {self._hard_closed} **********")
#         self._ensure_open()
#         return super().send(*args, **kwargs)
#
#     def stream(self, *args, **kwargs):
#         print(f"^^^^^^^^^^^^^ stream **** {self._hard_closed} **********")
#         self._ensure_open()
#         return super().stream(*args, **kwargs)
#
#     def put(self, *args, **kwargs):
#         print(f"^^^^^^^^^^^^^ put **** {self._hard_closed} **********")
#         self._ensure_open()
#         return super().put(*args, **kwargs)
#
#     def get(self, *args, **kwargs):
#         print(f"^^^^^^^^^^^^^ get **** {self._hard_closed} **********")
#         self._ensure_open()
#         return super().get(*args, **kwargs)
#
#     def post(self, *args, **kwargs):
#         print(f"^^^^^^^^^^^^^ post **** {self._hard_closed} **********")
#         self._ensure_open()
#         return super().post(*args, **kwargs)
#
#     def close(self):
#         with self._lock:
#             if not self._hard_closed:
#                 self._hard_closed = True
#                 super().close()

    def close(self):
        with self._lock:
            if not self._hard_closed:
                self._hard_closed = True
                self._orig.close()


class GlobalClient:

    client: GuardedClient = None
    waiter: threading.Thread = None

    @classmethod
    def get_client(cls):
        if cls.client is None:
            cls.client = GuardedClient()
            print(f">>>>>>CREATED HTTP_CLIENT={id(cls.client)} {cls.client} {cls.client._hard_closed}")
        else:
            print(f">>>>>>REUSED HTTP_CLIENT={id(cls.client)} {cls.client} {cls.client._hard_closed}")
        return cls.client

    @classmethod
    def close_client(cls):
        if cls.client is not None:
            try:
                cls.client.close()
            except Exception as exc:
                print(f">>>>>>>>>>>>>>>>>FAIL to close: {exc}")
            finally:
                print(f">>>>>>CLOSED HTTP_CLIENT={id(cls.client)} {cls.client} {cls.client._hard_closed}")


