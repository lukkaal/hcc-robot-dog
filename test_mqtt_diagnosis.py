"""MQTT Broker 诊断性测试脚本"""

import socket
import time
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# 从 .env 读取配置
import os
from dotenv import load_dotenv
load_dotenv()

BROKER_HOST = os.getenv("MQTT_BROKER", "1.12.248.179")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))
USERNAME = os.getenv("MQTT_USER", "mechanicalDog")
PASSWORD = os.getenv("MQTT_PW", "U6IsxS0Erz+!o-.y1CNZUOv?")
MQTT_SUB_TOPIC = os.getenv("MQTT_SUB_TOPIC", "/247/D1V5L10MVFH1/function/get")

def test_basic_connectivity():
    """测试基础网络连通性"""
    print(f"[Network] 检查到服务器 {BROKER_HOST}:{BROKER_PORT} 的基础连接...")

    # 检查域名解析
    try:
        resolved_ip = socket.gethostbyname(BROKER_HOST)
        print(f"[DNS] {BROKER_HOST} 解析为 {resolved_ip}")
    except Exception as e:
        print(f"[DNS] 解析失败: {e}")
        return False

    # 检查 TCP 连接
    try:
        print(f"[TCP] 尝试连接到 {BROKER_HOST}:{BROKER_PORT}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)  # 10秒超时
        result = sock.connect_ex((BROKER_HOST, BROKER_PORT))
        sock.close()

        if result == 0:
            print(f"[TCP] 成功连接到 {BROKER_HOST}:{BROKER_PORT}")
            return True
        else:
            print(f"[TCP] 连接失败，错误码: {result}")
            return False
    except Exception as e:
        print(f"[TCP] 连接异常: {e}")
        return False

def test_mqtt_auth():
    """测试 MQTT 认证"""
    print(f"\n[MQTT] 开始认证测试...")
    print(f"[Config] 用户名: {USERNAME}")
    print(f"[Config] 密码长度: {len(PASSWORD)} 字符")
    print(f"[Config] 订阅主题: {MQTT_SUB_TOPIC}")

    # 尝试不同的客户端 ID
    test_client_ids = [
        f"TestClient_{int(time.time())}",
        f"Diagnostic_{os.urandom(4).hex()}",
        f"S&D1V5L10MVFH1&247&{int(time.time())%1000}"
    ]

    for client_id in test_client_ids:
        print(f"\n[MQTT] 尝试客户端ID: {client_id}")

        result = {"success": False, "rc": None, "error": None}

        def on_connect(client, userdata, flags, reason_code, properties=None):
            print(f"[MQTT] 连接回调 - Reason Code: {reason_code}")
            if hasattr(reason_code, 'value'):
                rc_val = reason_code.value
            else:
                rc_val = reason_code

            print(f"[MQTT] 详细RC值: {rc_val}")
            result["rc"] = rc_val
            if rc_val == 0:
                result["success"] = True
                print(f"[MQTT] ✅ 认证成功！已连接到 {BROKER_HOST}:{BROKER_PORT}")
            else:
                result["error"] = f"连接失败，错误码: {rc_val}"
                print(f"[MQTT] ❌ 连接失败 - 错误码: {rc_val}")

                # 常见错误码解释
                error_codes = {
                    1: "连接被拒绝 - 不正确的协议版本",
                    2: "连接被拒绝 - 不正确的客户端标识符",
                    3: "连接被拒绝 - 服务器不可用",
                    4: "连接被拒绝 - 错误的用户名或密码",
                    5: "连接被拒绝 - 未授权",
                    134: "连接断开（常见于认证失败或 ID 冲突）"
                }
                if rc_val in error_codes:
                    print(f"[MQTT] 错误说明: {error_codes[rc_val]}")

        def on_disconnect(client, userdata, flags, reason_code, properties=None):
            print(f"[MQTT] 断开连接 - Reason Code: {reason_code}")

        def on_log(client, userdata, level, buf):
            print(f"[MQTT Log] Level={level}, Message={buf}")

        try:
            client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id)
            client.username_pw_set(USERNAME, PASSWORD)
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            # client.on_log = on_log  # 如果需要详细日志可以取消注释

            print(f"[MQTT] 正在连接 {BROKER_HOST}:{BROKER_PORT} (ID: {client_id})...")
            client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
            client.loop_start()

            # 等待连接结果
            timeout = 15
            start_time = time.time()
            while result["rc"] is None and (time.time() - start_time) < timeout:
                time.sleep(0.5)

            client.loop_stop()
            client.disconnect()

            if result["success"]:
                print(f"[MQTT] 🎉 客户端 {client_id} 连接成功!")
                return True
            else:
                print(f"[MQTT] 客户端 {client_id} 连接失败")

        except Exception as e:
            print(f"[MQTT] 连接异常 ({client_id}): {e}")

    return False

if __name__ == "__main__":
    print("=" * 70)
    print("MQTT Broker 诊断性测试")
    print(f"目标: {BROKER_HOST}:{BROKER_PORT}")
    print("=" * 70)

    # 1. 基础连通性测试
    network_ok = test_basic_connectivity()

    if not network_ok:
        print("\n❌ 网络层面连接失败，无法进行 MQTT 测试")
        print("可能的原因:")
        print("- 网络策略限制访问该 IP 和端口")
        print("- 防火墙阻止了连接")
        print("- 目标服务器不可达")
        print("- DNS 解析问题")
    else:
        print("\n✅ 网络层面连接正常，继续 MQTT 测试...")
        # 2. MQTT 认证测试
        mqtt_ok = test_mqtt_auth()

        if mqtt_ok:
            print("\n🎉 MQTT 连接测试成功!")
        else:
            print("\n❌ MQTT 连接测试失败")
            print("\n建议排查方向:")
            print("1. 检查用户名和密码是否正确")
            print("2. 确认服务器端口是否为 1883 (或尝试 8883)")
            print("3. 检查防火墙和安全组设置")
            print("4. 联系服务器管理员确认服务状态")

    print("=" * 70)