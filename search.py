from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class ReceivedSearch:
    username: str
    query: str
    matched_files: int


@dataclass
class SearchItem:
    filename: str
    filesize: int
    attributes: List[Tuple[int, int]]

    @classmethod
    def from_shared_item(cls, shared_item):
        return cls()


@dataclass
class SearchResult:
    ticket: int
    username: str

    free_slots: int = 0
    avg_speed: int = 0
    queue_len: int = 0

    shared_items: List[SearchItem] = field(default_factory=list)
    locked_results: List[SearchItem] = field(default_factory=list)


@dataclass
class SearchQuery:
    ticket: int
    query: str
    results: List[SearchResult] = field(default_factory=list)
