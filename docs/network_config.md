# 山猫M20 机器狗控制环境配置

## 网络配置

- **机器狗 IP**: `10.21.31.103`
- **网关 PC IP**: `10.21.31.202`
- **网络接口**: `enpls0`
- **网段**: `10.21.31.x/24`

## 通信协议

### UDP 控制
- **目标地址**: `10.21.31.103:30000`
- **协议**: 自定义 UDP 协议（16字节头部 + JSON 载荷）
- **控制频率**: 20Hz 脉冲式

### RTSP 视频流
- **地址**: `rtsp://10.21.31.103:8554/video1`
- **视频格式**: MJPEG
- **默认分辨率**: 640x480

### MQTT 远程控制
- **测试环境 Broker**: `1.12.248.179:1883`
- **生产环境 Broker**: `106.52.191.198:1883`
- **用户名**: `mechanicalDog`
- **密码**: `U6IsxS0Erz+!o-.y1CNZUOv?`
- **订阅主题**: `/247/D1V5L10MVFH1/function/get`

## 本地控制设置

### 1. 环境准备
```bash
cd /Users/LEELUKA/PyProj/SchoolProj/archive
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. 启动服务
```bash
# 使用测试环境配置
source .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. 控制接口
- **Web 面板**: `http://10.21.31.202:8000`
- **前进**: `POST /api/forward?duration={seconds}`
- **后退**: `POST /api/backward?duration={seconds}`
- **左转**: `POST /api/turn-left?duration={seconds}`
- **右转**: `POST /api/turn-right?duration={seconds}`

## 故障排除

### 网络连通性检查
```bash
# 检查机器狗连通性
ping 10.21.31.103

# 检查网络接口配置
ifconfig enpls0
ip addr show
```

### 服务状态检查
- 确认网关 PC IP 为 `10.21.31.202`
- 确认机器狗 IP `10.21.31.103` 可达
- 确认 UDP 端口 30000 和 RTSP 端口 8554 可访问