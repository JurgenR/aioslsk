import hashlib
import logging
import os
import shelve
from typing import List, Protocol
from .model import Transfer

logger = logging.getLogger(__name__)


class TransferCache(Protocol):
    """Abstract base class for storing shares"""

    def read(self) -> List['Transfer']:
        ...

    def write(self, transfers: List['Transfer']):
        ...


class TransferNullCache:

    def read(self) -> List['Transfer']:  # pragma: no cover
        return []

    def write(self, transfers: List['Transfer']):  # pragma: no cover
        pass


class TransferShelveCache:

    DEFAULT_FILENAME = 'transfers'

    def __init__(self, data_directory: str):
        self.data_directory = data_directory

    def read(self) -> List['Transfer']:
        db_path = os.path.join(self.data_directory, self.DEFAULT_FILENAME)

        transfers = []
        with shelve.open(db_path, flag='c') as database:
            for _, transfer in database.items():
                transfers.append(transfer)

        logger.info(f"read {len(transfers)} transfers from : {db_path}")

        return transfers

    def write(self, transfers: List['Transfer']):
        db_path = os.path.join(self.data_directory, self.DEFAULT_FILENAME)

        logger.info(f"writing {len(transfers)} transfers to : {db_path}")

        with shelve.open(db_path, flag='c') as database:
            # Update/add transfers
            for transfer in transfers:
                key = hashlib.sha256(
                    (
                        transfer.username +
                        transfer.remote_path +
                        str(transfer.direction.value)
                    ).encode('utf-8')
                ).hexdigest()
                database[key] = transfer

            # Remove non existing transfers
            keys_to_delete = []
            for key, db_transfer in database.items():
                if not any(transfer == db_transfer for transfer in transfers):
                    keys_to_delete.append(key)
            for key_to_delete in keys_to_delete:
                database.pop(key_to_delete)

        logger.info(f"successfully wrote {len(transfers)} transfers to : {db_path}")
