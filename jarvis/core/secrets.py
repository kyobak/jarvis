"""Tokens live in the macOS Keychain (keyring); a 0600 JSON file is the fallback
when no keychain backend exists (Linux CI, some headless setups). Never in git or logs."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE = "jarvis-desk"


class SecretStore:
    def __init__(self, fallback: Path | None, use_keyring: bool = True) -> None:
        self.fallback = fallback
        self._keyring = None
        if use_keyring:
            try:
                import keyring
                from keyring.backends.fail import Keyring as FailKeyring

                if not isinstance(keyring.get_keyring(), FailKeyring):
                    self._keyring = keyring
            except Exception:  # no backend, or keyring not installed
                self._keyring = None
        self._memory: dict[str, str] = {}

    @property
    def backend(self) -> str:
        return "keychain" if self._keyring else "file" if self.fallback else "memory"

    def _load_file(self) -> dict[str, str]:
        if not self.fallback or not self.fallback.exists():
            return {}
        try:
            return json.loads(self.fallback.read_text())
        except (OSError, ValueError):
            return {}

    def _save_file(self, data: dict[str, str]) -> None:
        assert self.fallback
        self.fallback.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.fallback, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)

    def get(self, key: str) -> str | None:
        if self._keyring:
            try:
                return self._keyring.get_password(SERVICE, key)
            except Exception as e:
                log.warning("keychain read failed for %s: %s", key, type(e).__name__)
                return None
        if self.fallback:
            return self._load_file().get(key)
        return self._memory.get(key)

    def set(self, key: str, value: str) -> None:
        if self._keyring:
            self._keyring.set_password(SERVICE, key, value)
        elif self.fallback:
            data = self._load_file()
            data[key] = value
            self._save_file(data)
        else:
            self._memory[key] = value

    def delete(self, key: str) -> None:
        if self._keyring:
            try:
                self._keyring.delete_password(SERVICE, key)
            except Exception:
                pass
        elif self.fallback:
            data = self._load_file()
            if data.pop(key, None) is not None:
                self._save_file(data)
        else:
            self._memory.pop(key, None)
