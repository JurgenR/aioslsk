from pyslsk.settings import Settings


class TestSettings:

    def _create_settings(self):
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

    def test_whenSetSetting_shouldSetSetting(self):
        settings = self._create_settings()

        settings.set('first_setting', 2)

        assert settings._settings['first_setting'] == 2

    def test_whenSetNestedSetting_shouldSetSetting(self):
        settings = self._create_settings()

        settings.set('dict_setting.first', 'test')

        assert settings._settings['dict_setting']['first'] == 'test'

    def test_whenAppendListSetting_shouldAppendToListSetting(self):
        settings = self._create_settings()

        settings.append('dict_setting.list_setting', 'test')

        assert 'test' in settings._settings['dict_setting']['list_setting']

    def test_whenRemoveListSetting_shouldRemoveFromListSetting(self):
        settings = self._create_settings()

        settings.remove('dict_setting.list_setting', 'first')

        assert settings._settings['dict_setting']['list_setting'] == []

    def test_whenGetSetting_shouldReturnSetting(self):
        settings = self._create_settings()

        assert settings.get('first_setting') == 1

    def test_whenGetNestedSetting_shouldReturnSetting(self):
        settings = self._create_settings()

        assert settings.get('dict_setting.first') == 'hello'
