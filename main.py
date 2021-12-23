import connection
import messages
import slsk

import argparse
import cmd
import logging
import logging.config
import yaml


class SoulSeekCmd(cmd.Cmd):
    intro = 'Test SoulSeek client'
    prompt = '(py-slsk) '

    def __init__(self, client):
        super().__init__()
        self.client = client

    def do_results(self, query):
        # If query is empty list all searches performed
        if not query:
            for ticket, search_query in self.client.state.search_queries.items():
                print(f"{ticket}\t{search_query.query}\t{len(search_query.results)}")
            return

        query_obj = None
        for ticket, search_query in self.client.state.search_queries.items():
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

    def do_connections(self, _):
        return
        # connections = self.network.get_connections()
        # for connection in connections:
        #     print(f"* {connection.hostname}:{connection.port}")

    def do_state(self, _):
        print("State: {}".format(self.client.state.__dict__))

    def do_search(self, query):
        print(f"Starting search for {query}")
        ticket = self.client.search(query)
        print(f"Ticket number : {ticket}")

    def do_enable(self, obj):
        if obj == 'children':
            self.client.accept_children()

    def do_user(self, command):
        action, username = command.split()
        if action == 'info':
            self.client.get_user_info(username)

    def do_s(self, _):
        self.client.search('urbanus klinkers en klankers')

    def do_exit(self, arg):
        print("Exiting")
        self.client.stop()
        return True


if __name__ == '__main__':
    # Clear the log file before setting the logger
    with open('logs/slsk.log', 'w'):
        pass
    with open('logger.yaml', 'r') as f:
        log_cfg = yaml.safe_load(f.read())
    logging.config.dictConfig(log_cfg)

    with open('settings.yaml', 'r') as f:
        settings = yaml.safe_load(f.read())

    client = slsk.SoulSeek(settings)
    client.start()

    # Login and start the command loop
    client.login()
    SoulSeekCmd(client).cmdloop()
