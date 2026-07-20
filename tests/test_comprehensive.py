#!/usr/bin/env python3
"""
MQTT 连接综合测试脚本
测试网络连通性、MQTT 服务器可达性以及认证信息
"""

import os
import socket
import time
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
from dotenv import load_dotenv
load_dotenv()

def test_network_connectivity(host, port):
    """测试基础网络连通性"""
    print(f"[网络测试] 正在测试到 {host}:{port} 的基础网络连通性...")

    try:
        # 解析域名
        resolved_ip = socket.gethostbyname(host)
        print(f"[DNS] {host} 解析为 {resolved_ip}")

        # 测试 TCP 连接
        print(f"[TCP] 正在连接 {host}:{port}...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            print(f"[TCP] ✅ 成功连接到 {host}:{port}")
            return True
        else:
            print(f"[TCP] ❌ 连接失败，错误码: {result}")
            return False

    except socket.gaierror as e:
        print(f"[DNS] ❌ 域名解析失败: {e}")
        return False
    except Exception as e:
        print(f"[TCP] ❌ 连接异常: {e}")
        return False

def test_mqtt_authentication(host, port, client_id, username, password, timeout=10):
    """测试 MQTT 认证"""
    print(f"[MQTT] 正在测试 MQTT 认证...")
    print(f"  客户端ID: {client_id}")
    print(f"  用户名: {username}")
    print(f"  密码长度: {len(password)} 字符")

    result = {"success": False, "rc": None, "error_msg": ""}

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if hasattr(reason_code, 'value'):
            rc = reason_code.value
        else:
            rc = reason_code
        result["rc"] = rc

        if rc == 0:
            result["success"] = True
            print(f"[MQTT] ✅ 认证成功！连接到 {host}:{port}")
        else:
            error_messages = {
                1: "协议版本错误",
                2: "客户端标识符错误",
                3: "服务器不可用",
                4: "用户名或密码错误",
                5: "未授权",
                134: "连接断开（认证失败或ID冲突）"
            }
            error_msg = error_messages.get(rc, f"未知错误码 {rc}")
            result["error_msg"] = error_msg
            print(f"[MQTT] ❌ 认证失败，rc={rc}: {error_msg}")

    def on_disconnect(client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            print(f"[MQTT] 连接断开，rc={reason_code}")

    try:
        client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id)
        client.username_pw_set(username, password)
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect

        client.connect(host, port, keepalive=60)
        client.loop_start()

        # 等待连接结果
        start_time = time.time()
        while result["rc"] is None and (time.time() - start_time) < timeout:
            time.sleep(0.2)

        client.loop_stop()
        client.disconnect()

        return result["success"]

    except Exception as e:
        print(f"[MQTT] ❌ 连接异常: {e}")
        return False

def main():
    # 配置信息（从 .env 读取）
    BROKER_HOST = os.environ["MQTT_BROKER"]
    BROKER_PORT = int(os.environ.get("MQTT_PORT", "1883"))
    CLIENT_ID = os.environ["MQTT_CLIENT_ID"]
    USERNAME = os.environ["MQTT_USER"]
    PASSWORD = os.environ["MQTT_PW"]

    print("=" * 60)
    print("MQTT 连接综合测试")
    print("=" * 60)

    # 1. 测试网络连通性
    network_ok = test_network_connectivity(BROKER_HOST, BROKER_PORT)

    if not network_ok:
        print("\n❌ 网络连接失败，无法进行 MQTT 测试")
        print("解决方案建议:")
        print("- 检查网络连接")
        print("- 确认防火墙设置")
        print("- 验证目标服务器IP和端口")
        return

    # 2. 测试 MQTT 认证
    print()
    auth_ok = test_mqtt_authentication(BROKER_HOST, BROKER_PORT, CLIENT_ID, USERNAME, PASSWORD)

    print()
    print("=" * 60)
    print("测试结果汇总:")
    print(f"- 网络连通性: {'✅ 通过' if network_ok else '❌ 失败'}")
    print(f"- MQTT 认证: {'✅ 通过' if auth_ok else '❌ 失败'}")

    if network_ok and auth_ok:
        print("\n🎉 所有测试通过！MQTT 连接应该可以正常工作")
    elif network_ok and not auth_ok:
        print("\n⚠️  网络连接正常，但认证失败")
        print("可能的解决方案:")
        print("- 检查用户名和密码是否正确")
        print("- 确认客户端ID是否正确")
        print("- 验证服务器端是否启用了该账户")
    else:
        print("\n❌ 连接失败，请检查网络配置")

    print("=" * 60)

if __name__ == "__main__":
    main()