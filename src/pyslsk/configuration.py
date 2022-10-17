import os
import shutil
import yaml

from .settings import Settings


class Configuration:

    def __init__(self, settings_directory: str, data_directory: str):
        self.settings_directory: str = settings_directory
        self.data_directory: str = data_directory

        os.makedirs(settings_directory, exist_ok=True)
        os.makedirs(data_directory, exist_ok=True)

    def _get_settings_path(self, name: str) -> str:
        return os.path.join(self.settings_directory, 'settings_{}.yaml'.format(name))

    def create_settings(self, name: str):
        shutil.copy2(Settings.DEFAULT_SETTINGS, self._get_settings_path(name))

    def load_settings(self, name: str, auto_create: bool = True) -> Settings:
        if not os.path.exists(self._get_settings_path(name)):
            if auto_create:
                self.create_settings(name)
            else:
                raise Exception(f"settings with name {name} does not exist")

        with open(self._get_settings_path(name), 'r') as fh:
            return Settings(yaml.safe_load(fh))

    def save_settings(self, name: str, settings: Settings):
        with open(self._get_settings_path(name), 'w') as fh:
            return fh.write(yaml.dump(settings._settings))
