from abc import ABC, abstractmethod
from typing import List
from tests.e2e.mock.peer import Peer
from tests.e2e.mock.model import Settings


class DistributedStrategy(ABC):

    def __init__(self, settings: Settings, peers: List[Peer]):
        self.settings: Settings = settings
        self.peers: List[Peer] = peers

    @classmethod
    @abstractmethod
    def get_name(cls) -> str:
        ...

    def get_peers_accepting_children(self) -> List[Peer]:
        """Returns a list of all peers that are:

        * Not looking for a parent
        * Accepting children
        """
        eligable_peers = []
        for peer in self.peers:
            if not peer.user.accept_children:
                continue

            if peer.user.enable_parent_search:
                continue

            if peer.branch_level is None:
                continue

            eligable_peers.append(peer)

        return eligable_peers

    def get_roots(self) -> List[Peer]:
        """Returns the distributed roots, these are the peers that have their
        branch level set to 0 and are no longer searching for a parent. If there
        are none, pick all where the
        """
        roots = [
            peer for peer in self.peers
            if peer.branch_level == 0 and not peer.user.enable_parent_search
        ]
        if roots:
            return roots

        return [
            peer for peer in self.peers
            if peer.branch_level == 0
        ]

    @abstractmethod
    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        ...


class ChainParentsStrategy(DistributedStrategy):
    """This strategy simply picks the peers with the highest branch level to be
    potential parents
    """

    @classmethod
    def get_name(cls) -> str:
        return 'chain'

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        try:
            max_level = max([
                peer.branch_level for peer in self.get_peers_accepting_children()
                if peer != target_peer
            ])
        except ValueError:
            return []

        return [
            peer for peer in self.get_peers_accepting_children()
            if peer.branch_level == max_level and peer != target_peer
        ]


class EveryoneRootStrategy(DistributedStrategy):
    """This strategy simply makes everyone a root"""

    @classmethod
    def get_name(cls) -> str:
        return 'everyone_root'

    def get_roots(self) -> List[Peer]:
        return self.peers

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        return []


class RealisticParentsStrategy(DistributedStrategy):

    @classmethod
    def get_name(cls) -> str:
        return 'realistic'

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        """Implement a realistic parent strategy.

        There is a max on how many children a parent can have based on upload
        speed. Perhaps there is a way to sort parents by upload speed.

        Eg.: if peer0 has upload speed of 2000 and a max of 10 children is
        configured, he can have 10 children that have a upload speed of 200.
        Those children can then have 10 children whose upload speed is 20, etc.

        So if a peer has an upload speed of roughly 200, suggest peer0 as parent
        if it has not reached its max limit yet (become level 1). If he has
        roughly upload speed of 20 suggest one of the level 1 peers (become level 2).

        Perhaps it could be testable if it is more realistic. When receiving a
        parent, check its speed and check the speed of the root and try a couple
        of times to see if any conclusions could be drawn.

        Not sure how to determine if someone should be branch root though. Possibly:
        * If the upload speed is greater than all others? -> that could cause issues
        * If the upload speed is greater than the lowest upload speed of one of
          the branch roots
        """
        return []
