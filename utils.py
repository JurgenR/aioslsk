import os


def ticket_generator():
    idx = 1234
    while True:
        idx += 1
        if idx > 0xFFFFFFFF:
            idx = 1234
        yield idx
