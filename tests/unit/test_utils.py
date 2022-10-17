from pyslsk.utils import get_duration, ticket_generator

import pytest


class TestUtils:

    @pytest.mark.parametrize(
        "duration,expected",
        [
            (0, '0h 0m 0s'),
            (120, '0h 2m 0s'),
            (7200, '2h 0m 0s'),
            (7200 + (30 * 60) + 5, '2h 30m 5s'),
        ]
    )
    def test_whenGetDuration_shouldReturnDuration(self, duration: int, expected: str):
        attributes = [(1, duration)]
        duration_str = get_duration(attributes)
        assert expected == duration_str

    def test_whenTicketGenerator_shouldGetNextTicket(self):
        ticket_gen = ticket_generator(initial=0)
        assert next(ticket_gen) == 1

    def test_whenTicketGeneratorAtMax_shouldRestartAtZero(self):
        ticket_gen = ticket_generator(initial=0xFFFFFFFE)
        assert next(ticket_gen) == 0xFFFFFFFF
        assert next(ticket_gen) == 0xFFFFFFFE
