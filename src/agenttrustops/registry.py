"""A small registry that exposes only explicitly governed actions."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from .ledger import SQLiteActionLedger
from .runtime import TrustedAction


class ActionRegistry:
    """Map stable public names to trusted actions sharing one ledger."""

    def __init__(
        self,
        ledger: SQLiteActionLedger,
        actions: Iterable[TrustedAction] = (),
    ):
        self.ledger = ledger
        self._actions: dict[str, TrustedAction] = {}
        for action in actions:
            self.register(action)

    def register(self, action: TrustedAction) -> TrustedAction:
        if action.ledger is not self.ledger:
            raise ValueError("registered actions must share the registry ledger")
        if action.name in self._actions:
            raise ValueError(f"action is already registered: {action.name}")
        self._actions[action.name] = action
        return action

    def get(self, name: str) -> TrustedAction:
        try:
            return self._actions[name]
        except KeyError as error:
            raise KeyError(f"unknown trusted action: {name}") from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))

    def __iter__(self) -> Iterator[TrustedAction]:
        return iter(self._actions.values())
