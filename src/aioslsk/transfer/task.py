import aiofiles
import logging
from typing import TYPE_CHECKING

from ..exceptions import (
    ConnectionReadError,
    ConnectionWriteError,
    FileNotFoundError,
    FileNotSharedError,
    PeerConnectionError,
)
from ..network.connection import CloseReason, PeerConnection, PeerConnectionState
from ..protocol.messages import PeerUploadFailed


if TYPE_CHECKING:
    from .manager import TransferManager
    from .model import Transfer

logger = logging.getLogger(__name__)

class TransferTask:

    def __init__(self, manager: TransferManager):
        self.manager: TransferManager = manager


class UploadTask(TransferTask):

    async def execute(self, transfer: Transfer, connection: PeerConnection):
        """Uploads the transfer over the connection. This method will set the
        appropriate states on the passed `transfer` and `connection` objects.

        :param transfer: `Transfer` object
        :param connection: connection on which file should be sent
        """
        connection.set_connection_state(PeerConnectionState.TRANSFERING)
        await self.manager._uploading(transfer)
        try:
            async with aiofiles.open(transfer.local_path, 'rb') as handle:
                await handle.seek(transfer.get_offset())
                await connection.send_file(
                    handle,
                    transfer._transfer_progress_callback
                )

        except OSError:
            logger.exception(f"error opening on local file : {transfer.local_path}")
            await self.manager._fail(transfer)
            await connection.disconnect(CloseReason.REQUESTED)

        except ConnectionWriteError:
            logger.exception(f"error writing to socket : {transfer!r}")
            await self.manager._fail(transfer)
            await self.manager._network.send_peer_messages(
                PeerUploadFailed.Request(transfer.remote_path)
            )
        else:
            await connection.receive_until_eof(raise_exception=False)
            if transfer.is_transfered():
                await self.manager._complete(transfer)
            else:
                await self.manager._fail(transfer)


class DownloadTask(TransferTask):
    pass

