from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from shared.logging import get_logger
from shared.state import AUDIO_INPUT_STATES, INTERRUPTIBLE_STATES, TRANSITIONS, FSMState


class TransitionError(Exception):
    def __init__(
        self, source: FSMState, target: FSMState, valid_targets: list[FSMState]
    ) -> None:
        self.source = source
        self.target = target
        self.valid_targets = valid_targets
        valid_names = ", ".join(v.value for v in valid_targets)
        super().__init__(
            f"Cannot transition from {source.value} to {target.value}. "
            f"Valid targets: {valid_names}"
        )


logger = get_logger("orchestrator.state_machine")


class StateMachine:
    def __init__(
        self,
        initial_state: FSMState = FSMState.IDLE,
        on_transition: (
            Callable[[FSMState, FSMState, str], Awaitable[None]] | None
        ) = None,
    ) -> None:
        self._state = initial_state
        self._lock = asyncio.Lock()
        self._state_enter_time = time.monotonic()
        self._consecutive_errors = 0
        self._on_transition_cb = on_transition
        self._enter_callbacks: dict[FSMState, list[Callable[[], Awaitable[None]]]] = {}
        self._exit_callbacks: dict[FSMState, list[Callable[[], Awaitable[None]]]] = {}

    @property
    def state(self) -> FSMState:
        return self._state

    @property
    def state_duration_ms(self) -> float:
        return (time.monotonic() - self._state_enter_time) * 1000

    @property
    def can_accept_audio(self) -> bool:
        return self._state in AUDIO_INPUT_STATES

    @property
    def is_interruptible(self) -> bool:
        return self._state in INTERRUPTIBLE_STATES

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    def on_enter(
        self, state: FSMState
    ) -> Callable[[Callable[[], Awaitable[None]]], Callable[[], Awaitable[None]]]:
        def decorator(
            func: Callable[[], Awaitable[None]],
        ) -> Callable[[], Awaitable[None]]:
            if state not in self._enter_callbacks:
                self._enter_callbacks[state] = []
            self._enter_callbacks[state].append(func)
            return func

        return decorator

    def on_exit(
        self, state: FSMState
    ) -> Callable[[Callable[[], Awaitable[None]]], Callable[[], Awaitable[None]]]:
        def decorator(
            func: Callable[[], Awaitable[None]],
        ) -> Callable[[], Awaitable[None]]:
            if state not in self._exit_callbacks:
                self._exit_callbacks[state] = []
            self._exit_callbacks[state].append(func)
            return func

        return decorator

    async def transition(self, target: FSMState, reason: str = "") -> bool:
        async with self._lock:
            source = self._state
            if (source, target) not in TRANSITIONS:
                valid = [k[1] for k in TRANSITIONS if k[0] == source]
                raise TransitionError(source, target, valid)
            await self._fire_exit_callbacks(source)
            self._state = target
            self._state_enter_time = time.monotonic()
            if target == FSMState.ERROR:
                self._consecutive_errors += 1
            elif source == FSMState.ERROR:
                self._consecutive_errors = 0
            await self._fire_enter_callbacks(target)
            if self._on_transition_cb is not None:
                await self._on_transition_cb(source, target, reason)
            return True

    async def force_state(self, target: FSMState, reason: str = "") -> None:
        async with self._lock:
            source = self._state
            await self._fire_exit_callbacks(source)
            self._state = target
            self._state_enter_time = time.monotonic()
            if target == FSMState.ERROR:
                self._consecutive_errors += 1
            elif source == FSMState.ERROR:
                self._consecutive_errors = 0
            await self._fire_enter_callbacks(target)
            if self._on_transition_cb is not None:
                await self._on_transition_cb(source, target, reason)

    async def reset(self) -> None:
        async with self._lock:
            source = self._state
            await self._fire_exit_callbacks(source)
            self._state = FSMState.IDLE
            self._state_enter_time = time.monotonic()
            self._consecutive_errors = 0
            await self._fire_enter_callbacks(FSMState.IDLE)
            if self._on_transition_cb is not None:
                await self._on_transition_cb(source, FSMState.IDLE, "reset")

    async def request_barge_in(self) -> bool:
        if self._state not in INTERRUPTIBLE_STATES:
            return False
        await self.transition(FSMState.INTERRUPTED, reason="barge_in")
        return True

    def should_auto_recover(self) -> bool:
        return self._consecutive_errors < 3

    async def _fire_enter_callbacks(self, state: FSMState) -> None:
        for cb in self._enter_callbacks.get(state, []):
            try:
                await cb()
            except Exception:
                logger.warning(
                    "enter callback failed", state=state.value, exc_info=True
                )

    async def _fire_exit_callbacks(self, state: FSMState) -> None:
        for cb in self._exit_callbacks.get(state, []):
            try:
                await cb()
            except Exception:
                logger.warning("exit callback failed", state=state.value, exc_info=True)
