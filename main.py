import connection
import messages
import slsk

import argparse
import cmd
import logging
import logging.config
import threading
import yaml


class SoulSeekCmd(cmd.Cmd):
    intro = 'Test SoulSeek client'
    prompt = '(slsk) '

    def __init__(self, stop_event, network, server_connection, client):
        super().__init__()
        self.stop_event = stop_event
        self.network = network
        self.server_connection = server_connection
        self.client = client

    def do_state(self, _):
        print("State: {}".format(self.client.state.__dict__))

    def do_search(self, query):
        print(f"Request to search for {query}")

    def do_exit(self, arg):
        print("Exiting")
        self.stop_event.set()
        self.network.join()
        return True


if __name__ == '__main__':
    with open('logger.yaml', 'r') as f:
        log_cfg = yaml.safe_load(f.read())
    logging.config.dictConfig(log_cfg)

    parser = argparse.ArgumentParser()
    parser.add_argument('--username', default='Khyle999')
    parser.add_argument('--password', default='Test1234')
    parser.add_argument('--listening-port', default=2416, type=int)
    args = parser.parse_args()
    # Init connections
    stop_event = threading.Event()
    network = connection.NetworkLoop(stop_event)
    server_connection = connection.ServerConnection()
    # listening_connection = connection.ListeningConnection(
    #     port=args.listening_port)
    # listening_connection_obfs = connection.ListeningConnection(
    #     port=args.listening_port + 1)
    server_connection.connect(network.selector)
    # listening_connection.connect(network.selector)
    # listening_connection_obfs.connect(network.selector)
    network.start()
    client = slsk.SoulSeek(server_connection, args)
    server_connection.listener = client
    client.login()
    SoulSeekCmd(stop_event, network, server_connection, client).cmdloop()
