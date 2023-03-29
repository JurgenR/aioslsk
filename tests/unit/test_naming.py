from unittest.mock import Mock, patch

from pyslsk.naming import (
    chain_strategies,
    DefaultNamingStrategy,
    NumberDuplicateStrategy,
)

DEFAULT_LOCAL_PATH = 'C:\\Music\\'


class TestDefaultNamingStrategy:

    def test_apply(self):
        remote_path = '@@abcdef\\Music\\'
        remote_filename = 'myfile.mp3'
        local_path = 'C:\\Downloads\\'

        strategy = DefaultNamingStrategy()
        assert local_path, remote_filename == strategy.apply(remote_path, remote_filename, local_path, None)


class TestNumberDuplicateStrategy:

    def test_whenFileExistsNoIndices_shouldUseIndex1(self):
        filename = 'myfile.mp3'
        strategy = NumberDuplicateStrategy()

        listdir_mock = Mock(return_value=[filename])
        with patch('os.listdir', listdir_mock):
            actual_local_path, actual_local_filename = strategy.apply(
                None, None, DEFAULT_LOCAL_PATH, filename)

        assert DEFAULT_LOCAL_PATH == actual_local_path
        assert 'myfile (1).mp3' == actual_local_filename

    def test_whenFileExistsWithIndexGap_shouldUseIndexBetweenGap(self):
        filename = 'myfile.mp3'
        strategy = NumberDuplicateStrategy()

        listdir_mock = Mock(
            return_value=[
                filename,
                'myfile (1).mp3',
                'myfile (4).mp3'
            ]
        )
        with patch('os.listdir', listdir_mock):
            actual_local_path, actual_local_filename = strategy.apply(
                None, None, DEFAULT_LOCAL_PATH, filename)

        assert DEFAULT_LOCAL_PATH == actual_local_path
        assert 'myfile (2).mp3' == actual_local_filename

    def test_whenFileExistsWithMultipleIndices_shouldUseNextIndex(self):
        filename = 'myfile.mp3'
        strategy = NumberDuplicateStrategy()

        listdir_mock = Mock(
            return_value=[
                filename,
                'myfile (1).mp3',
                'myfile (2).mp3'
            ]
        )
        with patch('os.listdir', listdir_mock):
            actual_local_path, actual_local_filename = strategy.apply(
                None, None, DEFAULT_LOCAL_PATH, filename)

        assert DEFAULT_LOCAL_PATH == actual_local_path
        assert 'myfile (3).mp3' == actual_local_filename


class TestFunctions:

    def test_chainStrategiesDefault(self):
        remote_path = '@@abcdef\\Music\\'
        remote_filename = 'myfile.mp3'
        local_path = 'C:\\Downloads\\'

        strategies = [
            DefaultNamingStrategy()
        ]
        actual_path, actual_filename = chain_strategies(
            strategies, remote_path, remote_filename, local_path
        )
        assert remote_filename == actual_filename
        assert local_path == actual_path

    def test_chainStrategiesDefaultWithNumbering(self):
        remote_path = '@@abcdef\\Music\\'
        remote_filename = 'myfile.mp3'
        local_path = 'C:\\Downloads\\'

        expected_filename = 'myfile (1).mp3'

        strategies = [
            DefaultNamingStrategy(),
            NumberDuplicateStrategy()
        ]

        with patch('os.listdir', return_value=[remote_filename]), patch('os.path.exists', return_value=True):
            actual_path, actual_filename = chain_strategies(
                strategies, remote_path, remote_filename, local_path
            )
        assert expected_filename == actual_filename
        assert local_path == actual_path
