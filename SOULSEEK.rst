SoulSeek Flows
==============

Messages
--------

The messages described can be found here: https://www.museek-plus.org/wiki/SoulseekProtocol



Initial Connection and Logon
----------------------------

Open a TCP connection to server.slsknet.org:2416

Open up a listening connection

Send the Login_ command on the server socket. Most of the parameters here are self explanatory except for the client version (what to send here?).

A login response will be received which determines whether the login was successful or not along with the following commands providing some information:

- RoomList: List of chatrooms
- ParentMinSpeed: No idea yet
- ParentSpeedRatio: No idea yet
- WishlistInterval: No idea yet
- PrivilegedUsers

After the response we send the following requests back to the server with some information about us:

- CheckPrivileges: Check if we have privileges
- SetListenPort: The listening port(s), obfuscated and non-obfuscated
- SetStatus: Our status (offline, away, available)
- HaveNoParents: Related to Distributed Connections, should initually be true
- BranchRoot: Related to Distributed Connections, should initially be our own username
- BranchLevel: Related to Distributed Connections, should initially be 0
- SharedFoldersFiles: Number of directories and files we are sharing
- AddUser: Using our own username as parameter, this might be useful for checking if everything arrived on the server side
- AcceptChildren: Possibly this is used to prevent the server from advertising us through NetInfo_


Searching
---------




Distributed Connections
-----------------------

Each 60 seconds the server will send a NetInfo_ command. The command contains a list with each entry being a username, IP address and port.

Upon receiving this command the client will attempt to open up a connection to each of the IP addresses in the list.





.. _Login: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode1
.. _NetInfo: https://www.museek-plus.org/wiki/SoulseekProtocol#ServerCode102
