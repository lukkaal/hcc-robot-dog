# config.py

import os
from dotenv import load_dotenv
load_dotenv()

# ================= 机器狗配置 =================
ROBOT_IP = os.environ.get("ROBOT_IP", "10.21.31.103")
ROBOT_PORT = int(os.environ.get("ROBOT_PORT", "30001"))
HEARTBEAT_INTERVAL = 1.0  # 心跳发送频率(秒)

# ================= MQTT 配置 =================
MQTT_BROKER = os.environ.get("MQTT_BROKER", "")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_CLIENT_ID = os.environ.get("MQTT_CLIENT_ID", "")
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PW = os.environ.get("MQTT_PW", "")

# 上行主题 (发数据)
MQTT_PUB_TOPIC = os.environ.get("MQTT_PUB_TOPIC", "")
# 下行主题 (收指令)
MQTT_SUB_TOPIC = os.environ.get("MQTT_SUB_TOPIC", "")

# ================= 业务配置 =================
UPLOAD_INTERVAL = 600.0     # 数据上报时间间隔(秒)