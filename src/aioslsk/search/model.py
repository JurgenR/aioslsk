from collections.abc import Callable, Generator
from dataclasses import dataclass, field
import datetime
from enum import auto, Enum
import logging
import re
from typing import Optional

from ..protocol.primitives import FileData
from ..shares.utils import create_term_pattern
from ..tasks import Timer


logger = logging.getLogger(__name__)


class SearchType(Enum):
    NETWORK = auto()
    USER = auto()
    ROOM = auto()
    WISHLIST = auto()


@dataclass(slots=True)
class ReceivedSearch:
    """Used for keeping track of searches received from the distributed parent
    or server
    """
    username: str
    query: str
    result_count: int


@dataclass(slots=True)
class SearchQuery:
    query: str
    include_terms: set[str] = field(default_factory=set)
    exclude_terms: set[str] = field(default_factory=set)
    wildcard_terms: set[str] = field(default_factory=set)

    @classmethod
    def parse(cls, query: str) -> 'SearchQuery':
        """Parses the given query string into terms and creates a new
        :class:`.SearchQuery` object
        """
        obj = cls(query)

        terms = query.split()
        for term in terms:
            # Ignore terms containing only non-word chars
            l_term = term.lower()
            if not re.search(r'[^\W_]', l_term):
                continue

            if term.startswith('*'):
                obj.wildcard_terms.add(l_term[1:])
            elif term.startswith('-'):
                obj.exclude_terms.add(l_term[1:])
            else:
                obj.include_terms.add(l_term)

        return obj

    def matchers_iter(self) -> Generator[Callable[[str], bool], None, None]:
        """Generator for term matchers"""
        for include_term in self.include_terms:
            pattern = create_term_pattern(include_term, wildcard=False)
            yield lambda fn: bool(pattern.search(fn))

        for wildcard_term in self.wildcard_terms:
            pattern = create_term_pattern(wildcard_term, wildcard=True)
            yield lambda fn: bool(pattern.search(fn))

        for exclude_term in self.exclude_terms:
            pattern = create_term_pattern(exclude_term, wildcard=False)
            yield lambda fn: not pattern.search(fn)

    def has_inclusion_terms(self) -> bool:
        """Return whether this query has any valid inclusion terms"""
        return bool(self.include_terms) or bool(self.wildcard_terms)


@dataclass(slots=True)
class SearchResult:
    """Search result received from a user"""
    ticket: int
    username: str

    has_free_slots: bool = False
    avg_speed: int = 0
    queue_size: int = 0

    shared_items: list[FileData] = field(default_factory=list)
    locked_results: list[FileData] = field(default_factory=list)


@dataclass(slots=True)
class SearchRequest:
    """Search request we have made"""
    ticket: int
    query: str
    search_type: SearchType = SearchType.NETWORK

    room: Optional[str] = None
    username: Optional[str] = None
    results: list[SearchResult] = field(default_factory=list)
    started: datetime.datetime = field(default_factory=datetime.datetime.now)

    timer: Optional[Timer] = None
