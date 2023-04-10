from aioslsk.settings import Settings

import pytest
from unittest.mock import Mock


@pytest.fixture
def settings() -> Settings:
    return Settings({
        'first_setting': 1,
        'dict_setting': {
            'first': 'hello',
            'second': 'world',
            'list_setting': [
                'first'
            ]
        }
    })


class TestSettings:

    def test_whenSetSetting_shouldSetSetting(self, settings: Settings):
        settings.set('first_setting', 2)

        assert settings._settings['first_setting'] == 2

    def test_whenSetNestedSetting_shouldSetSetting(self, settings: Settings):
        settings.set('dict_setting.first', 'test')

        assert settings._settings['dict_setting']['first'] == 'test'

    def test_whenAppendListSetting_shouldAppendToListSetting(self, settings: Settings):
        settings.append('dict_setting.list_setting', 'test')

        assert 'test' in settings._settings['dict_setting']['list_setting']

    def test_whenRemoveListSetting_shouldRemoveFromListSetting(self, settings: Settings):
        settings.remove('dict_setting.list_setting', 'first')

        assert settings._settings['dict_setting']['list_setting'] == []

    def test_whenGetSetting_shouldReturnSetting(self, settings: Settings):
        assert settings.get('first_setting') == 1

    def test_whenGetNestedSetting_shouldReturnSetting(self, settings: Settings):
        assert settings.get('dict_setting.first') == 'hello'

    def test_whenAddListener_shouldAddListener(self, settings: Settings):
        listener = Mock()
        settings.add_listener('first_setting', listener)
        assert settings.listeners == {'first_setting': [listener]}

    def test_whenAddMultipleListeners_shouldAddListeners(self, settings: Settings):
        listener1 = Mock()
        listener2 = Mock()
        settings.add_listener('first_setting', listener1)
        settings.add_listener('first_setting', listener2)
        assert settings.listeners == {'first_setting': [listener1, listener2, ]}

    def test_whenSetSetting_shouldCallListener(self, settings: Settings):
        listener = Mock()
        settings.add_listener('first_setting', listener)
        settings.set('first_setting', 10)
        listener.assert_called_once_with(10)
