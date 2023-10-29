from __future__ import annotations
from functools import partial
from ipaddress import IPv4Address
from typing import List, TYPE_CHECKING
import logging
from async_upnp_client.aiohttp import AiohttpRequester
from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.exceptions import UpnpActionResponseError
from async_upnp_client.profiles.igd import IgdDevice
from async_upnp_client.search import async_search
from async_upnp_client.ssdp import SSDP_IP_V4, SSDP_PORT

from ..constants import UPNP_SEARCH_TIMEOUT

if TYPE_CHECKING:
    from ..settings import Settings

logger = logging.getLogger(__name__)


class UPNP:

    def __init__(self, settings: Settings):
        self._settings: Settings = settings
        self._factory: UpnpFactory = UpnpFactory(AiohttpRequester())

    async def search_igd_devices(self, source_ip: str, timeout: int = UPNP_SEARCH_TIMEOUT) -> List[IgdDevice]:
        devices: List[IgdDevice] = []
        logger.info("starting search for IGD devices")
        await async_search(
            partial(self._search_callback, devices),
            source=(source_ip, 0),
            target=(SSDP_IP_V4, SSDP_PORT),
            timeout=timeout
        )
        logger.debug(f"found {len(devices)} IGD devices")
        return devices

    async def _search_callback(self, devices: List[IgdDevice], headers):
        if headers['ST'] not in IgdDevice.DEVICE_TYPES:
            return

        logger.info(f"found Internet Gateway Device : {headers!r}")
        device = await self._factory.async_create_device(headers['LOCATION'])

        devices.append(IgdDevice(device, None))

    async def get_mapped_ports(self, device: IgdDevice):
        entry_count = await device.async_get_port_mapping_number_of_entries()
        if entry_count:
            logger.debug(f"found {entry_count} mapped ports on device {device.name!r}")
            return await self._get_mapped_ports_known(device, entry_count)
        else:
            return await self._get_mapped_ports_unknown(device)

    async def _get_mapped_ports_known(self, device: IgdDevice, count: int):
        entries = []
        for idx in range(count):
            logger.debug(f"getting port map with index {idx} on device {device.name!r}")
            try:
                entry = await device.async_get_generic_port_mapping_entry(idx)
            except Exception as exc:
                logger.debug(f"failed to get entry {idx} on device : {device.name!r}", exc_info=exc)

            else:
                logger.debug(f"got entry for index {idx} on device {device.name!r} : {entry!r}")
                entries.append(entry)

        return entries

    async def _get_mapped_ports_unknown(self, device: IgdDevice):
        """Gets all mapped port entries for the given device when the length of
        the total amount of ports is not known.
        """
        entries = []
        idx = 0
        while True:
            logger.debug(f"getting port map with index {idx} on device {device.name!r}")
            try:
                entry = await device.async_get_generic_port_mapping_entry(idx)

            except UpnpActionResponseError as exc:
                # SpecifiedArrayIndexInvalid
                if not (exc.status == 500 and exc.error_code == 713):
                    logger.debug(f"failed to get entry {idx} on device : {device.name!r}", exc_info=exc)

                break

            except Exception as exc:

                logger.debug(f"failed to get entry {idx} on device : {device.name!r}", exc_info=exc)
                break

            else:
                if entry is None:
                    break
                logger.debug(f"got entry for index {idx} on device {device.name!r} : {entry!r}")
                entries.append(entry)
                idx += 1

        return entries

    async def remove_port_mapping(self, device: IgdDevice, remote_host: str, port: int, protocol: str = 'TCP'):
        try:
            await device.async_delete_port_mapping(
                remote_host=IPv4Address(remote_host),
                external_port=port,
                protocol=protocol
            )
        except Exception as exc:
            logger.warning(
                f"failed to remove port mapping {remote_host}:{port} from device : {device.name!r}",
                exc_info=exc)

    async def map_port(self, device: IgdDevice, source_ip: str, port: int):
        logger.info(f"mapping port {source_ip}:{port} on device {device.name!r}")
        try:
            await device.async_add_port_mapping(
                protocol='TCP',
                remote_host=None,
                external_port=port,
                internal_client=IPv4Address(source_ip),
                internal_port=port,
                enabled=True,
                description='AioSlsk',
                lease_duration=self._settings.network.upnp.lease_duration
            )
        except UpnpActionResponseError as exc:
            logger.warning(f"failed to map port {port} device : {device.name!r}", exc_info=exc)

    async def unmap_port(self, device: IgdDevice, source_ip: str, port: int):
        await device.async_delete_port_mapping(
            remote_host=source_ip,
            external_port=port,
            protocol='TCP'
        )
