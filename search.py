class SearchQuery:

    def __init__(self, ticket, query):
        """

        @ivar ticket: Ticket number
        @ivar query: The query string
        @ivar results: List of L{SearchResult} objects
        """
        self.ticket: int = ticket
        self.query: str = query
        self.results = []


class SearchResult:

    def __init__(self, username, ticket, results, free_slots, avg_speed, queue_len, locked_results):
        self.username = username
        self.ticket = ticket
        self.results = results
        self.free_slots = free_slots
        self.avg_speed = avg_speed
        self.queue_len = queue_len
        self.locked_results = locked_results

    def __repr__(self):
        return (
            f"SearchResult(username={self.username!r}, ticket={self.ticket}, results={self.results!r}, "
            f"free_slots={self.free_slots}, avg_speed={self.avg_speed}, queue_len={self.queue_len}, "
            f"locked_results={self.locked_results!r})"
        )
