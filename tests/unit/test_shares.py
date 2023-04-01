from pyslsk.exceptions import FileNotFoundError
from pyslsk.shares import (
    extract_attributes,
    SharedDirectory,
    SharedItem,
    SharesManager,
    SharesStorage,
)
from pyslsk.settings import Settings

import pytest
from pytest_unordered import unordered
import os
from typing import List


RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources', 'shared')

MP3_FILENAME = 'Kevin_MacLeod-Galway.mp3'
FLAC_FILENAME = 'Kevin_MacLeod-Galway.flac'


DEFAULT_SETTINGS = {
    'sharing': {
        'directories': [
            RESOURCES
        ]
    }
}

SHARED_DIRECTORY = SharedDirectory('music', 'C:\\music', 'abcdef')
SHARED_ITEMS = {
    'item1': SharedItem(SHARED_DIRECTORY, 'genre\\album, release\\', 'simple band(contrib. singer) - isn\'t easy song.mp3', 0.0),
    'item2': SharedItem(SHARED_DIRECTORY, 'genre\\album release\\', 'simple band (contrib. singer) - isn\'t easy song.flac', 0.0),
    'item3': SharedItem(SHARED_DIRECTORY, 'genre\\album_release\\', 'simple_band(contributer. singer)-_isn\'t_easy_song.mp3', 0.0),
}
SHARED_DIRECTORY.items = set(SHARED_ITEMS.values())


@pytest.fixture
def manager(tmp_path):
    return SharesManager(Settings(DEFAULT_SETTINGS), SharesStorage())


@pytest.fixture
def manager_query(tmp_path):
    manager = SharesManager(Settings(DEFAULT_SETTINGS), SharesStorage())
    manager.shared_directories = [SHARED_DIRECTORY]
    manager.build_term_map(SHARED_DIRECTORY)

    return manager


class TestFunctions:

    def test_extractAttributes_MP3File_shouldReturnAttributes(self):
        filepath = os.path.join(RESOURCES, MP3_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(0, 128), (1, 15)]

    def test_extractAttributes_FLACFile_shouldReturnAttributes(self):
        filepath = os.path.join(RESOURCES, FLAC_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(1, 15), (4, 44100), (5, 16)]


class TestSharedDirectory:

    def test_getRemotePath_shouldReturnPath(self):
        alias = 'abcdef'
        shared_directory = SharedDirectory('music', r"C:\\music", alias)
        assert '@@' + alias == shared_directory.get_remote_path()

    def test_getItemByRemotePath_itemExists_shouldReturnItem(self):
        shared_directory = SharedDirectory('music', r"C:\\music", 'abcdef')
        item = SharedItem(shared_directory, 'author', 'song.mp3', 1.0)
        shared_directory.items = {item}

        remote_path = '@@abcdef\\author\\song.mp3'
        assert item == shared_directory.get_item_by_remote_path(remote_path)

    def test_getItemByRemotePath_itemNotExists_shouldRaise(self):
        shared_directory = SharedDirectory('music', r"C:\\music", 'abcdef')
        item = SharedItem(shared_directory, 'author', 'song.mp3', 1.0)
        shared_directory.items = {item}

        remote_path = '@@abcdef\\author\\song2.mp3'
        with pytest.raises(FileNotFoundError):
            shared_directory.get_item_by_remote_path(remote_path)


class TestSharesManager:

    @pytest.mark.parametrize(
        'query,expected_items',
        [
            # 1 term matching
            ('simple', ['item1', 'item2', 'item3']),
            # 1 term matching, case sensitive
            ('SIMPLE', ['item1', 'item2', 'item3']),
            # multiple terms, out of order
            ('song easy', ['item1', 'item2', 'item3']),
            # multiple terms, include part of directory and filename
            ('song album', ['item1', 'item2', 'item3']),
        ]
    )
    def test_querySimpleTerms_matching(self, manager_query: SharesManager, query: str, expected_items: List[str]):
        expected_items = [SHARED_ITEMS[item_name] for item_name in expected_items]
        actual_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)

    @pytest.mark.parametrize(
        'query',
        [
            # not fully matching term
            ('simpl'),
            # not matching because there is a seperator in between
            ('simpleband'),
            # only 1 term matches
            ('simple notfound')
        ]
    )
    def test_querySimpleTerms_notMatching(self, manager_query: SharesManager, query: str):
        actual_items = manager_query.query(query)
        assert actual_items == []

    def test_querySpecialCharactersInTerm_matching(self, manager_query: SharesManager):
        pass

    def test_querySpecialCharactersAcrossTerms(self, manager_query: SharesManager):
        pass

    def test_queryExcludeTerm(self, manager_query: SharesManager):
        pass

    def test_queryExcludeTermEdgeCases(self, manager_query: SharesManager):
        pass
