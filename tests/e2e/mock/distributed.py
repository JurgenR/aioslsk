from abc import ABC, abstractmethod
from math import ceil
import random
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

    @abstractmethod
    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        ...

    def get_roots(self) -> List[Peer]:
        """Returns the distributed roots"""
        return self.get_potential_roots()

    def get_potential_roots(self) -> List[Peer]:
        return [
            peer for peer in self._get_valid_peers()
            if peer.branch_level == 0
        ]

    def _get_valid_peers(self) -> List[Peer]:
        return [peer for peer in self.peers if peer.user]

    def _get_peers_accepting_children(self) -> List[Peer]:
        """Returns a list of all peers that are:

        * Have a valid user assigned
        * Not looking for a parent
        * Accepting children
        """
        eligable_peers = []
        for peer in self._get_valid_peers():
            if not peer.user.accept_children:
                continue

            eligable_peers.append(peer)

        return eligable_peers

    def sort_peers_by_connect_time(self, peers: List[Peer], reverse: bool = False) -> List[Peer]:
        peers.sort(
            key=lambda p: p.connect_time,
            reverse=reverse
        )
        return peers


class ConnectTimeOldestRootStrategy(DistributedStrategy):
    """The first connected peer becomes root, all others are children"""

    @classmethod
    def get_name(cls) -> str:
        return 'connect_time_oldest_root'

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        return [
            peer for peer in self.get_roots()
            if peer != target_peer
        ]

    def get_roots(self) -> List[Peer]:
        peers = self.sort_peers_by_connect_time(self.get_potential_roots())
        if not peers:
            return []

        return peers[:1]


class ConnectTimeChainStrategy(DistributedStrategy):
    """Chains peers based on their connect time. Oldest client is root, others
    follow in a chain
    """

    @classmethod
    def get_name(cls) -> str:
        return 'connect_time_chain'

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        peers = [
            peer for peer in self._get_peers_accepting_children()
            if peer != target_peer and peer.connect_time < target_peer.connect_time
        ]

        if not peers:
            return []

        return self.sort_peers_by_connect_time(peers, reverse=True)[:1]

    def get_roots(self) -> List[Peer]:
        peers = self.get_potential_roots()
        if not peers:
            return []

        return self.sort_peers_by_connect_time(peers)[:1]


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
                peer.branch_level for peer in self._get_peers_accepting_children()
                if peer != target_peer
            ])
        except ValueError:
            return []

        return [
            peer for peer in self._get_peers_accepting_children()
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
    * Probably it's simply a percentage of peers that become branch root.
        If there are 100 users and the percentage of branch roots should be
        5% then the 5 users with the top upload speeds are used.

    ----

    The server will mostly pick only peers whose speed exceeds yours. There
    are peers where it is less, but at least close and not much less. There
    does not seem to be a correlation on how much more; I've seen potential
    parents where that have an upload speed that only slightly exceeds the
    current upload speed. But I've also seen potential parents that greatly
    exceed the current speed.

    The potential parents with lower speed than the current speed could be
    explained by the fact that the speed used when selecting the parents is
    not determined based on the current speed but rather the speed at logon.
    This requires more investigation however, as I did not go in depth at
    when the new speed is taken into account after an upload, I just know
    that it is not immediate. The same could be said about the high speeds
    but those seem to occur more frequently and the expectation is that most
    people have around the same speed and higher speeds are rarer anyway,
    yet they occur much more often than the lower speeds. When graphing out
    the speeds of potential parents it increases exponentially at a certain
    point. I'm not sure if it is by design or I'm just looking at how
    upload speeds are generally divided.

    There is perhaps a smarter mechanism behind it. It cannot be that the
    server just picks the peers with speeds closest to the current speed as
    this would create bottlenecks. But I feel like if it were to be random
    then low speed peers could get assigned to branch roots would also
    create bottlenecks. It's difficult to determine because when the speed
    is low there is a large pool of peers to pick from and it's difficult to
    correlate. At current it does seems random, it could be that weights are
    assigned based on the current level and/or speed to the random
    selection process.
    """

    def __init__(self, settings: Settings, peers: List[Peer]):
        super().__init__(settings, peers)
        self.root_percentage: float = 0.01

    @classmethod
    def get_name(cls) -> str:
        return 'realistic'

    def get_potential_parents(self, target_peer: Peer) -> List[Peer]:
        possible_peers = []
        for peer in self._get_peers_accepting_children():
            if peer == target_peer:
                continue

            if peer.user.avg_speed >= target_peer.user.avg_speed:
                possible_peers.append(peer)

        return random.choices(possible_peers, k=10)

    def get_roots(self) -> List[Peer]:
        roots = sorted(
            self.get_potential_roots(),
            key=lambda p: p.user.avg_speed,
            reverse=True
        )

        amount_of_roots = ceil(len(self._get_valid_peers()) * self.root_percentage)
        return roots[:amount_of_roots]
