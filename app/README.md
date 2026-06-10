# 山猫M20 遥控网关

基于 FastAPI 的机器狗 Web 遥控面板，支持前后移动、左右转向及实时视频监控。内置 MQTT 桥接模块，打通了云端智慧工地平台到机器狗的远程控制链路。

## 部署架构

```
                         公网                              局域网 (10.21.31.x)
 ┌──────────┐    MQTT     ┌──────────────────────────────┐    UDP:30000    ┌──────────┐
 │ 智慧工地  │ ←────────→ │         网关 PC               │ ──────────────→ │ 山猫M20  │
 │ 云平台    │  :1883     │                              │                 │ 机器狗   │
 └──────────┘            │  ┌──────────┐  ┌───────────┐ │ ←──RTSP:8554── │          │
                         │  │ MQTT桥接 │→│ FastAPI    │ │                └──────────┘
 ┌──────────┐   HTTP     │  │ 收云端指令│ │ :8000      │ │
 │ 现场操作员│ ←────────→ │  └──────────┘  │            │ │
 │ 手机/平板 │  :8000     │                │ 控制API ×4 │ │
 │ (浏览器)  │           │                │ 视频API ×1 │ │
 └──────────┘            └──────────────────────────────┘
```

**两条控制链路：**
1. **本地**：浏览器按住按钮 → HTTP :8000 → UDP → 狗（现场操作员）
2. **远程**：云平台 → MQTT 公网 → MQTT桥接 → HTTP :8000 → UDP → 狗（云端远程控制）

**视频链路：** 狗 → RTSP → 网关 → MJPEG :8000 → 仅局域网（现场操作员可看）

## 快速启动

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后：
- 浏览器打开 `http://localhost:8000` — Web 遥控面板
- MQTT 桥接自动连接公网 Broker，云端指令实时下发

## 项目结构

```
app/
├── main.py              # FastAPI 入口，生命周期管理
├── robot_client.py      # 机器狗 UDP 控制协议封装
├── mqtt_bridge.py       # MQTT 桥接：云端指令 → 本地 HTTP
├── requirements.txt
├── README.md
└── static/
    └── index.html       # Web 遥控面板
```

## API 手册

基址: `http://<网关IP>:8000`

| 端点 | 方法 | 参数 | 说明 |
|---|---|---|---|
| `/api/forward` | POST | `duration` (float, 可选, 默认0.5) | 前进，运动指定秒数后自动停止 |
| `/api/backward` | POST | `duration` (float, 可选, 默认0.5) | 后退 |
| `/api/turn-left` | POST | `duration` (float, 可选, 默认0.5) | 左转（绕Z轴逆时针） |
| `/api/turn-right` | POST | `duration` (float, 可选, 默认0.5) | 右转（绕Z轴顺时针） |
| `/api/video` | GET | — | MJPEG 视频流（仅局域网） |

### 响应格式

```json
{"status": "ok", "action": "forward", "speed": 0.1}
```

### 调用示例

```bash
# 前进 1 秒
curl -X POST "http://10.21.31.100:8000/api/forward?duration=1.0"

# 左转 2 秒
curl -X POST "http://10.21.31.100:8000/api/turn-left?duration=2.0"

# 后退（默认 0.5 秒）
curl -X POST "http://10.21.31.100:8000/api/backward"
```

## 实际调用场景

两条控制链路对应两种使用场景：

### 场景一：现场操作员（局域网 Web 面板）

操作员在局域网内，手机/平板浏览器打开 `http://<网关IP>:8000`，按住面板按钮即可遥控。

也可以直接调 HTTP API（适合脚本/自动化）：

```bash
# 前进 1 秒
curl -X POST "http://10.21.31.100:8000/api/forward?duration=1.0"

# 左转 2 秒
curl -X POST "http://10.21.31.100:8000/api/turn-left?duration=2.0"

# 后退（默认 0.5 秒）
curl -X POST "http://10.21.31.100:8000/api/backward"
```

### 场景二：云端智慧工地平台（远程 MQTT）

远程平台无法直接访问网关 HTTP（网关无公网 IP），需通过 MQTT Broker 下发指令。

**调用方式：** 向以下 topic 发布 JSON 消息：

```
Topic:  /247/D1V5L10MVFH1/function/get
```

**消息格式：**

```json
[
  {"id": "moveAction",   "value": "1"},
  {"id": "moveDuration", "value": "3"}
]
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `moveAction` | string(1-6) | 是 | 动作码，见下表 |
| `moveDuration` | string(秒) | 否 | 运动时长（秒），默认 0.5 |

> **速度由网关固定**（`DEFAULT_SPEED = 0.10`），远端不可修改。防止远程误操作导致速度失控。

**动作码：**

| 码 | 动作 | 网关执行 |
|----|------|----------|
| 0 | 停止 | 不调用（脉冲自然结束即停） |
| 1 | 前进 | `POST /api/forward?duration=N` |
| 2 | 后退 | `POST /api/backward?duration=N` |
| 3 | 左移 | 暂不支持 |
| 4 | 右移 | 暂不支持 |
| 5 | 左转 | `POST /api/turn-left?duration=N` |
| 6 | 右转 | `POST /api/turn-right?duration=N` |

**MQTT 发布示例（Python）：**

```python
import json
import paho.mqtt.client as mqtt

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "cloud-platform-001")
client.username_pw_set("mechanicalDog", "U6IsxS0Erz+!o-.y1CNZUOv?")
client.connect("106.52.191.198", 1883)

# 让机器狗前进 3 秒（速度由网关固定，远端无需传速度）
cmd = [
    {"id": "moveAction",   "value": "1"},
    {"id": "moveDuration", "value": "3"},
]
client.publish("/247/D1V5L10MVFH1/function/get", json.dumps(cmd))
```

**MQTT 发布示例（JavaScript / Node.js）：**

```js
const mqtt = require("mqtt");
const client = mqtt.connect("mqtt://106.52.191.198:1883", {
  clientId: "cloud-platform-001",
  username: "mechanicalDog",
  password: "U6IsxS0Erz+!o-.y1CNZUOv?",
});

// 让机器狗左转 2 秒（速度由网关固定，远端无需传速度）
client.publish("/247/D1V5L10MVFH1/function/get", JSON.stringify([
  { id: "moveAction",   value: "5" },
  { id: "moveDuration", value: "2" },
]));
```

> **注意：** 网关启动时 MQTT 桥接自动连接 Broker 并订阅该 topic，云端只需 publish 即可，无需额外配置。

### 默认速度

速度默认为最大速度的 10%（`DEFAULT_SPEED = 0.10`），在 `app/robot_client.py` 中修改：

```python
robot = RobotClient(default_speed=0.10, pulse_duration=0.5)
```

## MQTT 桥接（技术细节）

网关启动时自动连接公网 MQTT Broker (`106.52.191.198:1883`)，订阅云端指令 topic:

```
/247/D1V5L10MVFH1/function/get
```

云端指令格式及调用示例见上方 **场景二**。

### 桥接数据流

```
云端平台 ──MQTT publish──→ Broker ──MQTT──→ MqttBridge ──HTTP POST──→ FastAPI ──UDP──→ 机器狗
```

桥接模块 `mqtt_bridge.py` 负责解析 `moveAction`/`moveDuration` 字段，翻译为本地 HTTP 调用，调用方无需关心内网实现。

### 控制模型

**无状态脉冲式**：每次 API 调用发一段脉冲，结束后自动归零。前端按住按钮时每 300ms 重复调用，松开即停。云端下发指令通过 `moveDuration` 控制运动时长。

任何一端故障（浏览器崩、网络断、MQTT断连、服务挂）都不会导致机器狗失控——脉冲结束后自动停。
