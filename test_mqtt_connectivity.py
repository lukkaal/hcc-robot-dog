"""MQTT Broker 连通性测试脚本"""

import socket
import time
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

BROKER_HOST = "1.12.248.179"
BROKER_PORT = 1883
CLIENT_ID = "S&D1V5L10MVFH1&247&1"
USERNAME = "mechanicalDog"
PASSWORD = "U6IsxS0Erz+!o-.y1CNZUOv?"


def test_tcp_connect(host, port, timeout=5):
    """测试 TCP 层能否连通"""
    print(f"[TCP] 正在连接 {host}:{port} ...")
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        print(f"[TCP] OK — {host}:{port} 可达")
        return True
    except Exception as e:
        print(f"[TCP] FAIL — {e}")
        return False


def test_mqtt_connect(host, port, client_id, username, password, timeout=10):
    """测试 MQTT 协议层能否连接并订阅"""
    result = {"success": False, "rc": None}

    def on_connect(client, userdata, flags, rc):
        result["rc"] = rc
        if rc == 0:
            result["success"] = True

    client = mqtt.Client(CallbackAPIVersion.VERSION1, client_id)
    client.username_pw_set(username, password)
    client.on_connect = on_connect

    print(f"[MQTT] 正在连接 Broker {host}:{port} (client_id={client_id}) ...")
    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        t0 = time.time()
        while not result["success"] and result["rc"] is None:
            if time.time() - t0 > timeout:
                print("[MQTT] FAIL — 连接超时（无 CONNACK 响应）")
                break
            time.sleep(0.1)
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        print(f"[MQTT] FAIL — {e}")
        return False

    if result["success"]:
        print(f"[MQTT] OK — 认证通过，已成功连接到 {host}:{port}")
    else:
        print(f"[MQTT] FAIL — 连接被拒绝, rc={result['rc']}")
    return result["success"]


if __name__ == "__main__":
    print("=" * 50)
    print("MQTT Broker 连通性测试")
    print(f"目标: {BROKER_HOST}:{BROKER_PORT}")
    print("=" * 50)

    # 1. TCP 层
    tcp_ok = test_tcp_connect(BROKER_HOST, BROKER_PORT)

    # 2. MQTT 协议层
    if tcp_ok:
        mqtt_ok = test_mqtt_connect(BROKER_HOST, BROKER_PORT, CLIENT_ID, USERNAME, PASSWORD)
    else:
        print("[MQTT] 跳过（TCP 不通）")
        mqtt_ok = False

    print("=" * 50)
    if tcp_ok and mqtt_ok:
        print("结论: Broker 完全可达，MQTT 认证正常")
    elif tcp_ok:
        print("结论: TCP 可达但 MQTT 认证/协议层失败，检查账号密码或 Broker 配置")
    else:
        print("结论: 网络不通，检查防火墙/安全组/VPN")
    print("=" * 50)
