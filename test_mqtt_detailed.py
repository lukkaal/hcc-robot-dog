"""MQTT Broker 详细连通性测试脚本"""

import socket
import time
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

BROKER_HOST = "1.12.248.179"
BROKER_PORT = 1883
CLIENT_ID = "S&D1V5L10MVFH1&247&1"
USERNAME = "mechanicalDog"
PASSWORD = "U6IsxS0Erz+!o-.y1CNZUOv?"

def test_tcp_connect(host, port, timeout=10):
    """测试 TCP 层能否连通"""
    print(f"[TCP] 正在连接 {host}:{port} (超时: {timeout}s)...")
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        print(f"[TCP] OK — {host}:{port} 可达")
        sock.close()
        return True
    except socket.timeout:
        print(f"[TCP] FAIL — 连接超时 ({timeout}s)")
        return False
    except ConnectionRefusedError:
        print(f"[TCP] FAIL — 连接被拒")
        return False
    except Exception as e:
        print(f"[TCP] FAIL — {e}")
        return False

def test_mqtt_connect(host, port, client_id, username, password, timeout=15):
    """测试 MQTT 协议层连接并获取详细错误信息"""

    result = {"success": False, "rc": None, "error": None}

    def on_connect(client, userdata, flags, reason_code, properties=None):
        print(f"[MQTT] 连接回调收到: reason_code={reason_code}")
        if hasattr(reason_code, 'value'):
            rc_val = reason_code.value
        else:
            rc_val = reason_code
        result["rc"] = rc_val
        if rc_val == 0:
            result["success"] = True
            print(f"[MQTT] OK — 认证通过，已成功连接到 {host}:{port}")
        else:
            result["error"] = f"连接失败，错误码: {rc_val}"
            print(f"[MQTT] FAIL — {result['error']}")

    def on_disconnect(client, userdata, flags, reason_code, properties=None):
        print(f"[MQTT] 连接断开: {reason_code}")

    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id)
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    print(f"[MQTT] 正在连接 Broker {host}:{port} (client_id={client_id})...")
    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()

        t0 = time.time()
        while not result["success"] and result["rc"] is None:
            if time.time() - t0 > timeout:
                print(f"[MQTT] FAIL — 连接超时（{timeout}s 内无响应）")
                break
            time.sleep(0.5)

        client.loop_stop()
        client.disconnect()

    except Exception as e:
        print(f"[MQTT] 异常 — {e}")
        result["error"] = str(e)
        return False

    return result["success"]

def test_with_different_client_ids():
    """尝试使用不同的客户端 ID 测试"""
    base_client_id = "S&D1V5L10MVFH1&247"
    for i in range(1, 4):
        client_id = f"{base_client_id}&{i}"
        print(f"[MQTT] 尝试使用客户端ID: {client_id}")

        result = {"success": False, "rc": None}

        def on_connect(client, userdata, flags, reason_code, properties=None):
            if hasattr(reason_code, 'value'):
                rc_val = reason_code.value
            else:
                rc_val = reason_code
            result["rc"] = rc_val
            result["success"] = (rc_val == 0)

        client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id)
        client.username_pw_set(USERNAME, PASSWORD)
        client.on_connect = on_connect

        try:
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            client.loop_start()

            t0 = time.time()
            while not result["success"] and result["rc"] is None:
                if time.time() - t0 > 10:
                    break
                time.sleep(0.5)

            client.loop_stop()
            client.disconnect()

            if result["success"]:
                print(f"[MQTT] 使用客户端ID {client_id} 连接成功!")
                return True

        except Exception as e:
            print(f"[MQTT] 客户端ID {client_id} 连接异常: {e}")

    return False

if __name__ == "__main__":
    print("=" * 60)
    print("MQTT Broker 详细连通性测试")
    print(f"目标: {BROKER_HOST}:{BROKER_PORT}")
    print(f"客户端ID: {CLIENT_ID}")
    print(f"用户名: {USERNAME}")
    print("=" * 60)

    # 1. TCP 层测试
    tcp_ok = test_tcp_connect(BROKER_HOST, BROKER_PORT)

    if not tcp_ok:
        print("\n[提示] TCP 连接失败，可能是以下原因之一：")
        print("- 服务器暂时不可达")
        print("- 防火墙阻止了连接")
        print("- 网络波动")
        print("- 服务器负载过高，响应缓慢")
    else:
        # 2. MQTT 协议层测试
        print("\n[TCP] 连接成功，继续测试 MQTT 协议层...")
        mqtt_ok = test_mqtt_connect(BROKER_HOST, BROKER_PORT, CLIENT_ID, USERNAME, PASSWORD)

        if not mqtt_ok:
            print("\n[MQTT] 连接失败，尝试使用不同客户端ID...")
            alt_ok = test_with_different_client_ids()

            if not alt_ok:
                print("[MQTT] 所有客户端ID尝试均失败")
            else:
                print("[MQTT] 成功找到可用的客户端ID")

    print("=" * 60)
    if tcp_ok and 'mqtt_ok' in locals() and mqtt_ok:
        print("结论: Broker 完全可达，MQTT 认证正常")
    elif tcp_ok:
        print("结论: TCP 可达但 MQTT 认证/协议层失败，检查账号密码或 Broker 配置")
    else:
        print("结论: 网络不通，检查防火墙/安全组/VPN")
    print("=" * 60)