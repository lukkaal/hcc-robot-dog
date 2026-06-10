import json
import requests
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

MQTT_BROKER = "106.52.191.198"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "S&D1V5L10MVFH1&247&1"
MQTT_USER = "mechanicalDog"
MQTT_PW = "U6IsxS0Erz+!o-.y1CNZUOv?"
MQTT_SUB_TOPIC = "/247/D1V5L10MVFH1/function/get"

GATEWAY_URL = "http://127.0.0.1:8000"

# 云端 moveAction → 本网关 API 端点
ACTION_MAP = {
    0: None,           # 停止 — 不调用，脉冲自然结束即停
    1: "forward",      # 前进
    2: "backward",     # 后退
    5: "turn-left",    # 左转
    6: "turn-right",   # 右转
}


class MqttBridge:
    """MQTT 桥接模块：订阅公网云端指令，翻译为本地 HTTP 调用"""

    def __init__(self, gateway_url: str = GATEWAY_URL):
        self.gateway_url = gateway_url
        self.client = mqtt.Client(CallbackAPIVersion.VERSION1, MQTT_CLIENT_ID)
        self.client.username_pw_set(MQTT_USER, MQTT_PW)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[MQTT Bridge] 已连接公网 Broker {MQTT_BROKER}")
            client.subscribe(MQTT_SUB_TOPIC)
            print(f"[MQTT Bridge] 已订阅云端指令通道: {MQTT_SUB_TOPIC}")
        else:
            print(f"[MQTT Bridge] 连接失败, rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            payload_str = msg.payload.decode("utf-8")
            print(f"[MQTT Bridge] <<< 收到云端指令: {payload_str}")
            self._dispatch(json.loads(payload_str))
        except Exception as e:
            print(f"[MQTT Bridge] 解析异常: {e}")

    def _dispatch(self, cmd_data):
        action = None
        duration = None

        if isinstance(cmd_data, list):
            for item in cmd_data:
                item_id = item.get("id")
                value = item.get("value")
                if item_id == "moveAction":
                    action = int(value)
                elif item_id == "moveDuration":
                    duration = float(value)

        if action is None:
            print(f"[MQTT Bridge] 未识别到 moveAction: {cmd_data}")
            return

        endpoint = ACTION_MAP.get(action)
        if endpoint is None:
            print(f"[MQTT Bridge] 动作码 {action} 无需/暂不支持下发 (停止/左移/右移)")
            return

        if duration is None:
            duration = 0.5

        url = f"{self.gateway_url}/api/{endpoint}"
        print(f"[MQTT Bridge] → {url}?duration={duration}")
        try:
            resp = requests.post(url, params={"duration": duration}, timeout=5)
            print(f"[MQTT Bridge] 响应: {resp.json()}")
        except Exception as e:
            print(f"[MQTT Bridge] HTTP 调用失败: {e}")

    def start(self):
        self.client.connect(MQTT_BROKER, MQTT_PORT)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT Bridge] 已断开")
