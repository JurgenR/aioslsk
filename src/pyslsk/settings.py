class Settings:

    def __init__(self, settings):
        self._settings = settings

    def set(self, key: str, value):
        parts = key.split('.')

        old_value = self._settings
        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                old_value[part] = value
            else:
                old_value = old_value[part]

    def get(self, key: str):
        parts = key.split('.')
        value = self._settings

        for part in parts:
            value = value[part]

        return value

    def append(self, key: str, value):
        parts = key.split('.')

        old_value = self._settings
        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                old_value[part].append(value)
            else:
                old_value = old_value[part]

    def remove(self, key: str, value):
        parts = key.split('.')

        old_value = self._settings
        for idx, part in enumerate(parts):
            if idx == len(parts) - 1:
                old_value[part].remove(value)
            else:
                old_value = old_value[part]
