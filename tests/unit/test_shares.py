from aioslsk.events import InternalEventBus
from aioslsk.exceptions import FileNotFoundError
from aioslsk.shares import (
    extract_attributes,
    SharedDirectory,
    SharedItem,
    SharesManager,
    SharesStorage,
)
from aioslsk.settings import Settings

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
    'item1': SharedItem(SHARED_DIRECTORY, 'folk\\folkalbum, release\\', 'simple band(contrib. singer) - isn\'t easy song.mp3', 0.0),
    'item2': SharedItem(SHARED_DIRECTORY, 'metal\\metalalbum release\\', 'simple band (contrib. singer)_-_don\'t easy song 片仮名.flac', 0.0),
    'item3': SharedItem(SHARED_DIRECTORY, 'rap\\rapalbum_release\\', 'simple_band(contributer. singer)-don\'t_easy_song 片仮名.mp3', 0.0),
}
SHARED_DIRECTORY.items = set(SHARED_ITEMS.values())


@pytest.fixture
def manager(tmp_path):
    return SharesManager(Settings(DEFAULT_SETTINGS), SharesStorage(), InternalEventBus())


@pytest.fixture
def manager_query(tmp_path):
    manager = SharesManager(Settings(DEFAULT_SETTINGS), SharesStorage(), InternalEventBus())
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
            ('rap', ['item3']),
            # 1 term matching, case sensitive
            ('mETAl', ['item2']),
            # multiple terms, out of order
            ('simple folk', ['item1']),
            # multiple terms, include part of directory and filename
            ('song folkalbum', ['item1']),
            # term surrounded by special chars
            ('contrib', ['item1', 'item2']),
            # unicode characters
            ('片仮名', ['item2', 'item3'])
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
            ('simple notfound'),
            # wildcard chars no match
            ('*impler'),
            # only exclusion
            ('-mp3'),
            # only special characters
            ('____')
        ]
    )
    def test_querySimpleTerms_notMatching(self, manager_query: SharesManager, query: str):
        actual_items = manager_query.query(query)
        assert actual_items == []

    @pytest.mark.parametrize(
        'query,expected_items',
        [
            # matching simple term, and containing special chars
            ('simple isn\'t', ['item1']),
            # seperator in between
            ('simple_band', ['item3']),
        ]
    )
    def test_querySpecialCharactersInTerm_matching(self, manager_query: SharesManager, query: str, expected_items: List[str]):
        expected_items = [SHARED_ITEMS[item_name] for item_name in expected_items]
        actual_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)

    @pytest.mark.parametrize(
        'query,expected_items',
        [
            # wildcard
            ('*tributer', ['item3']),
            # wildcard special chars
            ('*on\'t', ['item2', 'item3']),
            # wildcard start of line
            ('*etal', ['item2']),
            # wildcard end of line
            ('*lac', ['item2']),
            # wildcard unicode characters
            ('*仮名', ['item2', 'item3']),
        ]
    )
    def test_queryWildcard_matching(self, manager_query: SharesManager, query: str, expected_items: List[str]):
        expected_items = [SHARED_ITEMS[item_name] for item_name in expected_items]
        actual_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)

    @pytest.mark.parametrize(
        'query,expected_items',
        [
            # exclude, start of line
            ('simple -mp3', ['item2']),
            # exclude, end of line
            ('simple -rap', ['item1', 'item2']),
            # exclude, multiple end of line
            ('simple -mp3 -contributer', ['item2']),
            # exclude unicode characters
            ('simple -片仮名', ['item1'])
        ]
    )
    def test_queryExcludeTerm(self, manager_query: SharesManager, query: str, expected_items: List[str]):
        expected_items = [SHARED_ITEMS[item_name] for item_name in expected_items]
        actual_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)

    @pytest.mark.parametrize(
        'query,expected_items',
        [
            # something with loads of special characters between words
            ('singer)_-_don\'t', ['item2']),
            # wildcard, something with loads of special characters between words
            ('*inger)_-_don\'t', ['item2']),
            # exclude, something with loads of special characters between words
            ('simple -singer)_-_don\'t', ['item1', 'item3']),
        ]
    )
    def test_edgeCases(self, manager_query: SharesManager, query: str, expected_items: List[str]):
        expected_items = [SHARED_ITEMS[item_name] for item_name in expected_items]
        actual_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
