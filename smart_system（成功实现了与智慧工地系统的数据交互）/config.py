# config.py

# ================= 机器狗配置 =================
ROBOT_IP = "10.21.31.103"
ROBOT_PORT = 30001
HEARTBEAT_INTERVAL = 1.0  # 心跳发送频率(秒)

# ================= MQTT 配置 =================
MQTT_BROKER = "106.52.191.198"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "S&D1V5L10MVFH1&247&1"
MQTT_USER = "mechanicalDog"
MQTT_PW = "U6IsxS0Erz+!o-.y1CNZUOv?"

# 上行主题 (发数据)
MQTT_PUB_TOPIC = "/247/D1V5L10MVFH1/property/post"
# 下行主题 (收指令)
MQTT_SUB_TOPIC = "/247/D1V5L10MVFH1/function/get"

# ================= 业务配置 =================
UPLOAD_INTERVAL = 600.0     # 数据上报时间间隔(秒)