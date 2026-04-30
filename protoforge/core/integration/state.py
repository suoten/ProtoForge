import asyncio
import logging
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger(__name__)


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


_VALID_TRANSITIONS: dict[ConnectionState, set[ConnectionState]] = {
    ConnectionState.DISCONNECTED: {ConnectionState.CONNECTING},
    ConnectionState.CONNECTING: {ConnectionState.HANDSHAKING, ConnectionState.DISCONNECTED},
    ConnectionState.HANDSHAKING: {ConnectionState.CONNECTED, ConnectionState.DISCONNECTED},
    ConnectionState.CONNECTED: {ConnectionState.DISCONNECTED, ConnectionState.RECONNECTING},
    ConnectionState.RECONNECTING: {ConnectionState.CONNECTING, ConnectionState.DISCONNECTED},
}


class ConnectionStateMachine:
    def __init__(self, on_change: Callable[[ConnectionState, ConnectionState], None] | None = None):
        self._state = ConnectionState.DISCONNECTED
        self._on_change = on_change
        self._lock = asyncio.Lock()

    @property
    def state(self) -> ConnectionState:
        return self._state

    async def transition(self, new_state: ConnectionState) -> bool:
        async with self._lock:
            if new_state not in _VALID_TRANSITIONS.get(self._state, set()):
                logger.warning("Invalid state transition: %s -> %s", self._state.value, new_state.value)
                return False
            old = self._state
            self._state = new_state
            logger.info("Connection state: %s -> %s", old.value, new_state.value)
        if self._on_change:
            self._on_change(old, new_state)
        return True

    def can_connect(self) -> bool:
        return self._state == ConnectionState.DISCONNECTED

    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    def reset(self) -> None:
        self._state = ConnectionState.DISCONNECTED
