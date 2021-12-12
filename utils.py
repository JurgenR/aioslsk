import os


def ticket_generator():
    idx = 1234
    while True:
        idx += 1
        if idx > 0xFFFFFFFF:
            idx = 1234
        yield idx


def get_absolute_paths(directories):
    abs_paths = []
    for directory in directories:
        abs_paths.append(os.path.abspath(directory))
    return abs_paths


def get_file_count(directory):
    count = 0
    for root, dirs, files in os.walk(directory):
        count += len(files)
    return count


def get_stats(directories):
    """Returns the total amount of files and directories shared"""
    count = 0
    for directory in directories:
        count += get_file_count(directory)
    return len(directories), count
