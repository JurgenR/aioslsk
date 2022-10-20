from __future__ import annotations
import logging
import threading
from typing import List, Union

from .configuration import Configuration
from .events import EventBus, InternalEventBus
from .shares import SharesManager, SharesIndexer, IndexStorage
from .model import Room, User
from .network import Network
from . import messages
from .peer import PeerManager
from .server_manager import ServerManager
from .scheduler import Job, Scheduler
from .state import State
from .search import SearchQuery
from .settings import Settings
from .transfer import Transfer, TransferDirection, TransferManager
from .utils import ticket_generator


CLIENT_VERSION = 157


logger = logging.getLogger()


class SoulSeek(threading.Thread):

    def __init__(self, configuration: Configuration, event_bus: EventBus = None):
        super().__init__()
        self.configuration: Configuration = configuration
        self.settings: Settings = configuration.load_settings('pyslsk')

        self._ticket_generator = ticket_generator()
        self._stop_event = threading.Event()

        self.events: EventBus = event_bus or EventBus()
        self.internal_events: InternalEventBus = InternalEventBus()

        self.state: State = State()
        self.state.scheduler = Scheduler()

        self._network: Network = Network(
            self.state,
            self.settings,
            self.internal_events
        )

        self._cache_expiration_job = Job(60, self._network.expire_caches)
        self.state.scheduler.add_job(self._cache_expiration_job)

        shares_indexer: SharesIndexer = SharesIndexer()
        index_storage: IndexStorage = IndexStorage(self.configuration.data_directory)
        self.shares_manager: SharesManager = SharesManager(
            self.settings,
            shares_indexer,
            index_storage
        )
        self.shares_manager.shared_items = set(index_storage.load_items())
        self.shares_manager.build_term_map(rebuild=True)
        self.state.scheduler.add(
            0, self.shares_manager.load_from_settings, times=1
        )
        logger.debug(f"loaded from settings")

        self.transfer_manager: TransferManager = TransferManager(
            self.state,
            self.configuration,
            self.settings,
            self.events,
            self.internal_events,
            self.shares_manager,
            self._network
        )
        self.transfer_manager.load_transfers()

        self.peer_manager: PeerManager = PeerManager(
            self.state,
            self.settings,
            self.events,
            self.internal_events,
            self.shares_manager,
            self.transfer_manager,
            self._network
        )
        self.server_manager: ServerManager = ServerManager(
            self.state,
            self.settings,
            self.events,
            self.internal_events,
            self.shares_manager,
            self._network
        )

        self._loops = [
            self._network,
            self.state.scheduler,
        ]

    def run(self):
        super().run()

        self._network.initialize()
        while not self._stop_event.is_set():
            for loop in self._loops:
                try:
                    loop.loop()
                except Exception:
                    logger.exception(f"exception running loop {loop!r}")

        for loop in self._loops:
            loop.exit()

    def stop(self):
        logging.info("signaling client to exit")
        self._stop_event.set()
        if self.is_alive():
            logger.debug(f"wait for thread {self!r} to finish")
            self.join(timeout=30)
            if self.is_alive():
                logger.warning(f"thread is still alive after 30s : {self!r}")

        self.shares_manager.indexer.stop()

        # Writing database needs to be last, as transfers need to go into the
        # incomplete state if they were still transfering
        self.transfer_manager.store_transfers()

    @property
    def connections(self):
        return self._network.get_connections()

    @property
    def transfers(self):
        return self.transfer_manager._transfers

    def save_settings(self):
        self.configuration.save_settings('pyslsk', self.settings)

    def download(self, user: Union[str, User], filename: str):
        if isinstance(user, User):
            user = user.name
        transfer = self.transfer_manager.add(
            Transfer(
                user,
                filename,
                TransferDirection.DOWNLOAD
            )
        )
        self.transfer_manager.queue(transfer)
        return transfer

    def get_uploads(self) -> List[Transfer]:
        return self.transfer_manager.get_uploads()

    def get_downloads(self) -> List[Transfer]:
        return self.transfer_manager.get_downloads()

    def remove_transfer(self, transfer: Transfer):
        self.transfer_manager.remove(transfer)

    def abort_transfer(self, transfer: Transfer):
        self.transfer_manager.abort(transfer)

    def queue_transfer(self, transfer: Transfer):
        self.transfer_manager.queue(transfer)

    def join_room(self, room: Union[str, Room]):
        if isinstance(room, Room):
            self.server_manager.join_room(room.name)
        else:
            self.server_manager.join_room(room)

    def get_room_list(self):
        self.server_manager.get_room_list()

    def leave_room(self, room: Union[str, Room]):
        if isinstance(room, Room):
            self.server_manager.leave_room(room.name)
        else:
            self.server_manager.leave_room(room)

    def send_private_message(self, user: Union[str, User], message: str):
        if isinstance(user, User):
            self.server_manager.send_private_message(user.name, message)
        else:
            self.server_manager.send_private_message(user, message)

    def send_room_message(self, room: Union[str, Room], message: str):
        if isinstance(room, Room):
            self.server_manager.send_room_message(room.name, message)
        else:
            self.server_manager.send_room_message(room, message)

    def search(self, query: str):
        """Performs a search, returns the generated ticket number for the search
        """
        logger.info(f"Starting search for query: {query}")
        ticket = next(self._ticket_generator)
        self._network.send_server_messages(
            messages.FileSearch.create(ticket, query)
        )
        self.state.search_queries[ticket] = SearchQuery(ticket=ticket, query=query)
        return ticket

    def get_search_results_by_ticket(self, ticket: int):
        """Returns all search results for given ticket"""
        return self.state.search_queries[ticket]

    def remove_search_results_by_ticket(self, ticket: int):
        return self.state.search_queries.pop(ticket)

    def get_user_stats(self, user: Union[str, User]):
        if isinstance(user, User):
            self.server_manager.get_user_stats(user.name)
        else:
            self.server_manager.get_user_stats(user)

    def get_user_status(self, user: Union[str, User]):
        if isinstance(user, User):
            self.server_manager.get_user_status(user.name)
        else:
            self.server_manager.get_user_status(user)

    def add_user(self, user: Union[str, User]):
        if isinstance(user, User):
            self.server_manager.add_user(user.name)
        else:
            self.server_manager.add_user(user)

    def remove_user(self, user: Union[str, User]):
        if isinstance(user, User):
            self.server_manager.remove_user(user.name)
        else:
            self.server_manager.remove_user(user)

    # Peer requests
    def get_user_info(self, user: Union[str, User]):
        if isinstance(user, User):
            self.peer_manager.get_user_info(user.name)
        else:
            self.peer_manager.get_user_info(user)

    def get_user_shares(self, user: Union[str, User]):
        if isinstance(user, User):
            self.peer_manager.get_user_shares(user.name)
        else:
            self.peer_manager.get_user_shares(user)
