import asyncio

class AsyncAtomicCounter:
    def __init__(self, start=1):
        self._value = start
        self._lock = asyncio.Lock()

    async def next(self):
        async with self._lock:
            v = self._value
            self._value += 1
            return v
