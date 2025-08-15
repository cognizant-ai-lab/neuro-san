import asyncio


class AsyncAtomicCounter:
    """
    Class implements atomic incrementing counter for async execution environment.
    """
    def __init__(self, start: int = 1):
        self._value = start
        self._lock = asyncio.Lock()

    async def next(self):
        """
        Get next counter value
        """
        async with self._lock:
            v = self._value
            self._value += 1
            return v
