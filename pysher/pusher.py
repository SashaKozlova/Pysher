from pysher.channel import Channel
from pysher.connection import Connection
import hashlib
import hmac
import logging
import json
import requests
import login_get_token

VERSION = '0.6.0'
CHANNEL_ID = None


def get_access_token(url, payload):
    global CHANNEL_ID
    headers = {"Accept": "application/json"}
    token_response = requests.post(url=url, headers=headers, json=payload)
    text = token_response.json()
    access_token = "Bearer " + text['access_token']
    CHANNEL_ID = text['user']['id']

    return access_token


def logout(url, access_token):
    headers = {"Accept": "application/json", 'Authorization': access_token}
    response = requests.post(url=url, headers=headers)
    print("Logout: " + response.text)


class Pusher(object):
    host = "ws.pusherapp.com"
    client_id = "app"
    protocol = 6

    def __init__(self, key, cluster="", secure=True, secret="", user_data=None, log_level=logging.INFO,
                 daemon=True, port=443, reconnect_interval=10, custom_host="", auto_sub=False,
                 http_proxy_host="", http_proxy_port=0, http_no_proxy=None, http_proxy_auth=None,
                 **thread_kwargs):
        """Initialize the Pusher instance.

        :param str or bytes key:
        :param str cluster:
        :param bool secure:
        :param bytes or str secret:
        :param Optional[Dict] user_data:
        :param str log_level:
        :param bool daemon:
        :param int port:
        :param int or float reconnect_interval:
        :param str custom_host:
        :param bool auto_sub:
        :param stt http_proxy_host:
        :param int http_proxy_port:
        :param http_no_proxy:
        :param http_proxy_auth:
        :param Any thread_kwargs:
        """
        # https://pusher.com/docs/clusters
        if cluster:
            self.host = "ws-{cluster}.pusher.com".format(cluster=cluster)
        else:
            self.host = "ws.pusherapp.com"

        self.key = key
        self.secret = secret

        self.user_data = user_data or {}

        self.channels = {}
        self.url = self._build_url(secure, port, custom_host)
        self.auth_token = None

        if auto_sub:
            reconnect_handler = self._reconnect_handler
        else:
            reconnect_handler = None

        self.connection = Connection(self._connection_handler, self.url,
                                     reconnect_handler=reconnect_handler,
                                     log_level=log_level,
                                     daemon=daemon,
                                     reconnect_interval=reconnect_interval,
                                     socket_kwargs=dict(http_proxy_host=http_proxy_host,
                                                        http_proxy_port=http_proxy_port,
                                                        http_no_proxy=http_no_proxy,
                                                        http_proxy_auth=http_proxy_auth,
                                                        ping_timeout=100),
                                     **thread_kwargs)

    @property
    def key_as_bytes(self):
        return self.key if isinstance(self.key, bytes) else self.key.encode('UTF-8')

    @property
    def secret_as_bytes(self):
        return self.secret if isinstance(self.secret, bytes) else self.secret.encode('UTF-8')

    def connect(self):
        """Connect to Pusher"""
        self.connection.start()

    def disconnect(self, timeout=None):
        """Disconnect from Pusher"""
        self.connection.disconnect(timeout)
        self.channels = {}

    def subscribe(self, channel_name, auth=None, authEndpoint=None, url_token=None, payload=None):
        """Subscribe to a channel.

        :param str channel_name: The name of the channel to subscribe to.
        :param str auth: The token to use if authenticated externally.
        :rtype: pysher.Channel
        """
        data = {'channel': channel_name}
        if auth is None:
            if channel_name.startswith('presence-'):
                data['auth'] = self._generate_presence_token(channel_name)
                data['channel_data'] = json.dumps(self.user_data)
            elif channel_name.startswith('private-'):
                data['auth'] = self._generate_auth_token(channel_name, authEndpoint=authEndpoint, url_token=url_token,
                                                         payload=payload)
                data['channel'] = "{}{}".format(channel_name, CHANNEL_ID)
        else:
            data['auth'] = auth

        self.connection.send_event('pusher:subscribe', data)

        self.channels[channel_name] = Channel(channel_name, self.connection)

        return self.channels[channel_name]

    def unsubscribe(self, channel_name):
        """Unsubscribe from a channel

        :param str channel_name: The name of the channel to unsubscribe from.
        """
        if channel_name in self.channels:
            self.connection.send_event(
                'pusher:unsubscribe', {
                    'channel': channel_name,
                }
            )
            del self.channels[channel_name]

    def channel(self, channel_name):
        """Get an existing channel object by name

        :param str channel_name: The name of the channel you want to retrieve
        :rtype: pysher.Channel or None
        """
        return self.channels.get(channel_name)

    def _connection_handler(self, event_name, data, channel_name):
        """Handle incoming data.

        :param str event_name: Name of the event.
        :param Any data: Data received.
        :param str channel_name: Name of the channel this event and data belongs to.
        """
        if channel_name in self.channels:
            self.channels[channel_name]._handle_event(event_name, data)

    def _reconnect_handler(self):
        """Handle a reconnect."""
        for channel_name, channel in self.channels.items():
            data = {'channel': channel_name}

            if channel.auth:
                data['auth'] = channel.auth

            self.connection.send_event('pusher:subscribe', data)

#    def _generate_auth_token(self, channel_name):
#        """Generate a token for authentication with the given channel.
#
#        :param str channel_name: Name of the channel to generate a signature for.
#        :rtype: str
#        """
#        subject = "{}:{}".format(self.connection.socket_id, channel_name)
#        h = hmac.new(self.secret_as_bytes, subject.encode('utf-8'), hashlib.sha256)
#        auth_key = "{}:{}".format(self.key, h.hexdigest())
#        print(auth_key)
#
#        return auth_key

    def _generate_auth_token(self, channel_name, authEndpoint, url_token, payload):
        """Generate a token for authentication with the given channel.

        :param str channel_name: Name of the channel to generate a signature for.
        :param str authEndpoint: url auth endpoint
        :param str url_token: url for request to get token
        :param str payload: login and password in json
        :rtype: str
        """
        self.auth_token = get_access_token(url=url_token, payload=payload)
        print('auth_token: ' + self.auth_token)

        headers = {'Accept': 'application/json', 'Authorization': self.auth_token}
        channel_name = "{}{}".format(channel_name, CHANNEL_ID)
        socket_id = self.connection.socket_id
        form_data = {'socket_id': socket_id, 'channel_name': channel_name}

        auth_response = requests.post(url=authEndpoint, headers=headers, json=form_data)
        auth_key_data = auth_response.json()
        auth_key = auth_key_data['auth']
        print(auth_key)

        return auth_key

    def _generate_presence_token(self, channel_name):
        """Generate a presence token.

        :param str channel_name: Name of the channel to generate a signature for.
        :rtype: str
        """
        subject = "{}:{}:{}".format(self.connection.socket_id, channel_name, json.dumps(self.user_data))
        h = hmac.new(self.secret_as_bytes, subject.encode('utf-8'), hashlib.sha256)
        auth_key = "{}:{}".format(self.key, h.hexdigest())

        return auth_key

    def _build_url(self, secure=True, port=None, custom_host=None):
        path = "/app/{}?client={}&version={}&protocol={}".format(
            self.key, self.client_id, VERSION, self.protocol
        )

        proto = "wss" if secure else "ws"

        host = custom_host or self.host
        if not port:
            port = 443 if secure else 80
        print("Connection url: {}://{}:{}{}".format(proto, host, port, path))
        return "{}://{}:{}{}".format(proto, host, port, path)
