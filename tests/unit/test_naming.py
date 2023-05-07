import os
import pytest
import sys
from unittest.mock import Mock, patch

from aioslsk.naming import (
    chain_strategies,
    DefaultNamingStrategy,
    KeepDirectoryStrategy,
    NumberDuplicateStrategy,
)


DEFAULT_LOCAL_PATH = 'C:\\Downloads\\' if sys.platform == 'win32' else '/users/Downloads/'


class TestDefaultNamingStrategy:

    def test_apply(self):
        remote_path = '@@abcdef\\Music\\myfile.mp3'
        local_path = 'C:\\Downloads\\'

        strategy = DefaultNamingStrategy()
        assert local_path, 'myfile.mp3' == strategy.apply(remote_path, local_path, None)


class TestKeepDirectoryStrategy:

    def test_apply(self):
        remote_path = '@@abcdef\\album\\myfile.mp3'
        local_path = DEFAULT_LOCAL_PATH
        local_filename = 'myfile.mp3'

        strategy = KeepDirectoryStrategy()
        actual_local_path, actual_local_filename = strategy.apply(
            remote_path, local_path, local_filename)

        assert os.path.join(local_path, 'album') == actual_local_path
        assert local_filename == actual_local_filename

    @pytest.mark.parametrize(
        "remote_path",
        [
            ('myfile.mp3'), # only filename
            ('@@abcdef\\myfile.mp3'), # only alias
            ('C:\\myfile.mp3'), # Windows drive
        ]
    )
    def test_apply_ignoredRemotePaths(self, remote_path: str):
        local_path = DEFAULT_LOCAL_PATH
        local_filename = 'myfile.mp3'

        strategy = KeepDirectoryStrategy()
        actual_local_path, actual_local_filename = strategy.apply(
            remote_path, local_path, local_filename)

        assert local_path == actual_local_path
        assert local_filename == actual_local_filename


class TestNumberDuplicateStrategy:

    def test_whenFileExistsNoIndices_shouldUseIndex1(self):
        filename = 'myfile.mp3'
        strategy = NumberDuplicateStrategy()

        listdir_mock = Mock(return_value=[filename])
        with patch('os.listdir', listdir_mock):
            actual_local_path, actual_local_filename = strategy.apply(
                None, DEFAULT_LOCAL_PATH, filename)

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
                None, DEFAULT_LOCAL_PATH, filename)

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
                None, DEFAULT_LOCAL_PATH, filename)

        assert DEFAULT_LOCAL_PATH == actual_local_path
        assert 'myfile (3).mp3' == actual_local_filename


class TestFunctions:

    def test_chainStrategiesDefault(self):
        remote_path = '@@abcdef\\Music\\myfile.mp3'
        local_path = DEFAULT_LOCAL_PATH

        strategies = [
            DefaultNamingStrategy()
        ]
        actual_path, actual_filename = chain_strategies(
            strategies, remote_path, local_path
        )
        assert 'myfile.mp3' == actual_filename
        assert local_path == actual_path

    def test_chainStrategiesDefaultWithNumbering(self):
        remote_path = '@@abcdef\\Music\\myfile.mp3'
        local_path = DEFAULT_LOCAL_PATH

        expected_filename = 'myfile (1).mp3'

        strategies = [
            DefaultNamingStrategy(),
            NumberDuplicateStrategy()
        ]

        with patch('os.listdir', return_value=['myfile.mp3']), patch('os.path.exists', return_value=True):
            actual_path, actual_filename = chain_strategies(
                strategies, remote_path, local_path
            )
        assert expected_filename == actual_filename
        assert local_path == actual_path
