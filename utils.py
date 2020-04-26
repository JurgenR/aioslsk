import os


def ticket_generator():
    for idx in range(1111, 0xFFFFFFFF):
        yield idx


def get_directories_absolute_paths(directories):
    abs_paths = []
    for directory in directories:
        abs_paths.append(os.path.abspath(directory))
    return abs_paths


def get_file_count(directory):
    count = 0
    for root, dirs, files in os.walk(directory):
        count += len(files)
    return count
