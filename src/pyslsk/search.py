from dataclasses import dataclass, field
from typing import List

from pyslsk.messages import FileData


@dataclass
class ReceivedSearch:
    """Used for keeping track of searches received from the distributed parent"""
    username: str
    query: str
    matched_files: int


@dataclass
class SearchResult:
    """Search result received from a user"""
    ticket: int
    username: str

    has_free_slots: bool = False
    avg_speed: int = 0
    queue_size: int = 0

    shared_items: List[FileData] = field(default_factory=list)
    locked_results: List[FileData] = field(default_factory=list)


@dataclass
class SearchQuery:
    """Search query we have made"""
    ticket: int
    query: str
    results: List[SearchResult] = field(default_factory=list)
