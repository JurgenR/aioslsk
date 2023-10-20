from __future__ import annotations
import json
import os
from typing import Any, Callable, Dict, List


RESOURCES_DIRECTORY: str = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'resources')


class Settings:
    DEFAULT_SETTINGS: str = os.path.join(RESOURCES_DIRECTORY, 'default_settings.json')

    def __init__(self, settings: dict):
        self._settings: dict = settings
        self.listeners: Dict[str, List[Callable]] = {}

    @classmethod
    def create_default(cls) -> Settings:
        """Creates a new `Settings` object from the defaults"""
        with open(cls.DEFAULT_SETTINGS, 'r') as fh:
            return Settings(json.load(fh))

    def add_listener(self, key, callback):
        if key in self.listeners:
            self.listeners[key].append(callback)
        else:
            self.listeners[key] = [callback, ]

    def call_listeners(self, key, value):
        for listener in self.listeners.get(key, []):
            listener(value)

    def set(self, key: str, value: Any):
        parts = key.split('.')

        old_value = self._settings
        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                old_value[part] = value
            else:
                old_value = old_value[part]

        self.call_listeners(key, value)

    def get(self, key: str):
        parts = key.split('.')
        value = self._settings

        for part in parts:
            value = value[part]

        return value

    def append(self, key: str, value: Any):
        parts = key.split('.')

        old_value = self._settings
        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                old_value[part].append(value)
            else:
                old_value = old_value[part]

    def remove(self, key: str, value: Any):
        parts = key.split('.')

        old_value = self._settings
        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                old_value[part].remove(value)
            else:
                old_value = old_value[part]
