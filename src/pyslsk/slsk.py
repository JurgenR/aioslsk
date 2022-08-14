from __future__ import annotations
import logging
import threading
from typing import Union

from .events import EventBus
from .filemanager import FileManager
from .model import Room, User
from .network import Network
from . import messages
from .peer import PeerManager
from .server_manager import ServerManager
from .scheduler import Job, Scheduler
from .state import State
from .search import SearchQuery
from .transfer import TransferManager


CLIENT_VERSION = 157


logger = logging.getLogger()


class SoulSeek(threading.Thread):

    def __init__(self, settings, event_bus: EventBus = None):
        super().__init__()
        self.settings = settings

        self._stop_event = threading.Event()

        self.events: EventBus = event_bus or EventBus()

        self.state: State = State()
        self.state.scheduler = Scheduler()

        self._network: Network = Network(
            self.state,
            settings
        )

        self._cache_expiration_job = Job(60, self._network.expire_caches)
        self.state.scheduler.add_job(self._cache_expiration_job)

        self.file_manager: FileManager = FileManager(settings['sharing'])
        self.transfer_manager: TransferManager = TransferManager(
            self.state,
            settings,
            self.file_manager,
            self._network
        )

        self.peer_manager: PeerManager = PeerManager(
            self.state,
            settings,
            self.events,
            self.file_manager,
            self.transfer_manager,
            self._network
        )
        self.server_manager: ServerManager = ServerManager(
            self.state,
            settings,
            self.events,
            self.file_manager,
            self._network
        )

        self.loops = [
            self._network,
            self.state.scheduler
        ]

    def run(self):
        super().run()

        self._network.initialize()
        while not self._stop_event.is_set():
            for loop in self.loops:
                try:
                    loop.loop()
                except Exception:
                    logger.exception(f"exception running loop {loop!r}")

        for loop in self.loops:
            loop.exit()

    def stop(self):
        logging.info("signaling client to exit")
        self._stop_event.set()
        logger.debug(f"wait for thread {self!r} to finish")
        self.join(timeout=30)
        if self.is_alive():
            logger.warning(f"thread is still alive after 30s : {self!r}")

    @property
    def connections(self):
        return self._network.get_connections()

    @property
    def transfers(self):
        return self.transfer_manager._transfers

    def download(self, user: Union[str, User], filename: str):
        if isinstance(user, User):
            return self.transfer_manager.queue_download(user.name, filename)
        else:
            return self.transfer_manager.queue_download(user, filename)

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
        logger.info(f"Starting search for query: {query}")
        ticket = next(self.state.ticket_generator)
        self._network.send_server_messages(
            messages.FileSearch.create(ticket, query)
        )
        self.state.search_queries[ticket] = SearchQuery(ticket=ticket, query=query)
        return ticket

    def get_search_results_by_ticket(self, ticket):
        return self.state.search_queries[ticket]

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
