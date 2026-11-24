"""Ordinary transfer path operations, independent of the protocol."""
from functools import partial

import pytest

from aioslsk.file_access import open_transfer_file, transfer_stat, unlink_download


def test_nested_album_can_be_downloaded_resumed_shared_and_removed(tmp_path):
    root = str(tmp_path / 'music')
    filename = str(tmp_path / 'music' / 'Live Album' / 'Track 01.mp3')
    opener = partial(open_transfer_file, root)

    with open(filename, 'xb', opener=opener) as output:
        output.write(b'first ')
    with open(filename, 'ab', opener=opener) as output:
        output.write(b'second')
    with open(filename, 'rb', opener=opener) as source:
        assert source.read() == b'first second'
    assert transfer_stat(root, filename).st_size == 12
    unlink_download(root, filename)
    assert list((tmp_path / 'music' / 'Live Album').iterdir()) == []


def test_old_partial_outside_current_root_is_preserved(tmp_path):
    root = tmp_path / 'new-library'
    root.mkdir()
    old_partial = tmp_path / 'previous-download'
    old_partial.write_bytes(b'partial')
    with pytest.raises(OSError):
        unlink_download(str(root), str(old_partial))
    assert old_partial.read_bytes() == b'partial'


def test_file_access_skips_album_directory_links(tmp_path):
    root = tmp_path / 'music'
    root.mkdir()
    album = root / 'album'
    album.mkdir()
    (album / 'track').write_bytes(b'audio')
    alias = root / 'alias'
    try:
        alias.symlink_to(album, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f'directory links unavailable: {exc}')
    with pytest.raises(OSError):
        transfer_stat(str(root), str(alias / 'track'))
