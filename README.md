# 山猫M20 遥控网关

基于 FastAPI 的机器狗 Web 遥控面板，支持前后移动、左右转向及实时视频监控。同时内置智慧工地数据网关，打通云端平台到机器狗的远程控制与数据上报链路。

## 项目结构

```
.
├── app/                    # Web 遥控网关
│   ├── main.py             # FastAPI 入口，生命周期管理
│   ├── robot_client.py     # 机器狗 UDP 控制协议封装
│   ├── mqtt_bridge.py      # MQTT 桥接：云端指令 → 本地 HTTP
│   ├── static/
│   │   └── index.html      # Web 遥控面板
│   └── requirements.txt
├── smart_system.../        # 智慧工地数据网关
│   ├── main.py             # 数据网关入口
│   ├── config.py           # 配置文件（机器狗IP、MQTT参数等）
│   ├── cloud/              # MQTT 云端通信模块
│   ├── core/               # 数据处理模块
│   └── robot/              # 机器狗连接与协议模块
├── test_control.py         # 机器狗运动控制测试脚本
├── test_video.py           # 视频流测试脚本
├── docs/                   # 文档
└── requirements.txt        # 根目录依赖
```

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 Web 遥控网关

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后浏览器打开 `http://localhost:8000` 即可使用 Web 遥控面板。

### 3. 启动智慧工地数据网关

修改 `smart_system.../config.py` 中的机器狗 IP 和 MQTT 参数，然后运行：

```bash
python smart_system.../main.py
```

### 4. 测试机器狗运动控制

确保机器狗已开机并处于常规模式+站立状态，然后：

```bash
python test_control.py
```

## API 手册

基址: `http://<网关IP>:8000`

| 端点 | 方法 | 参数 | 说明 |
|---|---|---|---|
| `/api/forward` | POST | `duration` (float, 可选, 默认0.5) | 前进 |
| `/api/backward` | POST | `duration` (float, 可选, 默认0.5) | 后退 |
| `/api/turn-left` | POST | `duration` (float, 可选, 默认0.5) | 左转 |
| `/api/turn-right` | POST | `duration` (float, 可选, 默认0.5) | 右转 |
| `/api/video` | GET | — | MJPEG 视频流 |

### 调用示例

```bash
# 前进 1 秒
curl -X POST "http://localhost:8000/api/forward?duration=1.0"

# 左转 2 秒
curl -X POST "http://localhost:8000/api/turn-left?duration=2.0"

# 后退（默认 0.5 秒）
curl -X POST "http://localhost:8000/api/backward"
```

## 控制模型

**无状态脉冲式**：每次 API 调用发一段脉冲，结束后自动归零。前端按住按钮时每 300ms 重复调用，松开即停。任何一端故障（网络断、服务挂）都不会导致机器狗失控——脉冲结束后自动停止。
