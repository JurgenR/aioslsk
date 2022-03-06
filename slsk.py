import logging
import threading
import time

from events import EventBus
from filemanager import FileManager
from network_manager import NetworkManager
import messages
from peer import PeerManager
from server_manager import ServerManager
from scheduler import Job, Scheduler
from state import State
from search import SearchQuery
from transfer import TransferManager


logger = logging.getLogger()


class SoulSeek:

    def __init__(self, settings):
        self.settings = settings

        self._stop_event = threading.Event()
        self._cache_lock = threading.Lock()

        self.events = EventBus()

        self.state = State()
        self.state.scheduler = Scheduler(self._stop_event)

        self.file_manager = FileManager(settings['sharing'])

        self.transfer_manager = TransferManager(settings)

        self._network_manager = NetworkManager(
            settings,
            self._stop_event,
            self._cache_lock
        )

        cache_expiration_job = Job(60, self._network_manager.expire_caches)
        self.state.scheduler.add_job(cache_expiration_job)

        self._peer_manager = PeerManager(
            self.state,
            settings,
            self.events,
            self.file_manager,
            self.transfer_manager,
            self._network_manager
        )
        self._server_manager = ServerManager(
            self.state,
            settings,
            self.events,
            self.file_manager,
            self._network_manager
        )

    def start(self):
        self._network_manager.initialize()
        self.state.scheduler.start()

    def stop(self):
        logging.info("signaling client to exit")
        self._stop_event.set()
        network_loops = self._network_manager.get_network_loops()
        for thread in network_loops + [self.state.scheduler, ]:
            logger.debug(f"wait for thread {thread!r} to finish")
            thread.join(timeout=30)
            if thread.is_alive():
                logger.warning(f"thread is still alive after 30s : {thread!r}")

    @property
    def connections(self):
        return self._network_manager.get_connections()

    @property
    def transfers(self):
        return self.transfer_manager._transfers

    def login(self):
        """Perform a login request with the username and password found in
        L{self.settings} and waits until L{self.state.logged_in} is set.
        """
        username = self.settings['credentials']['username']
        password = self.settings['credentials']['password']
        logger.info(f"Logging on with credentials: {username}:{password}")
        self._network_manager.send_server_messages(
            messages.Login.create(username, password, 157)
        )
        while not self.state.logged_in:
            time.sleep(1)

    def download(self, username: str, filename: str):
        return self._peer_manager.download(username, filename)

    def join_room(self, name: str):
        self._server_manager.join_room(name)

    def leave_room(self, name: str):
        self._server_manager.leave_room(name)

    def send_private_message(self, username: str, message: str):
        self._server_manager.send_private_message(username, message)

    def send_room_message(self, room_name: str, message: str):
        self._server_manager.send_room_message(room_name, message)

    def search(self, query):
        logger.info(f"Starting search for query: {query}")
        ticket = next(self.state.ticket_generator)
        self._network_manager.send_server_messages(
            messages.FileSearch.create(ticket, query)
        )
        self.state.search_queries[ticket] = SearchQuery(ticket=ticket, query=query)
        return ticket

    def get_search_results_by_ticket(self, ticket):
        return self.state.search_queries[ticket]
