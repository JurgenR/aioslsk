import logging
import upnpclient


logger = logging.getLogger()


ADD_PORT_MAPPING_ACTION = 'AddPortMapping'


class UPNP:

    def __init__(self):
        pass

    def map_port(self, ip: str, port: int, duration: int):
        """Maps a port using UPNP

        @param duration: Lease duration in seconds
        """
        logging.debug(f"discover UPNP devices")
        devices = upnpclient.discover()

        for device in devices:
            action = device.find_action(ADD_PORT_MAPPING_ACTION)
            if action is not None:
                logging.debug(f"calling {ADD_PORT_MAPPING_ACTION} on device {device} with for {ip}:{port}")
                try:
                    action(
                        NewRemoteHost=None,
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
