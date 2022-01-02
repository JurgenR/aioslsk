from datetime import timedelta
import logging
import threading
import time

from connection import (
    PeerConnection,
    PeerConnectionType,
)
from network_manager import NetworkManager
import messages
from peer import PeerManager
from server_manager import ServerManager
from scheduler import Job, Scheduler
from state import State
from search import SearchQuery


logger = logging.getLogger()


class SoulSeek:

    def __init__(self, settings):
        self.settings = settings

        self._stop_event = threading.Event()
        self._cache_lock = threading.Lock()

        self.state = State()
        self.state.scheduler = Scheduler(self._stop_event)

        cache_expiration_job = Job(
            60,
            self.state.expire_caches,
            args=[self._cache_lock, ]
        )
        self.state.scheduler.add_job(cache_expiration_job)


        self.network_manager = NetworkManager(settings['network'], self._stop_event)
        self.peer_manager = PeerManager(
            self.state,
            self._cache_lock,
            settings,
            self.network_manager
        )
        self.server_manager = ServerManager(
            self.state,
            self._cache_lock,
            settings,
            self.network_manager
        )

    def start(self):
        self.network_manager.initialize()
        self.state.scheduler.start()

    def stop(self):
        logging.info("signaling client to exit")
        self._stop_event.set()
        network_loops = self.network_manager.get_network_loops()
        for thread in network_loops + [self.state.scheduler, ]:
            logger.debug(f"wait for thread {thread!r} to finish")
            thread.join(timeout=30)
            if thread.is_alive():
                logger.warning(f"thread is still alive after 60s : {thread!r}")

    def get_connections(self):
        return []

    def login(self):
        """Perform a login request with the username and password found in
        L{self.settings} and waits until L{self.state.logged_in} is set.
        """
        username = self.settings['credentials']['username']
        password = self.settings['credentials']['password']
        logger.info(f"Logging on with credentials: {username}:{password}")
        self.network_manager.send_server_messages(
            messages.Login.create(username, password, 157)
        )
        while not self.state.logged_in:
            time.sleep(1)

    def search(self, query):
        logger.info(f"Starting search for query: {query}")
        ticket = next(self.state.ticket_generator)
        self.network_manager.send_server_messages(
            messages.FileSearch.create(ticket, query))
        self.state.search_queries[ticket] = SearchQuery(ticket, query)
        return ticket

    def download(self, search_result):
        pass

    def accept_children(self):
        logger.info("Start accepting children")
        self.network_manager.send_server_messages(
            messages.AcceptChildren.create(True))
