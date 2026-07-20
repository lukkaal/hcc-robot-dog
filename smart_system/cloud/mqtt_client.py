# cloud/mqtt_client.py
import paho.mqtt.client as mqtt
import json
from paho.mqtt.enums import CallbackAPIVersion
from config import MQTT_BROKER, MQTT_PORT, MQTT_CLIENT_ID, MQTT_USER, MQTT_PW, MQTT_PUB_TOPIC, MQTT_SUB_TOPIC

class MqttManager:
    def __init__(self, command_callback=None):
        self.command_callback = command_callback
        self.client = mqtt.Client(CallbackAPIVersion.VERSION1, MQTT_CLIENT_ID)
        self.client.username_pw_set(MQTT_USER, MQTT_PW)
        
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[MQTT] 已连接到服务器 {MQTT_BROKER}")
            self.client.subscribe(MQTT_SUB_TOPIC)
            print(f"[MQTT] 已订阅下行指令通道: {MQTT_SUB_TOPIC}")
        else:
            print(f"[MQTT] 连接失败, 状态码: {rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode('utf-8')
            print(f"\n[>>> 收到云端指令 <<<]\n内容: {payload_str}\n")
            if self.command_callback:
                self.command_callback(payload_str)
        except Exception as e:
            print(f"[MQTT] 指令解析异常: {e}")

    def publish_status(self, payload: list):
        self.client.publish(MQTT_PUB_TOPIC, json.dumps(payload, ensure_ascii=False))
        # pass

    def start(self):
        self.client.connect(MQTT_BROKER, MQTT_PORT)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()