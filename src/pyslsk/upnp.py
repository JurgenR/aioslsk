import logging
import upnpclient


logger = logging.getLogger(__name__)


ADD_PORT_MAPPING_ACTION = 'AddPortMapping'
DELETE_PORT_MAPPING_ACTION = 'DeletePortMapping'
GET_GENERIC_PORT_MAPPING_ENTRY_ACTION = 'GetGenericPortMappingEntry'


class UPNP:

    def __init__(self):
        self.discovered_devices = None

    def discover_devices(self):
        if self.discovered_devices is None:
            logging.debug("discover UPNP devices")
            self.discovered_devices = upnpclient.discover()
        else:
            logging.debug("using cached UPNP devices")
        return self.discovered_devices

    def get_mappings(self):
        devices = self.discover_devices()

        mappings = []

        for device in devices:
            get_action = device.find_action(GET_GENERIC_PORT_MAPPING_ENTRY_ACTION)
            if get_action is None:
                continue

            logging.debug(f"fetching port mappings on device {device}")

            idx = 0
            while True:
                try:
                    response = get_action(NewPortMappingIndex=idx)
                    logging.debug(f"Index {idx}: {response}")
                except upnpclient.soap.SOAPError:
                    logging.debug(f"no port mapping on index {idx}")
                    break
                else:
                    mappings.append(response)
                    idx += 1

        return mappings

    def delete_port_map(self, remote_host, ext_port, protocol='TCP'):
        devices = self.discover_devices()
        for device in devices:
            delete_map_action = device.find_action(DELETE_PORT_MAPPING_ACTION)
            if delete_map_action is not None:
                logging.debug(f"calling {ADD_PORT_MAPPING_ACTION} on device {device}")
                delete_map_action(
                    NewRemoteHost=remote_host,
                    NewExternalPort=ext_port,
                    NewProtocol=protocol
                )

    # device.find_action('DeletePortMapping')(NewRemoteHost='255.255.255.255', NewExternalPort=61000, NewProtocol='TCP')

    def map_port(self, ip: str, port: int, duration: int):
        """Maps a port using UPNP

        @param duration: Lease duration in seconds
        """
        devices = self.discover_devices()

        for device in devices:
            map_action = device.find_action(ADD_PORT_MAPPING_ACTION)
            if map_action is not None:
                logging.debug(f"calling {ADD_PORT_MAPPING_ACTION} on device {device} with for {ip}:{port}")
                try:
                    map_action(
                        NewRemoteHost='',
                        NewExternalPort=port,
                        NewProtocol='TCP',
                        NewInternalPort=port,
                        NewInternalClient=ip,
                        NewEnabled='1',
                        NewPortMappingDescription='PySlsk',
                        NewLeaseDuration=0
                    )
                except upnpclient.soap.SOAPError:
                    logging.exception(f"exception calling {ADD_PORT_MAPPING_ACTION} on device {device}")
