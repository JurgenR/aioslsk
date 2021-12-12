import logging
import time

from connection import (
    PeerConnection,
    PeerConnectionType,
)
from network_manager import NetworkManager
import messages
from peer import PeerManager
from server_manager import ServerManager
from state import State
from search import SearchQuery
from utils import ticket_generator


logger = logging.getLogger()


class SoulSeek:

    def __init__(self, settings):
        self.settings = settings

        self.state = State()
        self.ticket_generator = ticket_generator()

        self.network_manager = NetworkManager(settings['network'])
        self.peer_manager = PeerManager(self.state, self.network_manager)
        self.server_manager = ServerManager(self.state, settings, self.network_manager)

    def start_network(self):
        self.network_manager.initialize()

    def stop_network(self):
        self.network_manager.quit()

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
        ticket = next(self.ticket_generator)
        self.network_manager.send_server_messages(
            messages.FileSearch.create(ticket, query))
        self.state.search_queries[ticket] = SearchQuery(ticket, query)
        return ticket
