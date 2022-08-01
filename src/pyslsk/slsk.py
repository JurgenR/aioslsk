from __future__ import annotations
import logging
import threading
import time

from .events import EventBus
from .filemanager import FileManager
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

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

        self._stop_event = threading.Event()

        self.events: EventBus = EventBus()

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

    def download(self, username: str, filename: str):
        return self.transfer_manager.queue_download(username, filename)

    def join_room(self, name: str):
        self.server_manager.join_room(name)

    def leave_room(self, name: str):
        self.server_manager.leave_room(name)

    def send_private_message(self, username: str, message: str):
        self.server_manager.send_private_message(username, message)

    def send_room_message(self, room_name: str, message: str):
        self.server_manager.send_room_message(room_name, message)

    def search(self, query):
        logger.info(f"Starting search for query: {query}")
        ticket = next(self.state.ticket_generator)
        self._network.send_server_messages(
            messages.FileSearch.create(ticket, query)
        )
        self.state.search_queries[ticket] = SearchQuery(ticket=ticket, query=query)
        return ticket

    def get_search_results_by_ticket(self, ticket):
        return self.state.search_queries[ticket]
