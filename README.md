# 山猫M20 遥控网关

基于 FastAPI 的机器狗 Web 遥控面板 + GB/T 28181 视频推流网关。支持本地遥控、云端 MQTT 远程控制、以及向国标视频主站推送摄像头实时画面。

## 系统架构

```
                              公网                              局域网
  ┌──────────┐    MQTT      ┌──────────────────────────────────┐   UDP:30000   ┌──────────┐
  │ 智慧工地  │ ←──────────→ │           网关 PC                │ ─────────────→ │ 山猫M20  │
  │ 云平台    │   :1883      │                                  │               │ 机器狗   │
  └──────────┘              │  MQTT桥接 → FastAPI :8000         │ ←─RTSP:8554── │          │
                            │               控制API ×4          │               └──────────┘
  ┌──────────┐   HTTP       │               视频流MJPEG         │
  │ 现场操作员│ ←──────────→ │               诊断API             │
  │ 手机/平板 │   :8000      │                                  │
  │ (浏览器)  │             │  GB28181客户端 → SIP信令(UDP)     │
  └──────────┘              │        ↓                          │
                            │  ZLMediaKit(Docker) → RTP推流     │
  ┌──────────┐   SIP+PS/RTP │                                  │
  │ 视频主站  │ ←──────────→ └──────────────────────────────────┘
  │(GB28181) │
  └──────────┘
```

**三条链路：**
1. **本地遥控** — 浏览器 HTTP :8000 → UDP → 机器狗
2. **云端远程** — 云平台 → MQTT → 桥接 → HTTP :8000 → UDP → 机器狗
3. **视频上墙** — 摄像头 RTSP → ZLMediaKit 拉流 → 主站 INVITE 点播 → RTP 推流到平台

## 快速启动

### 环境准备

```bash
# Python 3.10+
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Docker（ZLMediaKit 视频推流容器）
docker pull zlmediakit/zlmediakit:master
```

### 配置

```bash
cp .env.example .env
# 编辑 .env 填入实际配置
```

### 启动

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后浏览器打开 `http://localhost:8000` 访问遥控面板。

### 全链路诊断

```bash
uv run python tests/diag.py          # 检测全链路状态
uv run python tests/diag.py --kill   # 清理端口占用 + 检测
```

## 环境变量

以下变量必须在 `.env` 中配置：

| 变量 | 必填 | 说明 |
|------|------|------|
| `ROBOT_RTSP_URL` | 是 | 机器狗摄像头 RTSP 地址 |
| `MQTT_BROKER` | 是 | MQTT Broker 地址 |
| `MQTT_PORT` | 否 | MQTT 端口，默认 1883 |
| `MQTT_CLIENT_ID` | 是 | MQTT Client ID |
| `MQTT_USER` | 是 | MQTT 用户名 |
| `MQTT_PW` | 是 | MQTT 密码 |
| `MQTT_SUB_TOPIC` | 是 | MQTT 订阅指令 topic |
| `GB28181_SIP_SERVER_HOST` | 是 | 视频主站 SIP 服务器 IP |
| `GB28181_SIP_SERVER_PORT` | 是 | 视频主站 SIP 端口 |
| `GB28181_SIP_SERVER_ID` | 是 | 视频主站 SIP 服务器 ID (20位) |
| `GB28181_SIP_DOMAIN` | 是 | 视频主站 SIP 域 (10位) |
| `GB28181_SIP_USERNAME` | 是 | 本设备 ID (20位) |
| `GB28181_SIP_AUTH_ID` | 是 | SIP 认证 ID |
| `GB28181_SIP_PASSWORD` | 是 | SIP 认证密码 |
| `GB28181_CHANNEL_ID` | 是 | 视频通道 ID (20位) |
| `GB28181_LOCAL_SIP_IP` | 是 | 本机局域网 IP |
| `GB28181_LOCAL_SIP_PORT` | 否 | 本机 SIP 端口，默认 15060 |
| `ZLM_SECRET` | 是 | ZLMediaKit API 密钥，需与 docker/zlm-config/config.ini 一致 |
| `GB28181_DEBUG` | 否 | 设为 1 打印原始 SIP 报文 |
| `ROBOT_IP` | 否 | 机器狗控制 IP，默认 10.21.31.103 |

## 项目结构

```
├── app/
│   ├── main.py              # FastAPI 入口，生命周期管理
│   ├── robot_client.py      # 机器狗 UDP 控制协议
│   ├── mqtt_bridge.py       # MQTT → HTTP 指令桥接
│   ├── gb28181_client.py    # GB/T 28181 SIP 信令客户端（自研，替代 WVP-PRO）
│   ├── docker_manager.py    # ZLMediaKit Docker 容器管理
│   └── static/
│       └── index.html       # Web 遥控面板
├── smart_system/            # 智慧工地平台数据交互模块
│   ├── cloud/               # MQTT 云端通信
│   ├── robot/               # 机器狗连接/协议
│   └── core/                # 数据处理
├── docker/
│   ├── docker-compose.yml   # 参考用（WVP+Redis+ZLM，生产环境仅需 ZLM）
│   ├── zlm-config/
│   │   └── config.ini       # ZLMediaKit 配置文件
│   └── wvp-config/          # WVP-PRO 配置（参考，已不再使用）
├── tests/
│   ├── diag.py              # 全链路诊断脚本
│   ├── test_gb28181.py      # GB28181 UDP 注册测试
│   ├── test_gb28181_tcp.py  # GB28181 TCP 注册测试
│   ├── test_mqtt_conn.py    # MQTT 连接测试
│   ├── test_comprehensive.py# MQTT 综合连接测试
│   └── send_cmd.py          # MQTT 指令发送工具
├── docs/                    # 设计文档 & 对接需求
├── scripts/                 # Docker 镜像拉取等辅助脚本
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── CLAUDE.md                # Claude Code 项目指引
└── README.md
```

## API 参考

基址: `http://<网关IP>:8000`

### 控制

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/forward` | POST | `duration` (float, 可选, 默认0.5) | 前进 |
| `/api/backward` | POST | `duration` (float, 可选, 默认0.5) | 后退 |
| `/api/turn-left` | POST | `duration` (float, 可选, 默认0.5) | 左转 |
| `/api/turn-right` | POST | `duration` (float, 可选, 默认0.5) | 右转 |

### 视频 & 诊断

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/video` | GET | MJPEG 视频流 |
| `/api/status` | GET | 网关状态（SIP注册、MQTT连接、推流） |

### 调用示例

```bash
curl -X POST "http://localhost:8000/api/forward?duration=1.0"
curl -X POST "http://localhost:8000/api/turn-left?duration=0.5"
curl "http://localhost:8000/api/status"
```

## GB28181 视频推流

### 工作流程

1. **启动** → SIP 向主站注册（MD5 Digest 认证）
2. **心跳** → 每 60s 发 REGISTER 保活，连续 3 次失败自动重注册
3. **目录同步** → 收到 Catalog 查询 → 回复设备/通道信息（MANSCDP XML）
4. **点播** → 收到 INVITE → 回 200 OK → 调 ZLM API 推 RTP 到平台指定端口
5. **停止** → 收到 BYE → 停推流

### 数据流

```
摄像头(HEVC) → RTSP → ZLMediaKit(proxy/robot-dog)
                            ↓
                    主站 INVITE 点播
                            ↓
                    RTP(PS over TCP) → 平台媒体服务器
```

### 维护要点

- **ZLM 容器挂了** → `docker restart dog-zlmediakit`，uvicorn 重启时自动恢复
- **SIP 注册失败** → 查 `tests/diag.py` 第5步网络可达性，确认主站 IP/端口
- **推流 0 bytes** → 查 ZLM 日志 `docker logs dog-zlmediakit --tail 50`，确认 INVITE 时序
- **平台报 32603** → 确认摄像头编码格式（HEVC/H.265 vs H.264），必要时加 FFmpeg 转码
- **心跳掉线** → 代码自动重注册，查 `/api/status` 确认 `heartbeat_fail_count`

### 关键文件

| 文件 | 作用 |
|------|------|
| `app/gb28181_client.py` | SIP 信令核心（注册、心跳、INVITE/BYE、MESSAGE） |
| `app/docker_manager.py` | ZLM 容器启停、RTSP 拉流代理 |
| `docker/zlm-config/config.ini` | ZLM API 密钥、端口配置 |

## 安全注意事项

1. `.env` 包含所有密码和密钥，**已从 git 中移除**，严禁提交到仓库
2. `.env.example` 是配置模板，不包含真实凭证
3. `docker/zlm-config/config.ini` 中的 `secret` 需与 `.env` 的 `ZLM_SECRET` 保持一致
4. Web 面板开启了 CORS `*`，仅适用于内网部署
