from aioslsk.events import EventBus
from aioslsk.exceptions import (
    FileNotFoundError,
    FileNotSharedError,
    SharedDirectoryError,
)
from aioslsk.shares.manager import SharesManager, extract_attributes
from aioslsk.shares.model import DirectoryShareMode, SharedDirectory, SharedItem
from aioslsk.naming import DefaultNamingStrategy, KeepDirectoryStrategy
from aioslsk.settings import Settings, SharedDirectorySettingEntry

from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
import mutagen
import pytest
from pytest_unordered import unordered
import os
import sys
from typing import Optional
from unittest.mock import patch, AsyncMock


RESOURCES = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'resources')
SHARED_DIR_PATH = os.path.join(RESOURCES, 'shared')

FRIEND = 'friend0'
USER = 'user0'

MP3_FILENAME = 'Kevin_MacLeod-Galway.mp3'
FLAC_FILENAME = 'Kevin_MacLeod-Galway.flac'
SUBDIR_FILENAME = 'Strange_Drone_Impact.mp3'
SUBDIR_PATH = os.path.join(SHARED_DIR_PATH, 'Cool_Test_Album')
ROOT_FILE_1_PATH = os.path.join(SHARED_DIR_PATH, MP3_FILENAME)
ROOT_FILE_2_PATH = os.path.join(SHARED_DIR_PATH, FLAC_FILENAME)
SUBDIR_FILE_1_PATH = os.path.join(SHARED_DIR_PATH, SUBDIR_FILENAME)
TOTAL_FILES = 4
TOTAL_DIRECTORIES = 4

DEFAULT_SETTINGS = {
    'credentials': {'username': 'user0', 'password': 'pass0'},
    'shares': {
        'directories': [
            {'path': SHARED_DIR_PATH, 'share_mode': 'everyone'}
        ]
    },
    'users': {'friends': []}
}

SETTINGS_SUBDIR_FRIENDS = Settings(**{
    'credentials': {'username': 'user0', 'password': 'pass0'},
    'shares': {
        'directories': [
            {'path': SHARED_DIR_PATH, 'share_mode': 'everyone'},
            {'path': SUBDIR_PATH, 'share_mode': 'friends'}
        ]
    },
    'users': {'friends': [FRIEND]}
})
SETTINGS_SUBDIR_USERS = Settings(**{
    'credentials': {'username': 'user0', 'password': 'pass0'},
    'shares': {
        'directories': [
            {'path': SHARED_DIR_PATH, 'share_mode': 'everyone'},
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


async def _load_and_scan(manager: SharesManager):
    manager.load_from_settings()
    await manager.scan()


@pytest.fixture
def manager(tmp_path):
    return SharesManager(Settings(**DEFAULT_SETTINGS), EventBus(), AsyncMock())


@pytest.fixture
def manager_query(tmp_path):
    manager = SharesManager(
        Settings(**DEFAULT_SETTINGS), EventBus(), AsyncMock())
    manager._shared_directories = [SHARED_DIRECTORY]
    manager._build_term_map(SHARED_DIRECTORY)

    return manager


class TestFunctions:

    def test_extractAttributes_MP3File_shouldReturnAttributes(self):
        filepath = os.path.join(SHARED_DIR_PATH, MP3_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(0, 128), (1, 15)]

    def test_extractAttributes_FLACFile_shouldReturnAttributes(self):
        filepath = os.path.join(SHARED_DIR_PATH, FLAC_FILENAME)

        attributes = extract_attributes(filepath)

        assert attributes == [(1, 15), (4, 44100), (5, 16)]

    def test_extractAttributes_exception_shouldReturnEmpty(self):
        filepath = os.path.join(SHARED_DIR_PATH, FLAC_FILENAME)
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
    def test_querySimpleTerms_matching(self, manager_query: SharesManager, query: str, expected_items: list[str]):
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
    def test_querySpecialCharactersInTerm_matching(self, manager_query: SharesManager, query: str, expected_items: list[str]):
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
    def test_queryWildcard_matching(self, manager_query: SharesManager, query: str, expected_items: list[str]):
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
    def test_queryExcludeTerm(self, manager_query: SharesManager, query: str, expected_items: list[str]):
        expected_items = [SHARED_ITEMS[item_name] for item_name in expected_items]
        actual_items, locked_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
        assert locked_items == []

    def test_queryExcludedSearchPhrases(self, manager_query: SharesManager):
        expected_items = [SHARED_ITEMS[item_name] for item_name in ['item3']]
        actual_items, locked_items = manager_query.query(
            'song',
            excluded_search_phrases=['simple band']
        )
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
    def test_edgeCases(self, manager_query: SharesManager, query: str, expected_items: list[str]):
        expected_items = [SHARED_ITEMS[item_name] for item_name in expected_items]
        actual_items, locked_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
        assert locked_items == []

    @pytest.mark.parametrize(
        'query,expected_items',
        [
            # Backslash, inclusion, directory
            ('song folk\\folkalbum', ['item1']),
            # Backslash exclusion, directory
            ('song -folk\\folkalbum', ['item2', 'item3']),
            # Backslash, inclusion, filename
            ('folkalbum, release\\simple band', ['item1']),
            # Backslash, exclusion, filename
            ('song -rapalbum_release\\simple band', ['item1', 'item2']),
            # Slash inclusion
            ('song folk/folkalbum', []),
            # Slash exclusion
            ('song -folk/folkalbum', ['item1', 'item2', 'item3']),
        ]
    )
    def test_queryTermsWithSlashes(self, manager_query: SharesManager, query: str, expected_items: list[str]):
        expected_items = [SHARED_ITEMS[item_name] for item_name in expected_items]
        actual_items, locked_items = manager_query.query(query)
        assert expected_items == unordered(actual_items)
        assert locked_items == []

    def test_maxResults(self, manager_query: SharesManager):
        # Get the results without any limit, this is simply to ensure that if
        # the test data is changed that this testcase doesn't become bogus
        actual_items, locked_items = manager_query.query('simple')
        unlimited_results_len = len(actual_items) + len(locked_items)

        max_results = 2
        manager_query._settings.searches.max_results = max_results

        actual_items, locked_items = manager_query.query('simple')
        limited_results_len = len(actual_items) + len(locked_items)
        assert limited_results_len == max_results
        assert unlimited_results_len > limited_results_len


class TestSharesManagerSharedDirectoryManagement:

    def test_loadFromSettings(self, manager: SharesManager):
        manager.load_from_settings()
        assert 1 == len(manager.shared_directories)
        assert manager.shared_directories[0].absolute_path == os.path.abspath(SHARED_DIR_PATH)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'executor',
        [
            None,
            ThreadPoolExecutor,
            ProcessPoolExecutor
        ]
    )
    async def test_scan(self, manager: SharesManager, executor: Optional[type[Executor]]):
        manager.load_from_settings()
        manager.executor = executor() if executor else None

        await manager.scan()

        directory = manager.shared_directories[0]
        assert len(directory.items) == TOTAL_DIRECTORIES
        for item in directory.items:
            assert item.attributes is not None

    @pytest.mark.asyncio
    async def test_scan_withExecutorFactory(self, manager: SharesManager):
        manager.load_from_settings()
        manager.executor_factory = ProcessPoolExecutor

        await manager.start()
        assert manager.executor is not None

        await manager.scan()

        await manager.stop()
        assert manager.executor is None

        directory = manager.shared_directories[0]
        assert len(directory.items) == TOTAL_DIRECTORIES
        for item in directory.items:
            assert item.attributes is not None

    @pytest.mark.asyncio
    async def test_scan_nestedDirectories(self, manager: SharesManager):
        manager._settings.shares.directories = [
            SharedDirectorySettingEntry(
                path=SHARED_DIR_PATH, share_mode=DirectoryShareMode.EVERYONE
            ),
            SharedDirectorySettingEntry(
                path=SUBDIR_PATH, share_mode=DirectoryShareMode.FRIENDS
            )
        ]
        manager.load_from_settings()
        assert len(manager.shared_directories) == 2

        await manager.scan()
        assert len(manager.shared_directories[0].items) == 3
        assert len(manager.shared_directories[1].items) == 1

    @pytest.mark.parametrize(
        'directory_path',
        [
            ('/home/user/music'),
            ('/home/user/music/something/../')
        ]
    )
    def test_getSharedDirectory_returnObject(self, manager: SharesManager, directory_path: str):
        path = '/home/user/music'
        expected_shared_dir = manager.add_shared_directory(path)

        shared_dir = manager.get_shared_directory(directory_path)
        assert shared_dir == expected_shared_dir

    @pytest.mark.parametrize(
        'directory_path',
        [
            ('/home/user/'),
            ('/home/user'),
            ('/home/user/music/some'),
            ('/home/user/music/some/thing/..')
        ]
    )
    def test_getSharedDirectory_raisesError(self, manager: SharesManager, directory_path: str):
        path = '/home/user/music'
        manager.add_shared_directory(path)

        with pytest.raises(SharedDirectoryError):
            manager.get_shared_directory(directory_path)

    def test_isDirectoryShared_returnTrue(self, manager: SharesManager):
        path = '/home/user/music'
        manager.add_shared_directory(path)

        value = manager.is_directory_shared('/home/user/music/something/../')
        assert value is True

    def test_isDirectoryShared_returnFalse(self, manager: SharesManager):
        path = '/home/user/music'
        manager.add_shared_directory(path)

        value = manager.is_directory_shared('/home/user/music/something')
        assert value is False

    def test_addSharedDirectory_alreadyAdded(self, manager: SharesManager):
        manager.add_shared_directory('test/path')

        with pytest.raises(SharedDirectoryError):
            manager.add_shared_directory('test/inbetween/../path')

    @pytest.mark.asyncio
    async def test_addSharedDirectory_existingSubDirectory(self, manager: SharesManager):
        manager.load_from_settings()
        await manager.scan()
        manager.add_shared_directory(SUBDIR_PATH, DirectoryShareMode.FRIENDS)

        assert len(manager.shared_directories) == 2
        assert len(manager.shared_directories[0].items) == 3
        assert len(manager.shared_directories[1].items) == 1

    def test_updateSharedDirectory(self, manager: SharesManager):
        directory0 = manager.add_shared_directory(
            'test/path',
            share_mode=DirectoryShareMode.USERS,
            users=['user1']
        )

        directory1 = manager.update_shared_directory(
            'test/path',
            share_mode=None,
            users=['user1', 'user2']
        )

        assert directory1 == directory0
        assert directory1.share_mode == DirectoryShareMode.USERS
        assert directory1.users == ['user1', 'user2']

        directory2 = manager.update_shared_directory(
            'test/path/test/../',
            share_mode=DirectoryShareMode.EVERYONE,
            users=None
        )

        assert directory2 == directory0
        assert directory2.share_mode == DirectoryShareMode.EVERYONE
        assert directory2.users == ['user1', 'user2']

    def test_removeSharedDirectory_usingPath(self, manager: SharesManager):
        directory = manager.add_shared_directory(
            'test/path',
            share_mode=DirectoryShareMode.USERS,
            users=['user1']
        )

        removed_directory = manager.remove_shared_directory('test/path')

        assert removed_directory == directory
        assert directory not in manager.shared_directories

    def test_removeSharedDirectory_nonExisting_shouldRaise(self, manager: SharesManager):
        directory = manager.add_shared_directory('test/path')

        manager.remove_shared_directory('test/path')

        with pytest.raises(SharedDirectoryError):
            manager.remove_shared_directory(directory)

    @pytest.mark.asyncio
    async def test_removeSharedDirectory_withSubdir(self, manager: SharesManager):
        manager._settings.shares.directories = [
            SharedDirectorySettingEntry(
                path=SHARED_DIR_PATH, share_mode=DirectoryShareMode.EVERYONE
            ),
            SharedDirectorySettingEntry(
                path=SUBDIR_PATH, share_mode=DirectoryShareMode.FRIENDS
            )
        ]
        manager.load_from_settings()
        await manager.scan()

        root_directory = manager.shared_directories[0]
        sub_directory = manager.shared_directories[1]

        assert len(root_directory.items) == 3
        assert len(sub_directory.items) == 1

        manager.remove_shared_directory(sub_directory)
        assert sub_directory not in manager.shared_directories
        assert len(manager.shared_directories) == 1
        assert len(manager.shared_directories[0].items) == 4


class TestManagerReplies:

    @pytest.mark.asyncio
    async def test_createSharesReply_everyone(self, manager: SharesManager):
        await _load_and_scan(manager)
        alias = manager.shared_directories[0].alias

        unlocked, locked = manager.create_shares_reply('anyone')
        unlocked_directories = {directory.name: directory.files for directory in unlocked}

        assert f'@@{alias}' in unlocked_directories
        assert f'@@{alias}\\Cool_Test_Album' in unlocked_directories
        assert f'@@{alias}\\Hot_Test_Album' in unlocked_directories
        assert f'@@{alias}\\Hot_Test_Album\\CD01' in unlocked_directories

        assert len(unlocked_directories[f'@@{alias}']) == 2
        assert len(unlocked_directories[f'@@{alias}\\Cool_Test_Album']) == 1
        assert len(unlocked_directories[f'@@{alias}\\Hot_Test_Album']) == 0
        assert len(unlocked_directories[f'@@{alias}\\Hot_Test_Album\\CD01']) == 1

        assert locked == []

    @pytest.mark.asyncio
    async def test_createSharesReply_friends_isFriend(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await _load_and_scan(manager)
        unlocked, locked = manager.create_shares_reply(FRIEND)

        assert len(unlocked) == TOTAL_DIRECTORIES
        assert locked == []

    @pytest.mark.asyncio
    async def test_createSharesReply_friends_isNotFriend(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await _load_and_scan(manager)
        unlocked, locked = manager.create_shares_reply('notfriend')
        assert len(unlocked) == TOTAL_DIRECTORIES - 1
        assert len(locked) == 1

    @pytest.mark.asyncio
    async def test_createSharesReply_users_isInList(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_USERS
        await _load_and_scan(manager)
        unlocked, locked = manager.create_shares_reply(USER)
        assert len(unlocked) == TOTAL_DIRECTORIES
        assert locked == []

    @pytest.mark.asyncio
    async def test_createSharesReply_users_isNotInList(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_USERS
        await _load_and_scan(manager)
        unlocked, locked = manager.create_shares_reply('notuser')
        assert len(unlocked) == TOTAL_DIRECTORIES - 1
        assert len(locked) == 1

    @pytest.mark.asyncio
    async def test_createDirectoryReply(self, manager: SharesManager):
        await _load_and_scan(manager)
        root_dir = manager.shared_directories[0].get_remote_path()
        directories = manager.create_directory_reply(root_dir)
        assert len(directories) == 1
        assert len(directories[0].files) == 2

    @pytest.mark.asyncio
    async def test_createDirectoryReply_emptyDirectory(self, manager: SharesManager):
        await _load_and_scan(manager)
        empty_dir = '\\'.join([manager.shared_directories[0].get_remote_path(), 'Hot_Test_Album'])
        directories = manager.create_directory_reply(empty_dir)

        assert len(directories) == 1
        assert directories[0].name == empty_dir
        assert len(directories[0].files) == 0

    @pytest.mark.asyncio
    async def test_createDirectoryReply_nonExistantDirectory(self, manager: SharesManager):
        await _load_and_scan(manager)
        empty_dir = '\\'.join([manager.shared_directories[0].get_remote_path(), 'Non_existant'])
        directories = manager.create_directory_reply(empty_dir)

        assert len(directories) == 0

    @pytest.mark.asyncio
    async def test_createDirectoryReply_subDir(self, manager: SharesManager):
        await _load_and_scan(manager)
        root_dir = manager.shared_directories[0].get_remote_path()
        subdir = '\\'.join([root_dir, 'Cool_Test_Album'])
        directories = manager.create_directory_reply(subdir)
        assert len(directories) == 1
        assert len(directories[0].files) == 1

    @pytest.mark.asyncio
    async def test_query_friends_isNotFriend(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await _load_and_scan(manager)
        unlocked, locked = manager.query('Strange', username='notfriend')
        assert len(unlocked) == 0
        assert len(locked) == 1

    @pytest.mark.asyncio
    async def test_query_isFriend(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await _load_and_scan(manager)
        unlocked, locked = manager.query('Strange', username=FRIEND)
        assert len(unlocked) == 1
        assert len(locked) == 0


class TestSharesManager:

    @pytest.mark.asyncio
    async def test_getSharedItem_withUsername_notShared_shouldRaise(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await _load_and_scan(manager)

        remote_path = list(manager.shared_directories[1].items)[0].get_remote_path()

        with pytest.raises(FileNotSharedError):
            await manager.get_shared_item(remote_path, 'notfriend')

    @pytest.mark.asyncio
    async def test_getSharedItem_withUsername_shared_shouldReturn(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await _load_and_scan(manager)

        remote_path = list(manager.shared_directories[1].items)[0].get_remote_path()

        item = await manager.get_shared_item(remote_path, FRIEND)
        assert item is not None

    @pytest.mark.asyncio
    async def test_getSharedItem_notExistsOnDisk_shouldRaise(self, manager: SharesManager):
        manager._settings = SETTINGS_SUBDIR_FRIENDS
        await _load_and_scan(manager)

        remote_path = list(manager.shared_directories[1].items)[0].get_remote_path()

        with patch('aiofiles.os.path.exists', return_value=False):
            with pytest.raises(FileNotFoundError):
                await manager.get_shared_item(remote_path)

    def test_calculateDownloadPath(self, manager: SharesManager):
        if sys.platform.startswith('win32'):
            download_path = 'C:\\download'
        else:
            download_path = '/home/download'
        manager._settings.shares.download = download_path

        manager.naming_strategies = [
            DefaultNamingStrategy(),
            KeepDirectoryStrategy()
        ]

        remote_path = '@@abcdef\\directory\\file.mp3'
        local_path, local_filename = manager.calculate_download_path(remote_path)
        assert local_path == os.path.join(download_path, 'directory')
        assert local_filename == 'file.mp3'
