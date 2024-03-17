from dataclasses import dataclass, field
import datetime
from enum import auto, Enum
import re
from typing import Callable, Dict, Generator, List, Optional, Set

from ..protocol.primitives import FileData
from ..shares.utils import create_term_pattern


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
    include_terms: Set[str] = field(default_factory=set)
    exclude_terms: Set[str] = field(default_factory=set)
    wildcard_terms: Set[str] = field(default_factory=set)
    _matchers: Dict[str, Callable[[str], bool]] = field(default_factory=dict)
    _matchers_complete: bool = False

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
                obj.wildcard_terms.add(l_term[1:])
            elif term.startswith('-'):
                obj.exclude_terms.add(l_term[1:])
            else:
                obj.include_terms.add(l_term)

        return obj

    def matchers_iter(self) -> Generator[Callable[[str], bool], None, None]:
        """Generator for matching terms that caches the regular patterns
        matchers
        """
        # If all matchers are calculated simply return from the stored dict
        if self._matchers_complete:
            for matcher in self._matchers.values():
                yield matcher

        # Calculate the matchers on the fly
        for include_term in self.include_terms:
            if include_term not in self._matchers:
                self._matchers[include_term] = lambda fn: bool(
                    re.search(create_term_pattern(include_term, wildcard=False), fn)
                )

            yield self._matchers[include_term]

        for wildcard_term in self.wildcard_terms:
            wterm = '*' + wildcard_term

            if wterm not in self._matchers:
                self._matchers[wterm] = lambda fn: bool(
                    re.search(create_term_pattern(wildcard_term, wildcard=True), fn)
                )

            yield self._matchers[wterm]

        for exclude_term in self.exclude_terms:
            exterm = '-' + exclude_term

            if exterm not in self._matchers:
                self._matchers[exterm] = lambda fn: not re.search(
                    create_term_pattern(exclude_term, wildcard=False), fn
                )

            yield self._matchers[exterm]

        self._matchers_complete = True

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
