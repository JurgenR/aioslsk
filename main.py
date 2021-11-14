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
    prompt = '(py-slsk) '

    def __init__(self, stop_event, network, server_connection, client):
        super().__init__()
        self.stop_event = stop_event
        self.network = network
        self.server_connection = server_connection
        self.client = client

    def do_results(self, query):
        # If query is empty list all searches performed
        if not query:
            for ticket, search_query in self.client.search_queries.items():
                print(f"{ticket}\t{search_query.query}\t{len(search_query.results)}")
            return

        query_obj = None
        for ticket, search_query in self.client.search_queries.items():
            if search_query.query == query:
                query_obj = search_query
                break
        else:
            print(f"Couldn't find results for query : {query}")
            return

        # Print results
        idx = 1
        for user_result in query_obj.results:
            print(f"Results for user : {user_result.username}")
            for result in user_result.results:
                print(f"\t{idx}\t{result['filename']}\t{result['extension']}\t{result['filesize']}")
                idx += 1

    def do_state(self, _):
        print("State: {}".format(self.client.state.__dict__))

    def do_search(self, query):
        print(f"Starting search for {query}")
        ticket = self.client.search(query)
        print(f"Ticket number : {ticket}")

    def do_download(self, selection):
        pass

    def do_s(self, _):
        self.client.search('urbanus klinkers en klankers')

    def do_exit(self, arg):
        print("Exiting")
        self.stop_event.set()
        self.network.join()
        return True


if __name__ == '__main__':
    # Clear the log file before setting the logger
    with open('logs/slsk.log', 'w'):
        pass
    with open('logger.yaml', 'r') as f:
        log_cfg = yaml.safe_load(f.read())
    logging.config.dictConfig(log_cfg)

    parser = argparse.ArgumentParser()
    parser.add_argument('--username', default='Khyle999')
    parser.add_argument('--password', default='Test1234')
    parser.add_argument('--listening-port', default=64823, type=int)
    parser.add_argument('--directories', nargs='*', default=['share', ])
    args = parser.parse_args()

    # Init connections
    print(f"Sharing directories: {args.directories}")
    stop_event = threading.Event()
    network = connection.NetworkLoop(stop_event)
    server_connection = connection.ServerConnection()
    listening_connection = connection.ListeningConnection(port=args.listening_port)
    listening_connection_obfs = connection.ListeningConnection(port=args.listening_port + 1)

    # Perform the socket connections and start the network loop
    server_connection.connect(network.selector)
    listening_connection.connect(network.selector)
    listening_connection_obfs.connect(network.selector)
    network.start()

    # Set the SoulSeek object as listener
    client = slsk.SoulSeek(network, server_connection, args)
    server_connection.listener = client
    listening_connection.listener = client
    listening_connection_obfs.listener = client

    # Login and start the command loop
    client.login()
    SoulSeekCmd(stop_event, network, server_connection, client).cmdloop()
