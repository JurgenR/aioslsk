from aioslsk.configuration import Configuration
from aioslsk.settings import Settings
import os
import pytest


@pytest.fixture
def configuration(tmpdir) -> Configuration:
    settings_dir = os.path.join(tmpdir, 'settings')
    data_dir = os.path.join(tmpdir, 'data')
    return Configuration(settings_dir, data_dir)


class TestConfiguration:

    def test_init_shouldCreateDirectories(self, tmpdir):
        settings_dir = os.path.join(tmpdir, 'settings')
        data_dir = os.path.join(tmpdir, 'data')

        Configuration(settings_dir, data_dir)

        assert os.path.isdir(settings_dir) is True
        assert os.path.isdir(data_dir) is True

    def test_createSettings_shouldCreateSettingsFile(self, configuration: Configuration):
        name = 'utest'
        configuration.create_settings(name)
        assert os.path.exists(
            os.path.join(configuration.settings_directory, 'settings_{}.yaml'.format(name))
        )

    def test_loadSettings_andSettingsExist_shouldLoadSettings(self, configuration: Configuration):
        name = 'utest'
        configuration.create_settings(name)
        settings = configuration.load_settings(name, auto_create=False)
        assert settings is not None

    def test_loadSettings_andAutoCreate_shouldLoadSettings(self, configuration: Configuration):
        name = 'utest'
        settings = configuration.load_settings(name, auto_create=True)
        assert settings is not None
        assert os.path.exists(
            os.path.join(configuration.settings_directory, 'settings_{}.yaml'.format(name))
        )

    def test_loadSettings_andNoAutoCreate_shouldRaiseException(self, configuration: Configuration):
        name = 'utest'
        with pytest.raises(Exception):
            configuration.load_settings(name, auto_create=False)

    def test_saveSettings_shouldSaveSettings(self, configuration: Configuration):
        name = 'utest'
        settings_dict = {'test': 'key'}

        configuration.save_settings(name, Settings(settings_dict))
        settings = configuration.load_settings(name, auto_create=False)
        assert settings.get('test') == 'key'
