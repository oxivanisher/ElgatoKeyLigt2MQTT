#!/usr/bin/env python3


import paho.mqtt.client as mqtt
import os
import logging
import leglight
import time


log_level = logging.INFO
if os.getenv('DEBUG', False):
  log_level = logging.DEBUG

logging.basicConfig(
  format='%(asctime)s %(levelname)-7s %(message)s',
  datefmt='%Y-%d-%m %H:%M:%S',
  level=log_level
)


class KeyLight2MQTT:

    def __init__(self):
        self.mqtt_server = os.getenv('MQTT_SERVER', 'localhost')
        self.mqtt_port = os.getenv('MQTT_PORT', 1883)
        self.mqtt_user = os.getenv('MQTT_USER', None)
        self.mqtt_password = os.getenv('MQTT_PASSWORD', None)
        self.mqtt_base_topic = os.getenv('MQTT_BASE_TOPIC', 'ElgatoKeyLights')

        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.mqtt_on_connect
        self.mqtt_client.on_message = self.mqtt_on_message

        self.all_lights = []
        self.last_light_discover = 0

    def set_light_power(self, light, state, power="on"):
        if power == "on":
            if not state['on']:
                light.on()
                logging.debug("Light on")
        else:
            if state['on']:
                light.off()
                logging.debug("Light off")

    def mqtt_on_connect(self, client, userdata, flags, rc):
        logging.info("MQTT: Connected with result code "+str(rc))

        # Subscribing in on_connect() means that if we lose the connection and
        # reconnect then subscriptions will be renewed.
        topic = "%s/set/#" % self.mqtt_base_topic
        logging.info("MQTT: Subscribing to %s" % topic)
        client.subscribe(topic)

    def mqtt_on_message(self, client, userdata, msg):
        logging.debug("MQTT: Msg recieved on <%s>: <%s>" % (msg.topic, str(msg.payload)))
        what = msg.topic.split("/")[-1]
        serial = msg.topic.split("/")[-2]
        value = msg.payload.decode("utf-8")
        logging.info("Setting %s on elgato light %s to %s" % (what, serial, value))
        for light in self.all_lights:
            if serial.lower() != light.serialNumber.lower():
                # do nothing if we are the wrong light
                continue

            # fetch current light state
            state = light.info()

            if what == "power":
                self.set_light_power(light, state, value)
            elif what == "brightness":
                value = int(value)
                if state['brightness'] != value:
                    light.brightness(value)
                    logging.debug("Brightness to %s" % value)
            elif what == "color":
                value = int(value)
                if state['temperature'] != value:
                    light.color(value)
                    logging.debug("Temperature to %s" % value)

    def discover_lights(self):
        # Cache results, discover only when needed (e.g., every 10 minutes)
        lights_before = len(self.all_lights)
        cache_duration = 600  # Cache results for 10 minutes

        # Only discover if cache is empty or older than cache_duration
        if not self.all_lights or time.time() - self.last_light_discover > cache_duration:
            logging.debug("Starting to discover lights...")
            try:
                discovered_lights = leglight.discover(2)  # Time to wait for discovery
                self.last_light_discover = time.time()

                # Merge new lights with existing lights, removing duplicates based on serial number
                all_serials = {light.serialNumber.lower() for light in self.all_lights}
                for new_light in discovered_lights:
                    if new_light.serialNumber.lower() not in all_serials:
                        self.all_lights.append(new_light)
                        all_serials.add(new_light.serialNumber.lower())

                if lights_before != len(self.all_lights):
                    logging.info("Found %s Elgato lights:" % len(self.all_lights))
                    for light in self.all_lights:
                        logging.info("  %s" % light)

            except OSError as err:
                self.last_light_discover = time.time() - 30  # Retry sooner if error occurs
                logging.error("OS error: {0}".format(err))
                logging.error("Critical error in light discovery, exiting...")
                sys.exit(1)  # Exit to trigger restart in systemd
        else:
            logging.debug("Using cached lights, skipping discovery.")


    def run(self):
        if self.mqtt_user:
            self.mqtt_client.username_pw_set(self.mqtt_user, self.mqtt_password)

        while True:
            logging.info("Waiting for MQTT server...")

            connected = False
            while not connected:
                try:
                    self.mqtt_client.connect(self.mqtt_server, int(self.mqtt_port), 60)
                    connected = True
                    logging.info("Connection successful")
                except ConnectionRefusedError:
                    logging.error("Failed to connect to MQTT server, retrying...")
                    time.sleep(1)

            try:
                while True:
                    self.discover_lights()
                    return_value = self.mqtt_client.loop()
                    if return_value:
                        logging.error("MQTT client loop returned <%s>. Exiting..." % return_value)
                        sys.exit(1)  # Exit on critical MQTT loop errors
            except Exception as e:
                logging.error("Unhandled exception occurred: %s", e)
                sys.exit(1)  # Exit on unexpected exceptions
            finally:
                self.mqtt_client.disconnect()
                connected = False


if __name__ == "__main__":
    kl = KeyLight2MQTT()
    kl.run()
