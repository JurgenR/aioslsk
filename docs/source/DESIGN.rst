======
Design
======

Client Initialization
=====================

The client consists of several services (or managers) that each have their own responsibility, these are initialized through the constructor of the client and can sometimes be dependent on each other:

* ``network``: Responsible for creating and destroying connections. All managers use the ``network`` to send messages and if necessary initialize peer connections
* ``users``: Responsible for managing user objects and some functions related to privileges
* ``rooms``: Responsible for managing room objects

    * Uses ``users`` to obtain ``User`` objects and set tracking status of the user

* ``interests``: Responsible for managing interests and recommendations

    * Uses ``users`` to grab ``User`` objects used when emitting events

* ``peers``: Responsible for general peer messages (not transfer related)

    * Uses ``users`` to grab ``User`` objects used when emitting events
    * Uses ``transfers`` to obtain information on free upload slots, upload speed, etc when the user information is requested
    * Uses ``shares`` to obtain a list of shares when such request is made

* ``transfers``: Responsible for managing ``Transfer`` objects and contains the procedures for queing and performing a transfer

    * Uses ``shares``

* ``shares``: Responsible for managing files and directories that we share
* ``search``: Responsible for handling all incoming and outgoing search requests and results

    * Uses ``users`` to grab ``User`` objects used when emitting events
    * Uses ``shares`` to perform queries
    * Uses ``transfers`` to obtain information on free upload slots, upload speed, etc to provide during the result

* ``distributed``: Responsible for the distributed network

The client will also initialize an ``EventBus`` object to pass to the services. The event bus is used to emit events back to the client consumer.


Connecting and Authentication
=============================

The client should be started using the ``SoulSeekClient.start()`` method which will first load all data, connect the listening ports and then connect to the server. The client will attempt to connect the listening connections first, if this fails the initialization fails, next the server will be connected.

Once the connections have been successfully set up it is up to the user to perform a logon using ``SoulSeekClient.login()``, this method will take the credentials from the settings. After logon a ``Session`` object will be created and the services will be notified of the new session which will be used by those services (in requests, checks, ...). The logon therefor works in a more synchronous manner, and the client will not start reading messages from the server until the session has been set.

The protocol does not define an explicit logout, instead the session will be destroyed when the server is disconnected.


Distributed Network
===================

This section describes the behaviour of the ``distributed.py`` module which is responsible for managing the distributed network. The ``DistributedNetwork`` class has 3 important variables:

* ``distributed_peers``: any peer that connected with peer connection type ``D`` will be added to this list. Upon disconnect that peer will be removed from this list
* ``parent``: the current parent
* ``children``: the current list of children


After session has been initialized the following values will be advertised to the server:

* Branch level: 0
* Branch root: <session username>
* Accept children: false
* ToggleParentSearch: true

Branch Root
-----------

If a :ref:`ServerSearchRequest` is received from the server it is assumed the server chose us to be the branch root. In that case the following values are advertised to the server:

* Branch level: 0
* Branch root: <session username>
* Accept children: true
* ToggleParentSearch: false

And the following values to the children (if there are any):

* Branch level: 0
* Branch root: <session username>

Afterwards the :ref:`ServerSearchRequest` will be passed on to the children


Parent
------

If :ref:`ToggleParentSearch` was enabled on the server the server will periodically send a list of :ref:`PotentialParents`. After getting a list of :ref:`PotentialParents` an attempt should be made to make a distributed connection to all peers in the list. If the connection is successful those peers will send the branch root and branch level. The module will select the first distributed connection that sent both values (except when branch level sent is 0) as the parent.

Setting the parent consists of cancelling all pending distributed connections and disconnecting all other distributed connections except the current children.

Example if we connected to a peer:

* Peer username: ``the parent user``
* Branch level: 1
* Branch root: ``the root user``

To the server:

* Branch level: 2
* Branch root: ``the root user``
* Accept children: true
* ToggleParentSearch: false

To the children:

* Branch level: 2
* Branch root: ``the root user``

If a branch level or branch root is received on any connection other than the parent connection the connection should be disconnected. When a branch level or branch root is received from our parent after the initial values then our new branch level/root needs to advertised to the server and our children.

We lose the parent when the connection is lost. If no message is received from the parent after a timeout the parent connection should also be disconnected. When losing the parent the branch values should be adjusted again to the initial values after session initialization.


Children
--------

When a distributed connection is made and the parent is set the new child will need to receive our branch values. When a distributed connection is initialized and a parent is set the code will look at the cache of potential parents to see if the user can be found there and will not add it as child.

When a child is disconnected the child is simply removed from the list of children and the client will no longer pass search requests or distributed level/root updates
