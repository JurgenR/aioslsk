from aioslsk.configuration import Configuration
from aioslsk.events import InternalEventBus
from aioslsk.exceptions import FileNotFoundError
from aioslsk.shares import (
    extract_attributes,
    SharedDirectory,
    SharedItem,
    SharesManager,
    SharesCache,
    SharesShelveCache,
    DirectoryShareMode,
)
from aioslsk.settings import Settings

import mutagen
import pytest
from pytest_unordered import unordered
import os
from typing import List
from unittest.mock import patch


RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'resources', 'shared')

FRIEND = 'friend0'
USER = 'user0'

MP3_FILENAME = 'Kevin_MacLeod-Galway.mp3'
FLAC_FILENAME = 'Kevin_MacLeod-Galway.flac'
SUBDIR_FILENAME = 'Strange_Drone_Impact.mp3'
SUBDIR_PATH = os.path.join(RESOURCES, 'Cool_Test_Album')
ROOT_FILE_1_PATH = os.path.join(RESOURCES, MP3_FILENAME)
ROOT_FILE_2_PATH = os.path.join(RESOURCES, FLAC_FILENAME)
SUBDIR_FILE_1_PATH = os.path.join(RESOURCES, SUBDIR_FILENAME)

DEFAULT_SETTINGS = {
    'sharing': {
        'directories': [
            {'path': RESOURCES,'share_mode': 'everyone'}
        ]
    },
    'users': {'friends': []}
}
SETTINGS_SUBDIR_FRIENDS = Settings({
    'sharing': {
        'directories': [
            {'path': RESOURCES, 'share_mode': 'everyone'},
            {'path': SUBDIR_PATH, 'share_mode': 'friends'}
        ]
    },
    'users': {'friends': [FRIEND]}
})
SETTINGS_SUBDIR_USERS = Settings({
    'sharing': {
        'directories': [
            {'path': RESOURCES, 'share_mode': 'everyone'},
            {'path': SUBDIR_PATH, 'share_mode': 'users', 'users': [USER]}
        ]
    },
    'users': {'friends': []}
})


SHARED_DIRECTORY = SharedDirectory('music', 'C:\\music', 'abcdef')
SHARED_ITEMS = {
    'item1': SharedItem(SHARED_DIRECTORY, 'folk\\folkalbum, release\\', 'simple band(contrib. singer) - isn\'t easy song.mp3', 0.0),
    'item2': SharedItem(SHARED_DIRECTORY, 'metal\\metalalbum release\\', 'simple band (contrib. singer)_-_don\'t easy song 片仮名.flac', 0.0),
    'item3': SharedItem(SHARED_DIRECTORY, 'rap\\rapalbum_release\\', 'simple_band(contributer. singer)-don\'t_easy_song 片仮名.mp3', 0.0),
}
SHARED_DIRECTORY.items = set(SHARED_ITEMS.values())


@pytest.fixture
def manager(tmp_path):
    return SharesManager(Settings(DEFAULT_SETTINGS), SharesCache(), InternalEventBus())


@pytest.fixture
def manager_query(tmp_path):
    manager = SharesManager(Settings(DEFAULT_SETTINGS), SharesCache(), InternalEventBus())
    manager.shared_directories = [SHARED_DIRECTORY]
    manager.build_term_map(SHARED_DIRECTORY)

    return manager


@pytest.fixture
def configuration(tmpdir) -> Configuration:
    settings_dir = os.path.join(tmpdir, 'settings')
    data_dir = os.path.join(tmpdir, 'data')
    return Configuration(settings_dir, data_dir)


class TestFunctions:

    def test_extractAttributes_MP3File_shouldReturnAttributes(self):
        filepath = os.path.join(RESOURCES, MP3_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(0, 128), (1, 15)]

    def test_extractAttributes_FLACFile_shouldReturnAttributes(self):
        filepath = os.path.join(RESOURCES, FLAC_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(1, 15), (4, 44100), (5, 16)]

    def test_extractAttributes_exception_shouldReturnEmpty(self):
        filepath = os.path.join(RESOURCES, FLAC_FILENAME)
        with patch('mutagen.File', side_effect=mutagen.MutagenError):
            attributes = extract_attributes(filepath)

        assert [] == attributes


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


class TestSharesManagerQuery:

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
        actual_items, locked_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
        assert locked_items == []

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
        actual_items, locked_items = manager_query.query(query)
        assert actual_items == []
        assert locked_items == []

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
        actual_items, locked_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
        assert locked_items == []

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
        actual_items, locked_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
        assert locked_items == []

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
        actual_items, locked_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
        assert locked_items == []

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
        actual_items, locked_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
        assert locked_items == []


class TestSharesManagerSharedDirectoryManagement:

    def test_loadFromSettings(self, manager: SharesManager):
        manager.load_from_settings()
        assert 1 == len(manager._shared_directories)
        assert manager._shared_directories[0].absolute_path == RESOURCES

    @pytest.mark.asyncio
    async def test_scan(self, manager: SharesManager):
        manager.load_from_settings()
        await manager.scan()
        directory = manager._shared_directories[0]
        assert 3 == len(directory.items)

    @pytest.mark.asyncio
    async def test_scan_waitForAttributes(self, manager: SharesManager):
        manager.load_from_settings()
        await manager.scan(wait_for_attributes=True)
        directory = manager._shared_directories[0]
        assert 3 == len(directory.items)
        for item in directory.items:
            assert item.attributes is not None

    @pytest.mark.asyncio
    async def test_scan_nestedDirectories(self, manager: SharesManager):
        manager._settings = Settings({
            'sharing': {
                'directories': [
                    {'path': RESOURCES, 'share_mode': 'everyone'},
                    {'path': SUBDIR_PATH, 'share_mode': 'friends'}
                ]
            }
        })
        manager.load_from_settings()
        assert 2 == len(manager._shared_directories)

        await manager.scan()
        assert 2 == len(manager._shared_directories[0].items)
        assert 1 == len(manager._shared_directories[1].items)

    @pytest.mark.asyncio
    async def test_addSharedDirectory_existingSubDirectory(self, manager: SharesManager):
        manager.load_from_settings()
        await manager.scan()
        manager.add_shared_directory(SUBDIR_PATH, DirectoryShareMode.FRIENDS)

        assert 2 == len(manager._shared_directories)
        assert 2 == len(manager._shared_directories[0].items)
        assert 1 == len(manager._shared_directories[1].items)

    @pytest.mark.asyncio
    async def test_removeSharedDirectory_withSubdir(self, manager: SharesManager):
        manager._settings = Settings({
            'sharing': {
                'directories': [
                    {'path': RESOURCES, 'share_mode': 'everyone'},
                    {'path': SUBDIR_PATH, 'share_mode': 'friends'}
                ]
            }
        })
        manager.load_from_settings()
        await manager.scan()
        assert 2 == len(manager._shared_directories[0].items)
        assert 1 == len(manager._shared_directories[1].items)

        subdir = manager._shared_directories[1]
        manager.remove_shared_directory(subdir)
        assert subdir not in manager._shared_directories
        assert 1 == len(manager._shared_directories)
        assert 3 == len(manager._shared_directories[0].items)


class TestManagerReplies:

    async def _load_and_scan(self, manager: SharesManager):
        manager.load_from_settings()
        await manager.scan(wait_for_attributes=True)

    @pytest.mark.asyncio
    async def test_createSharesReply_everyone(self, manager: SharesManager):
        await self._load_and_scan(manager)
        result, locked = manager.create_shares_reply('anyone')
        assert 2 == len(result)
        assert [] == locked

    @pytest.mark.asyncio
    async def test_createSharesReply_friends_isFriend(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await self._load_and_scan(manager)
        result, locked = manager.create_shares_reply(FRIEND)
        assert 2 == len(result)
        assert [] == locked

    @pytest.mark.asyncio
    async def test_createSharesReply_friends_isNotFriend(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await self._load_and_scan(manager)
        result, locked = manager.create_shares_reply('notfriend')
        assert 1 == len(result)
        assert 1 == len(locked)

    @pytest.mark.asyncio
    async def test_createSharesReply_users_isInList(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_USERS
        await self._load_and_scan(manager)
        result, locked = manager.create_shares_reply(USER)
        assert 2 == len(result)
        assert [] == locked

    @pytest.mark.asyncio
    async def test_createSharesReply_users_isNotInList(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_USERS
        await self._load_and_scan(manager)
        result, locked = manager.create_shares_reply('notuser')
        assert 1 == len(result)
        assert 1 == len(locked)

    @pytest.mark.asyncio
    async def test_createDirectoryReply(self, manager: SharesManager):
        await self._load_and_scan(manager)
        root_dir = manager._shared_directories[0].get_remote_path()
        directories = manager.create_directory_reply(root_dir)
        assert 1 == len(directories)
        assert 2 == len(directories[0].files)

    @pytest.mark.asyncio
    async def test_createDirectoryReply_subDir(self, manager: SharesManager):
        await self._load_and_scan(manager)
        root_dir = manager._shared_directories[0].get_remote_path()
        subdir = '\\'.join([root_dir, 'Cool_Test_Album'])
        directories = manager.create_directory_reply(subdir)
        assert 1 == len(directories)
        assert 1 == len(directories[0].files)

    @pytest.mark.asyncio
    async def test_query_friends_isNotFriend(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await self._load_and_scan(manager)
        result, locked = manager.query('Strange', username='notfriend')
        assert 0 == len(result)
        assert 1 == len(locked)

    @pytest.mark.asyncio
    async def test_query_isFriend(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await self._load_and_scan(manager)
        result, locked = manager.query('Strange', username=FRIEND)
        assert 1 == len(result)
        assert 0 == len(locked)


class TestSharesShelveCache:

    def test_read(self, configuration: Configuration):
        cache = SharesShelveCache(configuration.data_directory)
        cache.read()

    def test_write(self, configuration: Configuration):
        cache = SharesShelveCache(configuration.data_directory)
        cache.write([SHARED_DIRECTORY, ])
