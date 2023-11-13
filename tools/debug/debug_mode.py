"""Starts the client and drops into a Python REPL

The code is copy of asyncio.__main__ with slight modifications to start the
client on start and make it available from the REPL

To use:

1. Create a settings.json file with the desired settings under tools/debug/
2. Run `poetry run python -m tools.debug.debug_mode
"""
from aioslsk.settings import CredentialsSettings, Settings
from aioslsk.client import SoulSeekClient
from aioslsk import commands as cmds
import asyncio
import os
import json
import logging
import logging.config
import datetime

#### Start
import ast
import asyncio
import code
import concurrent.futures
import inspect
import sys
import threading
import types
import warnings

from asyncio import futures


SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))


def make_logging_config(directory: str):
    return {
        'version': 1,
        'formatters': {
            'simple': {
                'format': '[%(asctime)s][%(levelname)-8s][%(module)s][%(thread)d]: %(message)s'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': 'DEBUG',
                'formatter': 'simple',
                'stream': 'ext://sys.stderr'
            },
            'debug_file_handler': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'DEBUG',
                'formatter': 'simple',
                'filename': os.path.join(directory, 'slsk.log'),
                'maxBytes': 10485760,
                'backupCount': 20,
                'encoding': 'utf8'
            }
        },
        'loggers': {
            'aioslsk': {
                'level': 'DEBUG',
                'handlers': [
                    # 'console',
                    'debug_file_handler'
                ],
                'propagate': False
            },
            'asyncio': {
                'level': 'DEBUG',
                'handlers': [
                    # 'console',
                    'debug_file_handler'
                ],
                'propagate': False
            }
        },
        'root': {
            'level': 'DEBUG',
            'handlers': [
                'debug_file_handler'
            ]
        }
    }


class AsyncIOInteractiveConsole(code.InteractiveConsole):

    def __init__(self, locals, loop):
        super().__init__(locals)
        self.compile.compiler.flags |= ast.PyCF_ALLOW_TOP_LEVEL_AWAIT

        self.loop = loop

    def runcode(self, code):
        future = concurrent.futures.Future()

        def callback():
            global repl_future
            global repl_future_interrupted

            repl_future = None
            repl_future_interrupted = False

            func = types.FunctionType(code, self.locals)
            try:
                coro = func()
            except SystemExit:
                raise
            except KeyboardInterrupt as ex:
                repl_future_interrupted = True
                future.set_exception(ex)
                return
            except BaseException as ex:
                future.set_exception(ex)
                return

            if not inspect.iscoroutine(coro):
                future.set_result(coro)
                return

            try:
                repl_future = self.loop.create_task(coro)
                futures._chain_future(repl_future, future)
            except BaseException as exc:
                future.set_exception(exc)

        loop.call_soon_threadsafe(callback)

        try:
            return future.result()
        except SystemExit:
            raise
        except BaseException:
            if repl_future_interrupted:
                self.write("\nKeyboardInterrupt\n")
            else:
                self.showtraceback()


class REPLThread(threading.Thread):

    def run(self):
        try:
            banner = (
                f'asyncio REPL {sys.version} on {sys.platform}\n'
                f'Use "await" directly instead of "asyncio.run()".\n'
                f'Type "help", "copyright", "credits" or "license" '
                f'for more information.\n'
                f'{getattr(sys, "ps1", ">>> ")}import asyncio'
            )

            console.interact(
                banner=banner,
                exitmsg='exiting asyncio REPL...')
        finally:
            warnings.filterwarnings(
                'ignore',
                message=r'^coroutine .* was never awaited$',
                category=RuntimeWarning)

            loop.call_soon_threadsafe(loop.stop)

#### END

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Load settings and start the client
    SETTINGS_FILE = os.path.join(SCRIPT_DIR, 'settings.json')
    LOG_DIR = os.path.join(SCRIPT_DIR, 'logs', datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.config.dictConfig(make_logging_config(LOG_DIR))

    with open(SETTINGS_FILE, 'r') as fh:
        settings_dct = json.load(fh)

    settings: Settings = Settings(**settings_dct)
    client = SoulSeekClient(settings)

    loop.run_until_complete(client.start())
    loop.run_until_complete(client.login())

    repl_locals = {
        'asyncio': asyncio,
        'client': client,
        'cmds': cmds
    }
    for key in {'__name__', '__package__',
                '__loader__', '__spec__',
                '__builtins__', '__file__'}:
        repl_locals[key] = locals()[key]

    console = AsyncIOInteractiveConsole(repl_locals, loop)

    repl_future = None
    repl_future_interrupted = False

    try:
        import readline  # NoQA
    except ImportError:
        pass

    repl_thread = REPLThread()
    repl_thread.daemon = True
    repl_thread.start()

    while True:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            if repl_future and not repl_future.done():
                repl_future.cancel()
                repl_future_interrupted = True
            continue
        else:
            break
