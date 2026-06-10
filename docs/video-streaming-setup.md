# 4G + VPS 自建视频推流方案（无云平台依赖）

## 方案概述

```
 工地局域网 (10.21.31.x)                    4G基站         公网
┌──────────┐  RTSP   ┌──────────────────┐  无线    ═══════   ┌──────────────┐
│ 山猫M20  │ ──────→ │    网关 PC        │ ──────→          │    VPS       │
│ 机器狗   │  :8554  │                  │ ffmpeg            │ (公网IP)     │
└──────────┘         │ ┌──────┐ ┌─────┐ │ RTMP推流          │              │
                     │ │RTSP  │ │4G   │ │                   │ mediamtx     │
                     │ │拉流  │ │上网 │ │                   │ :1935 RTMP收 │
                     │ └──────┘ │卡   │ │                   │ :8889 WebRTC │
                     │          └─────┘ │                   │ :8888 HLS    │
                     └──────────────────┘                   └──┬──┬──┬─────┘
                                                             │  │  │
                                                    WebRTC  │  │HLS│
                                                    远端浏览器  │  │  │
                                                    <1s延迟   │  │  │
                                                            ┌─┘  │  └─┐
                                                       (手机) (PC) (平板)
```

**三条链路互不干扰：**

| 链路 | 路径 | 说明 |
|------|------|------|
| 本地控制 | 浏览器 → FastAPI :8000 → UDP → 狗 | 现场操作员 |
| 远程控制 | 云平台 → MQTT → 桥接 → HTTP → UDP → 狗 | 远程控制 |
| 视频推流 | 狗 RTSP → ffmpeg → VPS mediamtx → 浏览器 | 远程观看 |

> ffmpeg 推流由 systemd 管理，不经过 Python 代码，与 FastAPI 完全解耦。

## 一、硬件采购

### 4G USB 上网卡（推荐）

| 型号 | 价格 | 速率 | 接口 |
|------|------|------|------|
| 华为 E8372h-155 | ~200元 | 下行150M/上行50M | USB-A |
| 中兴 MF79U | ~180元 | 下行150M/上行50M | USB-A |
| 迅优 E325 | ~150元 | 下行150M/上行50M | USB-A |

> 上行 50Mbps 推一路 720p 视频（需约 1.5-2Mbps）绰绰有余。

### VPS

| 服务商 | 配置 | 价格 |
|--------|------|------|
| 阿里云轻量应用服务器 | 1核1G、3Mbps、Linux | ~34元/月 |
| 腾讯云轻量应用服务器 | 1核1G、3Mbps、Linux | ~28元/月 |

> VPS 带宽 3Mbps 够 1-2 人同时看。如需多人并发，可升配带宽。

### 配件

- **物联网卡 / 流量卡** — 联通或电信，100GB+/月，月租 30-50 元。注意选上行不限速的套餐。
- **USB 延长线（公对母）** — 3 米，把上网卡放到窗外/高处，~10 元。
- **防水胶带** — 户外固定上网卡用。

## 二、VPS 部署 mediamtx（30 分钟）

mediamtx 是开源 RTSP/RTMP/WebRTC 网关，一个二进制文件即可运行，无需 Docker、无需数据库。

### 2.1 购买 VPS

阿里云轻量或腾讯云轻量，选 Ubuntu 22.04 / Debian 12，得到公网 IP（如 `123.45.67.89`）。

### 2.2 安装

```bash
ssh root@<VPS公网IP>

mkdir -p /opt/mediamtx && cd /opt/mediamtx
wget https://github.com/bluenviron/mediamtx/releases/download/v1.11.3/mediamtx_v1.11.3_linux_amd64.tar.gz
tar xzf mediamtx_v1.11.3_linux_amd64.tar.gz
```

### 2.3 配置

编辑 `mediamtx.yml`：

```yaml
# RTMP 接收端口（网关 ffmpeg 推流到此）
rtmpAddress: :1935

# HLS 播放端口（远端浏览器）
hlsAddress: :8888

# WebRTC 播放端口
webrtcAddress: :8889

# 流路径配置
paths:
  robot-dog:
    source: rtmpServer
```

> 完整默认配置模板在 `mediamtx.yml` 中，上述只列出需要修改的字段。

### 2.4 防火墙

```bash
# 云服务商控制台安全组 + 系统防火墙都需要放行
ufw allow 1935/tcp   # RTMP 推流
ufw allow 8888/tcp   # HLS 播放
ufw allow 8889/tcp   # WebRTC 播放
ufw allow 22/tcp     # SSH（已有则跳过）
ufw enable
```

### 2.5 配置 systemd 守护

```bash
cat > /etc/systemd/system/mediamtx.service << 'EOF'
[Unit]
Description=mediamtx
After=network.target

[Service]
ExecStart=/opt/mediamtx/mediamtx /opt/mediamtx/mediamtx.yml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mediamtx
systemctl status mediamtx
```

## 三、网关 PC 配置（30 分钟）

### 3.1 插入 4G 上网卡

```bash
# 插入 USB 后查看是否识别
ip addr show
# 应出现 usb0 或 eth1 接口
```

华为 E8372 默认网关为 `192.168.8.1`。大部分上网卡即插即用（RNDIS/ECM 模式），无需驱动。

### 3.2 配置双网卡路由（关键）

网关 PC 有两张网卡：
- `eth0` — 局域网 10.21.31.x（与机器狗通信，**不能动**）
- `usb0` — 4G 上网卡（连公网）

不能让默认路由走 usb0（会切断局域网通信），需要用策略路由让**仅 RTMP 流量**走 usb0：

```bash
# 临时生效（立即测试用）
sudo ip route add <VPS公网IP> via 192.168.8.1 dev usb0

# 持久化 — 创建 systemd-networkd 配置
cat > /etc/systemd/network/10-usb0-route.network << EOF
[Match]
Name=usb0

[Route]
Destination=<VPS公网IP>/32
Gateway=192.168.8.1
EOF

systemctl restart systemd-networkd
```

> 其他设备的 4G 上网卡网关可能不同（常见 192.168.0.1 / 192.168.1.1），插上后 `ip route show dev usb0` 查看。

### 3.3 安装 ffmpeg

```bash
sudo apt install ffmpeg -y
ffmpeg -version
```

### 3.4 验证 RTSP 拉流

```bash
# 确认本机能从机器狗拉到画面
ffplay rtsp://10.21.31.103:8554/video1
# 有画面 → ctrl+c 退出
```

### 3.5 验证推流到 VPS

```bash
ffmpeg -rtsp_transport tcp \
  -i rtsp://10.21.31.103:8554/video1 \
  -c:v libx264 -b:v 1500k -maxrate 2000k -bufsize 3000k \
  -preset ultrafast -tune zerolatency \
  -c:a aac -b:a 64k -ar 44100 -ac 1 \
  -f flv \
  rtmp://<VPS公网IP>:1935/robot-dog

# 终端持续输出 "speed=1x" 且无 Connection refused → 推流成功
```

## 四、远端播放页面（20 分钟）

VPS 上安装 nginx 托管一个静态 HTML 页面。

```bash
ssh root@<VPS公网IP>
apt install nginx -y
```

创建 `/var/www/html/dog-video.html`：

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>机器狗实时视频</title>
  <style>
    body { margin: 0; background: #000; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
    video { max-width: 100%; max-height: 100vh; }
  </style>
</head>
<body>
  <video id="video" controls autoplay muted></video>

  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <script>
  const video = document.getElementById("video");
  const VPS_IP = window.location.hostname;       // 自动取当前页面 IP
  const hlsUrl = `http://${VPS_IP}:8888/robot-dog/`;
  if (Hls.isSupported()) {
    const hls = new Hls({ liveSyncDurationCount: 1 });
    hls.loadSource(hlsUrl);
    hls.attachMedia(video);
  } else {
    video.src = hlsUrl;       // Safari 原生支持 HLS
  }
  </script>
</body>
</html>
```

远端访问：`http://<VPS公网IP>/dog-video.html`

## 五、ffmpeg 推流守护（30 分钟）

网关 PC 上创建 systemd service，确保推流进程开机自启、崩溃自动重启。

```bash
cat > /etc/systemd/system/dog-video-push.service << 'EOF'
[Unit]
Description=机器人视频推流 (RTSP → RTMP)
After=network.target

[Service]
ExecStart=/usr/bin/ffmpeg \
  -rtsp_transport tcp \
  -i rtsp://10.21.31.103:8554/video1 \
  -c:v libx264 -b:v 1500k -maxrate 2000k -bufsize 3000k \
  -preset ultrafast -tune zerolatency \
  -c:a aac -b:a 64k -ar 44100 -ac 1 \
  -f flv \
  rtmp://<VPS公网IP>:1935/robot-dog
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now dog-video-push
systemctl status dog-video-push
```

常用操作：

```bash
journalctl -u dog-video-push -f        # 实时日志
systemctl restart dog-video-push       # 手动重启
systemctl stop dog-video-push          # 停止推流
```

### 转码参数说明

| 参数 | 含义 | 4G 推荐值 |
|------|------|-----------|
| `-b:v` | 视频码率 | 1500k（720p） |
| `-maxrate` | 峰值码率上限 | 2000k |
| `-bufsize` | 编码缓冲区 | 3000k |
| `-preset ultrafast` | 编码速度优先 | 必选，降低 CPU |
| `-tune zerolatency` | 低延迟调优 | 必选 |

> 码率占 4G 上行带宽约 2Mbps，按每天推流 8 小时计算，月流量约 210GB。

## 六、联调测试

| 序号 | 测试项 | 操作 | 预期结果 |
|------|--------|------|----------|
| 1 | RTSP 本地 | 网关 PC 执行 `ffplay rtsp://10.21.31.103:8554/video1` | 有画面 |
| 2 | 4G 公网 | `curl -4 ifconfig.me` | 返回公网 IP |
| 3 | VPS mediamtx 运行 | `systemctl status mediamtx` | active |
| 4 | RTMP 推流 | `systemctl status dog-video-push` | active，日志有 speed=1x |
| 5 | HLS 远端播放 | 手机切 4G 网络，打开 `http://<VPS-IP>/dog-video.html` | 有画面，延迟 3-5s |
| 6 | 控制链路 | 浏览器打开 Web 面板，按按钮 | 机器狗正常运动 |
| 7 | 断网恢复 | 拔掉 4G 上网卡 10 秒再插回 | dog-video-push 自动恢复 |

### 排障

```bash
# 推流失败 — 检查 VPS 端口是否可达
nc -zv <VPS公网IP> 1935

# 推流成功但远端看不到 — 检查 mediamtx 日志
journalctl -u mediamtx -f

# 视频卡顿 — 降低码率 -b:v 1000k，或检查 4G 信号强度
```

## 七、费用

| 项目 | 一次性 | 月费 |
|------|--------|------|
| 4G USB 上网卡 | ~200元 | — |
| 物联网流量卡 | — | ~30-50元 |
| VPS（1核1G 3M） | — | ~30-50元 |
| **合计** | ~200元 | ~60-100元/月 |

## 八、与 Python 代码的关系

**不改任何 Python 代码。** ffmpeg 推流由 systemd 独立管理，与 FastAPI 进程完全分离：

- FastAPI 停掉不影响视频推流
- 视频推流崩溃不影响机器人控制
- systemd 自带崩溃重启，比手写 subprocess 管理更可靠
- 两套日志独立（FastAPI 日志 vs `journalctl -u dog-video-push`）
