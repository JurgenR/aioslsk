"""Ordinary transfer path operations, independent of the protocol."""
from functools import partial

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
