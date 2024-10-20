"""Starts the client and drops into a Python REPL

The code is copy of asyncio.__main__ with slight modifications to start the
client on start and make it available from the REPL

To use:

1. Create a settings.json file with the desired settings under ``tools/debug/``
2. Run ``poetry run python -m tools.debug.debug_mode``
"""
from aioslsk.settings import Settings
from aioslsk.client import SoulSeekClient
from aioslsk import commands as cmds
from aioslsk.transfer.cache import TransferShelveCache
from aioslsk.shares.cache import SharesShelveCache
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


logger = logging.getLogger(__name__)


SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))


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
    DEFAULT_SETTINGS_FILE = os.path.join(SCRIPT_DIR, 'settings.json')
    # DEFAULT_LOG_CONFIG_FILE = os.path.join(SCRIPT_DIR, 'config', 'log_full.json')
    DEFAULT_CONFIG_DIR_PATH = os.path.join(SCRIPT_DIR, 'config')
    LOG_DIR_PATH = os.path.join(SCRIPT_DIR, 'logs')

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--cache-dir',
        help="Optional transfer/shares cache directory"
    )
    parser.add_argument(
        '--settings',
        help="Optional path to a settings.json file",
        default=DEFAULT_SETTINGS_FILE
    )
    parser.add_argument(
        '--log-config-preset',
        help="Use one of the provided logging files from the config/ directory",
        choices=('log_full', 'log_filter_search'),
        default='log_full'
    )
    parser.add_argument(
        '--log-config',
        help=(
            "Optional path to a JSON logging configuration file. If not set uses "
            "the --log-config-preset option"
        )
    )

    args = parser.parse_args()


    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Load logging configuration
    is_custom_config = bool(args.log_config)
    if is_custom_config:
        log_config_path = args.log_config
    else:
        log_config_path = os.path.join(DEFAULT_CONFIG_DIR_PATH, f'{args.log_config_preset}.json')

    with open(log_config_path, 'r') as fh:
        log_config = json.load(fh)

    if not is_custom_config:
        session_dir = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        log_dir = os.path.join(LOG_DIR_PATH, session_dir)
        os.makedirs(log_dir, exist_ok=True)

        filename = log_config['handlers']['file_handler']['filename']
        log_config['handlers']['file_handler']['filename'] = os.path.join(log_dir, filename)

    logging.config.dictConfig(log_config)


    # Load settings and start the client
    with open(args.settings, 'r') as fh:
        settings_dct = json.load(fh)

    settings: Settings = Settings(**settings_dct)
    client = SoulSeekClient(
        settings,
        transfer_cache=TransferShelveCache(args.cache_dir) if args.cache_dir else None,
        shares_cache=SharesShelveCache(args.cache_dir) if args.cache_dir else None
    )

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
        except SystemExit:
            loop.run_until_complete(client.stop())
            raise
        except KeyboardInterrupt:
            loop.run_until_complete(client.stop())
            if repl_future and not repl_future.done():
                repl_future.cancel()
                repl_future_interrupted = True
            continue
        else:
            break
