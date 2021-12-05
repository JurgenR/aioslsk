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

    def __init__(self, username, token, results, free_slots, avg_speed, queue_len, locked_results):
        self.username = username
        self.token = token
        self.results = results
        self.free_slots = free_slots
        self.avg_speed = avg_speed
        self.queue_len = queue_len
        self.locked_results = locked_results
