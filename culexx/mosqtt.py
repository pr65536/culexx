import re
import sys
import paho.mqtt.client as mosquitto
from blinker import signal
from .clogging import default_logger as log

class MQTTException(Exception):

    MQTTCLIENT_ERRORS = {
        '1' : 'unacceptable protocol version',
        '2' : 'identifier rejected',
        '3' : 'server unavailable',
        '4' : 'bad user name or password',
        '5' : 'not authorised',
        '6' : 'not found',        
        '7' : 'connection lost',
        '8' : 'TLS',        
        '9' : 'payload size',        
        '10' : 'not supported',        
        '11' : 'auth',        
        '12' : 'access denied',        
        '13' : 'unknown',        
        '14' : 'errno'
    }

    def __init__(self, error_code):
        key = "%s" % error_code
        message = self.MQTTCLIENT_ERRORS[key]
        Exception.__init__(self, message)


class SubscriptionState(object):
    PENDING = 0
    SUBSCRIBED = 1
    UNSUBSCRIBED = 2


class TopicMapper(object):

    TOPIC_FILTER_REGEX = "^(?P<client_id>[\w]+-\d+)(?P<topic_name>\/[\w\/]+)$"

    def __init__(self, mosqtt, topic_handlers={}):
        if not isinstance(topic_handlers, dict):
            raise TypeError("Expected dict but got %s" % type(topic_handlers))
        self.mosqtt = mosqtt
        self.topic_handlers = topic_handlers

    @property
    def topics(self):
        return self.topic_handlers

    def handle_topic(self, topic, payload):
        m = re.match(self.TOPIC_FILTER_REGEX, topic)
        try:
            topic = m.group('topic_name')
            func = self.topic_handlers.get(topic, None)
            log.debug(topic)
            log.debug(func)
            if hasattr(self.mosqtt, func):
                return getattr(self.mosqtt, func)(payload)
        except Exception as e:
            log.warn(e)


from types import MethodType

class SignalMapper(object):

    def __init__(self, mosqtt, callbacks={}):
        self.mosqtt = mosqtt
        self.sig_on_message = signal('on_message')
        self.sig_on_connect = signal('on_connect')
        self.sig_on_disconnect = signal('on_disconnect')
        self.sig_on_publish = signal('on_publish')
        self.sig_on_subscribe = signal('on_subscribe')
        self.sig_on_unsubscribe = signal('on_unsubscribe')
        self.sig_on_log = signal('on_log')
        self.callbacks = callbacks
        self.map_callbacks(self.callbacks)

    def map_callbacks(self, cb_map):
        for signal, funcs in cb_map.iteritems():
            sig_name = "sig_{0}".format(signal)
            sig = getattr(self, sig_name, None)
            if sig:
                for f_name in funcs:

                    func = getattr(self.mosqtt, f_name, None)
                    if func:
                        setattr(self.mosqtt, f_name, sig.connect(MethodType(func, self.mosqtt)))

    def on_connect(self, mosq, obj, rc):
        self.sig_on_connect.send(self.mosqtt, mosq=mosq, obj=obj, rc=rc)

    def on_publish(self, mosq, obj, rc):
        self.sig_on_publish.send(self.mosqtt, mosq=mosq, obj=obj, rc=rc)

    def on_subscribe(self, mosq, obj, mid, granted_qos):
        self.sig_on_subscribe.send(self.mosqtt, mosq=mosq, obj=obj, mid=mid, qos=granted_qos)

    def on_unsubscribe(self, mosq, obj, mid):
        self.sig_on_unsubscribe.send(self.mosqtt, mosq=mosq, obj=obj, mid=mid)

    def on_disconnect(self, mosq, obj, rc):
        self.sig_on_disconnect.send(self.mosqtt, mosq=mosq, obj=obj, rc=rc)

    def on_message(self, mosq, obj, msg):
        self.sig_on_message.send(self.mosqtt, mosq=mosq, obj=obj, msg=msg)

    def on_log(self, mosq, obj, level, string):
        # log messages
        self.sig_on_log.send(self.mosqtt, mosq=mosq, obj=obj, level=level, string=string)


class Mosqtt(object):

    MQTTHOST = "127.0.0.1"
    MQTTPORT = 1880
    TIMEOUT = 60

    _signals_class = SignalMapper
    _topics_class = TopicMapper

    _default_sig_handlers = { 'on_connect': (,), 'on_disconnect': (,) }

    class Meta(object):
        pass

    def __init__(self, prefix='mqttc', name='', broker=MQTTHOST, port=MQTTPORT, timeout=TIMEOUT):
        self.prefix = prefix
        self.broker = broker
        self.port = port
        self.timeout = timeout
        self.prefix = prefix
        self.name = name
        self._mqtt_client = None
        self._setup = False
        self._subscriptions = None
        self._unsubscribe_mids = {}
        self._subscribe_mids = {}
        self.signal_mapper = self._signals_class(self, getattr(self.Meta, 'signal_handlers',{}))
        self.topic_mapper = self._topics_class(getattr(self.Meta, 'topic_handlers',{}))

    def setup_callbacks(self):
        log.debug("setting up callbacks...")
        self.mqtt_client.on_log = self.signal_mapper.on_log
        self.mqtt_client.on_connect = self.signal_mapper.on_connect
        self.mqtt_client.on_subscribe = self.signal_mapper.on_subscribe
        self.mqtt_client.on_publish = self.signal_mapper.on_publish
        self.mqtt_client.on_unsubscribe = self.signal_mapper.on_unsubscribe
        self.mqtt_client.on_disconnect = self.signal_mapper.on_disconnect
        self.mqtt_client.on_message = self.signal_mapper.on_message

    @property
    def topics(self):
        return self.topic_mapper.topics

    @property
    def callbacks(self):
        return self.signal_mapper.callbacks

    @property
    def client_id(self):
        if not hasattr(self, '_client_id'):
            setattr(self, '_client_id', "{0}-{1}".format(self.prefix, self.name))
        return self._client_id

    @property
    def mqtt_client(self):
        if self._mqtt_client is None:
            self._mqtt_client = mosquitto.Mosquitto(self.client_id)
        return self._mqtt_client

    @property
    def subscriptions(self):
        self._subscriptions = self._subscriptions or {}
        return self._subscriptions

    def normalize_topic(self, topic):
        return  "{0}{1}".format(self.client_id, topic)

    def handler_for_topic(self, topic):
        return self.topic_mapper.handler_for_topic(topic)

    def pending_subscribe(self, mid):
        return self._subscribe_mids.get(mid, None)

    def pending_unsubscribe(self, mid):
        return self._unsubscribe_mids.get(mid, None)

    def subscribe(self, topic, qos=0):
        normalized_topic = self.normalize_topic(topic)
        rc, mid = self.mqtt_client.subscribe(normalized_topic, qos)
        self.subscriptions[normalized_topic] = SubscriptionState.PENDING # fixme
        self._subscribe_mids[mid] = normalized_topic # fixme
        return (rc, mid)

    def unsubscribe(self, topic):
        normalized_topic = self.normalize_topic(topic)
        rc, mid =  self.mqtt_client.unsubscribe(normalized_topic)
        self._unsubscribe_mids[mid] = normalized_topic # fixme
        return (rc, mid)

    def disconnect(self):
        self.mqtt_client.loop_stop()
        self.cleanup()
        return self.mqtt_client.disconnect()

    def cleanup(self):
        log.debug("cleaning up...")

    def setup_subscriptions(self):
        log.debug("setting up subscriptions...")
        for topic in self.topics.keys():
            self.subscribe(topic)

    def connect(self, loop_forever=True):
        if self._setup == True:
            return self.reconnect()

        self.setup_callbacks()

        log.debug("establishing connection to broker...")
        self.mqtt_client.connect(self.broker, self.port, self.timeout)

        self._setup = True

        if loop_forever:
            self.mqtt_client.loop_forever()
        else:
            self.mqtt_client.loop_start()

    def reconnect(self):
        try:
            return self.mqtt_client.reconnect()
        except:
            log.warn("Failed to reconnect!!!")
            raise

    def publish(self, topic, payload, qos=1, retain=False):
        rc = self.mqtt_client.loop()

        if rc == mosquitto.MQTT_ERR_NO_CONN:
            log.debug("reconnect result: %s" % rc)
            rc = self.reconnect()

        if rc == mosquitto.MQTT_ERR_SUCCESS:
            try:
                return self.mqtt_client.publish(self.normalize_topic(topic), payload, qos, retain)
            except:
                e = sys.exc_info()[0]
                log.warn("uh-oh! time to die: %s" % e)
                self.cleanup()
                raise
        else:
            raise MQTTException(rc)