"""Quick MQTT connectivity test — paste credentials below and run."""

# ====== 在这里填写你的 MQTT 凭据 ======
BROKER = "1.12.248.179"
PORT = 1883
USERNAME = "mechanicalDog"
PASSWORD = "U6IsxS0Erz+!o-.y1CNZUOv?"
CLIENT_ID = "S&44010000001320000075&256&2001585437478027300"
# =====================================

import paho.mqtt.client as mqtt
import time

RC_MEANING = {
    0: "成功",
    1: "协议版本不匹配",
    2: "Client ID 被拒",
    3: "Broker 不可用",
    4: "用户名或密码错误",
    5: "未授权",
}

def on_connect(client, userdata, flags, rc):
    reason = RC_MEANING.get(rc, f"未知({rc})")
    print(f"CONNACK 返回码: rc={rc} — {reason}")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"断连, rc={rc}")

def test(broker, port, username, password, client_id):
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id)
    if username:
        client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    print(f"正在连接 {broker}:{port} ...")
    print(f"  Client ID: {client_id}")
    print(f"  Username:  {username}")
    try:
        client.connect(broker, port, keepalive=60)
        client.loop_start()
        time.sleep(3)
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        print(f"连接异常: {e}")

if __name__ == "__main__":
    test(BROKER, PORT, USERNAME, PASSWORD, CLIENT_ID)
