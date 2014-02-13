from __future__ import absolute_import
from nose.tools import raises
from mock import Mock
import paho.mqtt.client as mosquitto

from ..mosqtt import *

# class TestClientMeta(MosqttMeta):
#     def __new__(cls, name, bases, attrs):
#         sig_handlers = attrs.get('signal_handlers', {})
#         for signal, handler_list in sig_handlers.iteritems():
#             for h in handler_list:
#                 if not attrs.get(h, False):
#                     continue
#                 attrs[h] = lambda *args: log.warn('signal fired')
#         return super(TestClientMeta, cls).__new__(cls, name, bases, attrs)

class TestClient(Mosqtt):

    class Meta(object):
        signal_handlers = {
            'on_connect': ('handle_connect',),
            'on_disconnect': ('handle_disconnect',),
            'on_subscribe': ('handle_subscribe',),
            'on_unsubscribe': ('handle_unsubscribe',),
            'on_publish': ('handle_publish',),
            'on_message': ('handle_message',),
            'on_log': ('handle_log',)
        }

        topic_handlers  = {
            '/topic': 'handle_topic',
        }

    def handle_topic(self, *args, **kwargs):
        pass

    def handle_connect(self, *args, **kwargs):
        log.warn('****************')

    def handle_disconnect(self, *args, **kwargs):
        pass

    def handle_subscribe(self, *args, **kwargs):
        pass

    def handle_unsubscribe(self, *args, **kwargs):
        pass

    def handle_message(self, *args, **kwargs):
        pass

    def handle_publish(self, *args, **kwargs):
        pass

    def handle_log(self, *args, **kwargs):
        pass

class TestBaseClient:

    def setUp(self):
        self.client = TestClient(name='test-000')
        self.mqttc = mosquitto.Mosquitto('mqttc-test-000')
        self.default_broker = TestClient.MQTTHOST
        self.default_port = TestClient.MQTTPORT
        self.default_timeout = TestClient.TIMEOUT

    def test_default_parameters(self):
        assert self.client.broker == self.default_broker
        assert self.client.port == self.default_port
        assert self.client.timeout == self.default_timeout
        assert self.client._mqtt_client == None
        assert self.client._setup == False

    def test_mqtt_client_returns_mosquitto_client(self):
        assert isinstance(self.client.mqtt_client, mosquitto.Mosquitto)

    def test_mqtt_client_is_memoized(self):
        client = self.client.mqtt_client 
        assert client == self.client.mqtt_client

    def test_channel_id(self):
        assert self.client.client_id == "{0}-{1}".format(self.client.prefix, self.client.name)

    def test_topics(self):
        assert self.client.callbacks == {'on_subscribe': ('handle_subscribe',),
                                        'on_message': ('handle_message',),
                                        'on_connect': ('handle_connect',),
                                        'on_log': ('handle_log',),
                                        'on_disconnect': ('handle_disconnect',),
                                        'on_unsubscribe': ('handle_unsubscribe',),
                                        'on_publish': ('handle_publish',)
                                        }

    def test_callbacks(self):
        assert self.client.topics == {'/topic': 'handle_topic'}

    def test_connect(self):
        self.client._mqtt_client = Mock()
        self.client.setup_callbacks = Mock(return_value=None)
        self.client.connect()
        self.client.setup_callbacks.assert_called_once_with()
        self.client._mqtt_client.connect.assert_called_once_with(self.default_broker, self.default_port, self.default_timeout)
        assert self.client._setup == True

    def test_disconnect(self):
        self.client._mqtt_client = self.mqttc
        self.client._mqtt_client.disconnect = Mock(return_value=None)
        self.client.disconnect()
        self.client._mqtt_client.disconnect.assert_called_once_with()

    def test_reconnect(self):
        self.client._mqtt_client = self.mqttc
        self.client._mqtt_client.reconnect = Mock(return_value=None)
        self.client.reconnect()
        self.client._mqtt_client.reconnect.assert_called_once_with()

    def test_subscribe_with_default_qos(self):
        self.client._mqtt_client = self.mqttc
        self.client._mqtt_client.subscribe = Mock(return_value=(0, 0))
        self.client.subscribe('/messages')
        self.client._mqtt_client.subscribe.assert_called_once_with('mqttc-test-000/messages', 0)

    def test_subscribe_with_custom_qos(self):
        self.client._mqtt_client = self.mqttc
        self.client._mqtt_client.subscribe = Mock(return_value=(0, 0))
        self.client.subscribe('/messages', 2)
        self.client._mqtt_client.subscribe.assert_called_once_with('mqttc-test-000/messages', 2)

    def test_unsubscribe(self):
        self.client._mqtt_client = self.mqttc
        self.client._mqtt_client.unsubscribe = Mock(return_value=(0, 0))
        self.client.unsubscribe('/messages')
        self.client._mqtt_client.unsubscribe.assert_called_once_with('mqttc-test-000/messages')

    def test_sucessful_publish_when_connection_active(self):
        self.client._mqtt_client = mosquitto.Mosquitto('mqttc-test-000')
        self.client._mqtt_client.publish = Mock(return_value=None)
        self.client._mqtt_client.loop = Mock(return_value=mosquitto.MQTT_ERR_SUCCESS)
        self.client.publish('/messages', 'hi')
        self.client._mqtt_client.publish.assert_called_once_with('mqttc-test-000/messages', 'hi', 1, False)

    def test_sucessful_publish_when_connection_lost(self):
        self.client._mqtt_client = mosquitto.Mosquitto('mqttc-test-000')
        self.client._mqtt_client.publish = Mock(return_value=None)
        self.client._mqtt_client.loop = Mock(return_value=mosquitto.MQTT_ERR_NO_CONN)
        self.client.reconnect = Mock(return_value=mosquitto.MQTT_ERR_SUCCESS)
        self.client.publish('/messages', 'hi')
        self.client.reconnect.assert_called_once_with()
        self.client._mqtt_client.publish.assert_called_once_with('mqttc-test-000/messages', 'hi', 1, False)

    @raises(MQTTException)
    def test_failed_publish_when_connection_lost(self):
        self.client._mqtt_client = self.mqttc
        self.client._mqtt_client.publish = Mock(return_value=None)
        self.client._mqtt_client.loop = Mock(return_value=mosquitto.MQTT_ERR_NO_CONN)
        self.client.reconnect = Mock(return_value=mosquitto.MQTT_ERR_ERRNO)
        self.client.publish('mqttc-test-001/messages', 'hi')
        self.client.reconnect.assert_called_once_with()

    def test_on_connect_signal(self):
        self.client._mqtt_client = self.mqttc
        self.client._mqtt_client.loop_forever = Mock(return_value=mosquitto.MQTT_ERR_SUCCESS)
        self.client._mqtt_client.connect = Mock(return_value=None)
        self.client.signal_mapper.sig_on_connect.send = Mock(return_value=None)
        self.client.connect()
        self.client._mqtt_client.on_connect(self.client.mqtt_client, None, None)
        self.client.signal_mapper.sig_on_connect.send.assert_called_once_with(self.client, mosq=self.mqttc, obj=None, rc=None)