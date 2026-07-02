"""发送云端指令到 MQTT，测试机器狗控制链路"""

BROKER = "1.12.248.179"
PORT = 1883
USERNAME = "mechanicalDog"
PASSWORD = "U6IsxS0Erz+!o-.y1CNZUOv?"
CLIENT_ID = "sender_test_001"
TOPIC = "/247/D1V5L10MVFH1/function/get"

import paho.mqtt.client as mqtt
import json
import time
import sys

ACTIONS = {
    "0": "停止",
    "1": "前进",
    "2": "后退",
    "5": "左转",
    "6": "右转",
}


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("已连接 Broker\n")
    else:
        print(f"连接失败, rc={rc}")
        sys.exit(1)


def send_command(action: int, duration: float = 0.5):
    payload = json.dumps([
        {"id": "moveAction", "value": action},
        {"id": "moveDuration", "value": duration},
    ])
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, CLIENT_ID)
    client.username_pw_set(USERNAME, PASSWORD)
    client.on_connect = on_connect
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()
    time.sleep(1)
    client.publish(TOPIC, payload)
    client.loop_stop()
    client.disconnect()
    print(f"已发送: {ACTIONS[str(action)]}，时长 {duration}s")
    print(f"Topic: {TOPIC}")
    print(f"Payload: {payload}")


def interactive():
    print("=" * 40)
    print("  机器狗指令发送器")
    print("=" * 40)
    print("\n指令:")
    for k, v in ACTIONS.items():
        print(f"  {k} — {v}")
    print("  q — 退出")
    print()

    while True:
        cmd = input("输入指令号 > ").strip()
        if cmd.lower() == "q":
            break
        if cmd not in ACTIONS:
            print("无效指令\n")
            continue
        dur = input("时长(秒, 默认0.5) > ").strip()
        try:
            dur = float(dur) if dur else 0.5
        except ValueError:
            dur = 0.5
        send_command(int(cmd), dur)
        print()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # 命令行模式: python send_cmd.py 1 0.5
        action = int(sys.argv[1])
        duration = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
        send_command(action, duration)
    else:
        interactive()
