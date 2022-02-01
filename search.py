from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class ReceivedSearch:
    """Used for keeping track of searches through the """
    username: str
    query: str
    matched_files: int


@dataclass
class SearchItem:
    """Single search item received from a user"""
    filename: str
    filesize: int
    attributes: List[Tuple[int, int]]

    # @classmethod
    # def from_shared_item(cls, shared_item):
    #     return cls()


@dataclass
class SearchResult:
    """Search result received from a user"""
    ticket: int
    username: str

    has_free_slots: bool = False
    avg_speed: int = 0
    queue_size: int = 0

    shared_items: List[SearchItem] = field(default_factory=list)
    locked_results: List[SearchItem] = field(default_factory=list)


@dataclass
class SearchQuery:
    """Search query we have made"""
    ticket: int
    query: str
    results: List[SearchResult] = field(default_factory=list)
