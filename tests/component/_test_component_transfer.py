from pyslsk.configuration import Configuration
from pyslsk.events import EventBus, InternalEventBus
from pyslsk.settings import Settings
from pyslsk.state import State
from pyslsk.transfer import (
    Transfer,
    TransferManager,
)

import pytest
from unittest.mock import Mock


DEFAULT_SETTINGS = {
    'credentials': {
        'username': 'user0'
    },
    'sharing': {
        'download': ''
    }
}


@pytest.fixture
def transfer_manager(tmpdir):
    state = State()
    configuration = Configuration(tmpdir, tmpdir)
    event_bus = EventBus()
    internal_event_bus = InternalEventBus()

    shares_manager = Mock()
    network = Mock()

    manager = TransferManager(
        state,
        configuration,
        Settings(DEFAULT_SETTINGS),
        event_bus,
        internal_event_bus,
        shares_manager, network
    )
    return manager


class TestComponentTransfer:

    def test_download_successful(self, transfer_manager: TransferManager):
        transfer = Transfer('user0')
        transfer_manager.add(transfer)
        transfer_manager.queue(transfer)

        # Mock transferrequest
        transfer_manager._on_peer_transfer_request()
