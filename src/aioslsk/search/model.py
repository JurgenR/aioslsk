from dataclasses import dataclass, field
import datetime
from enum import auto, Enum
import re
from typing import List, Optional

from ..protocol.primitives import FileData


class SearchType(Enum):
    NETWORK = auto()
    USER = auto()
    ROOM = auto()
    WISHLIST = auto()


@dataclass
class ReceivedSearch:
    """Used for keeping track of searches received from the distributed parent
    or server
    """
    username: str
    query: str
    result_count: int


@dataclass
class SearchQuery:
    query: str
    include_terms: List[str] = field(default_factory=list)
    exclude_terms: List[str] = field(default_factory=list)
    wildcard_terms: List[str] = field(default_factory=list)

    @classmethod
    def parse(cls, query: str) -> 'SearchQuery':
        """Parses the given query string into terms and creates a new
        `SearchQuery` object
        """
        obj = cls(query)

        terms = query.split()
        for term in terms:
            # Ignore terms containing only non-word chars
            l_term = term.lower()
            if not re.search(r'[^\W_]', l_term):
                continue

            if term.startswith('*'):
                obj.wildcard_terms.append(l_term[1:])
            elif term.startswith('-'):
                obj.exclude_terms.append(l_term[1:])
            else:
                obj.include_terms.append(l_term)

        return obj

    def has_inclusion_terms(self) -> bool:
        """Return whether this query has any valid inclusion terms"""
        return bool(self.include_terms) or bool(self.wildcard_terms)


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
class SearchRequest:
    """Search request we have made"""
    ticket: int
    query: str
    search_type: SearchType = SearchType.NETWORK

    room: Optional[str] = None
    username: Optional[str] = None
    results: List[SearchResult] = field(default_factory=list)
    started: datetime.datetime = field(default_factory=datetime.datetime.now)
