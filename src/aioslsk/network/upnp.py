from __future__ import annotations
from functools import partial
from ipaddress import IPv4Address
import logging
from async_upnp_client.aiohttp import AiohttpRequester
from async_upnp_client.client_factory import UpnpFactory
from async_upnp_client.exceptions import UpnpActionResponseError
from async_upnp_client.profiles.igd import IgdDevice, PortMappingEntry
from async_upnp_client.search import async_search
from async_upnp_client.ssdp import SSDP_IP_V4, SSDP_PORT

from ..constants import (
    UPNP_DEFAULT_SEARCH_TIMEOUT,
    UPNP_MAPPING_SERVICES,
    UPNP_DEFAULT_LEASE_DURATION,
)

logger = logging.getLogger(__name__)


class UPNP:

    def __init__(self):
        self._factory: UpnpFactory = UpnpFactory(AiohttpRequester())

    async def search_igd_devices(self, source_ip: str, timeout: int = UPNP_DEFAULT_SEARCH_TIMEOUT) -> list[IgdDevice]:
        devices: list[IgdDevice] = []
        logger.info("starting search for IGD devices")
        await async_search(
            partial(self._search_callback, devices),
            source=(source_ip, 0),
            target=(SSDP_IP_V4, SSDP_PORT),
            timeout=timeout
        )
        logger.info("found %d IGD devices", len(devices))
        return devices

    async def _search_callback(self, devices: list[IgdDevice], headers):
        if headers['ST'] not in IgdDevice.DEVICE_TYPES:
            return

        logger.info("found Internet Gateway Device : %r", headers)
        device = await self._factory.async_create_device(headers['LOCATION'])

        devices.append(IgdDevice(device, None))

    async def get_mapped_ports(self, device: IgdDevice) -> list[PortMappingEntry]:
        entry_count = await device.async_get_port_mapping_number_of_entries()

        if entry_count:
            logger.debug("found %d mapped ports on device %r", entry_count, device.name)
            return await self._get_mapped_ports_known(device, entry_count)

        else:
            return await self._get_mapped_ports_unknown(device)

    async def _get_mapped_ports_known(self, device: IgdDevice, count: int) -> list[PortMappingEntry]:
        entries = []
        for idx in range(count):
            logger.debug("getting port map with index %d on device %r", idx, device.name)
            try:
                entry = await device.async_get_generic_port_mapping_entry(idx)

            except Exception as exc:
                logger.debug("failed to get entry %d on device : %r", idx, device.name, exc_info=exc)

            else:
                logger.debug("got entry for index %d on device %r : %r", idx, device.name, entry)
                if entry:
                    entries.append(entry)

        return entries

    async def _get_mapped_ports_unknown(self, device: IgdDevice) -> list[PortMappingEntry]:
        """Gets all mapped port entries for the given device when the length of
        the total amount of ports is not known.
        """
        entries = []
        idx = 0
        while True:
            logger.debug("getting port map with index %d on device %r", idx, device.name)
            try:
                entry = await device.async_get_generic_port_mapping_entry(idx)

            except UpnpActionResponseError as exc:
                # SpecifiedArrayIndexInvalid
                if not (exc.status == 500 and exc.error_code == 713):
                    logger.debug("failed to get entry %d on device : %r", idx, device.name, exc_info=exc)

                break

            except Exception as exc:
                logger.debug("failed to get entry %d on device : %r", idx, device.name, exc_info=exc)
                break

            else:
                if entry is None:
                    break
                logger.debug("got entry for index %d on device %r : %r", idx, device.name, entry)
                entries.append(entry)
                idx += 1

        return entries

    async def map_port(
            self, device: IgdDevice, internal_ip: str, port: int,
            lease_duration: int = UPNP_DEFAULT_LEASE_DURATION):

        action = device._any_action(UPNP_MAPPING_SERVICES, "AddPortMapping")
        if not action:
            raise ValueError(f"device {device.name} has no 'AddPortMapping' service")

        await action.async_call(
            NewRemoteHost='',
            NewExternalPort=port,
            NewProtocol='TCP',
            NewInternalPort=port,
            NewInternalClient=IPv4Address(internal_ip).exploded,
            NewEnabled=True,
            NewPortMappingDescription='AioSlsk',
            NewLeaseDuration=lease_duration
        )

    async def unmap_port(self, device: IgdDevice, port: int):
        action = device._any_action(UPNP_MAPPING_SERVICES, "DeletePortMapping")
        if not action:
            raise ValueError(f"device {device.name} has no 'DeletePortMapping' service")

        await action.async_call(
            NewRemoteHost='',
            NewExternalPort=port,
            NewProtocol='TCP'
        )


async def _main(args):
    upnp = UPNP()
    if args.subcommand == 'list':
        devices = await upnp.search_igd_devices(
            args.internal_ip, timeout=args.search_timeout)
        if not devices:
            print("No devices found")

        for device in devices:
            print(f"device : {device.name}")
            mapped_ports = await upnp.get_mapped_ports(device)
            for mapped_port in mapped_ports:
                print(mapped_port)

    if args.subcommand == 'map':
        devices = await upnp.search_igd_devices(
            args.internal_ip, timeout=args.search_timeout)
        if not devices:
            print("No devices found")

        for device in devices:
            await upnp.map_port(device, args.internal_ip, args.port)

    elif args.subcommand == 'unmap':
        devices = await upnp.search_igd_devices(
            args.internal_ip, timeout=args.search_timeout)
        if not devices:
            print("No devices found")

        for device in devices:
            await upnp.unmap_port(device, args.port)


if __name__ == '__main__':
    import asyncio
    import argparse
    import logging

    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser(description="Utility for mapping and unmapping ports to UPnP")
    subparsers = parser.add_subparsers(dest='subcommand')

    list_parser = subparsers.add_parser('list', help="List port mappings")
    list_parser.add_argument('internal_ip')
    list_parser.add_argument(
        '-st', '--search-timeout',
        type=int, default=5,
        help="UPnP Device search timeout"
    )

    map_parser = subparsers.add_parser('map', help="Add port mapping")
    map_parser.add_argument('internal_ip')
    map_parser.add_argument('port', type=int)
    map_parser.add_argument(
        '-st', '--search-timeout',
        type=int, default=5,
        help="UPnP Device search timeout"
    )

    unmap_parser = subparsers.add_parser('unmap', help="Remove port mapping")
    unmap_parser.add_argument('internal_ip')
    unmap_parser.add_argument('port', type=int)
    unmap_parser.add_argument(
        '-st', '--search-timeout',
        type=int, default=5,
        help="UPnP Device search timeout"
    )

    args = parser.parse_args()
    asyncio.run(_main(args))
