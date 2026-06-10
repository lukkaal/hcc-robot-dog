# 4G/5G 公网视频推流方案

## 方案概述

```
 工地局域网 (10.21.31.x)                          4G/5G 基站                公网
 ┌──────────┐   RTSP    ┌──────────────────┐   无线    ═══════════    ┌──────────────┐
 │ 山猫M20  │ ────────→ │    网关 PC        │ ──────→               │  云直播平台   │
 │ 机器狗   │  :8554    │                  │  ffmpeg                │ (阿里云/腾讯) │
 └──────────┘           │ ┌──────┐ ┌─────┐ │  RTMP推流              │              │
                        │ │RTSP  │ │4G/5G│ │                       │ HLS/FLV播放   │
                        │ │拉流  │ │上网卡│ │                       │       ↓       │
                        │ └──────┘ └─────┘ │                       │  远程浏览器    │
                        └──────────────────┘                       └──────────────┘
```

网关 PC 加装 4G/5G USB 上网卡，通过蜂窝网络直接把视频推到云直播平台。
工地现场无需有线宽带，插电插卡就能用。

## 一、硬件采购

### 方案 A：4G USB 上网卡（推荐，成本低）

| 型号 | 价格 | 速率 | 接口 |
|------|------|------|------|
| 华为 E8372h-155 | ~200元 | 下行150M/上行50M | USB-A |
| 中兴 MF79U | ~180元 | 下行150M/上行50M | USB-A |
| 迅优 E325 | ~150元 | 下行150M/上行50M | USB-A |

> 上行 50Mbps 推一路 1080p 视频（需约 2-5Mbps）绰绰有余。

### 方案 B：5G CPE（延迟更低，适合高清）

| 型号 | 价格 | 速率 |
|------|------|------|
| 华为 5G CPE Pro | ~1500元 | 下行1.6G/上行300M |
| 中兴 MC8020 | ~1200元 | 下行1.5G/上行200M |

> 5G 延迟更低（端到端 <1s），但成本显著上升。工地下行推一路视频，4G 够用。

### 必备配件

- **物联网卡 / 流量卡** — 工地通常没有宽带，办一张大流量 4G 卡（月租 30-50 元，100-300GB）
  - 推荐联通/电信，工地覆盖通常比移动好
  - 注意选上行不限速的套餐（部分物联网卡会限上行）
- **USB 延长线（公对母）** — 把上网卡放到窗外/高处，信号更好（1-3 米即可，~10元）
- **防水胶带/电工胶带** — 户外固定上网卡用

## 二、云直播平台配置

以阿里云直播为例（腾讯云直播流程几乎一样）：

### 1. 开通服务

```bash
# 控制台
阿里云控制台 → 视频直播 → 开通服务
```

### 2. 添加推流域名和播流域名

```
推流域名: push.your-company.com   （网关 → 云平台）
播流域名: play.your-company.com   （云平台 → 远端浏览器）
```

> 两个域名都需要在 DNS 服务商处添加 CNAME 解析到阿里云分配的地址。
> 如果没有自己的域名，也可以用阿里云提供的测试域名（有播放次数和并发限制，仅用于开发测试）。

### 3. 获取推流地址

在控制台生成推流地址，格式如下：

```
rtmp://push.your-company.com/live/robot-dog-001?auth_key=xxxxx
```

`live` 是应用名（AppName），`robot-dog-001` 是流名（StreamName），后面是鉴权参数。

### 4. 生成播放地址

推流成功后，播放地址为：

```bash
# HLS（浏览器直接播）
http://play.your-company.com/live/robot-dog-001.m3u8

# FLV（更低延迟）
http://play.your-company.com/live/robot-dog-001.flv

# RTMP（VLC/播放器）
rtmp://play.your-company.com/live/robot-dog-001
```

### 5. 工地远端播放页面

远端浏览器打开以下 HTML 即可：

```html
<!-- DPlayer 播放器（HLS，延迟 3-5s） -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/dplayer/dist/DPlayer.min.css">
<script src="https://cdn.jsdelivr.net/npm/hls.js/dist/hls.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dplayer/dist/DPlayer.min.js"></script>
<div id="player"></div>
<script>
new DPlayer({
  container: document.getElementById("player"),
  video: { url: "http://play.your-company.com/live/robot-dog-001.m3u8" },
});
</script>
```

## 三、网关 PC 安装依赖

### 1. 4G 上网卡驱动

大多数 USB 上网卡插上后 Linux 自动识别为网卡（RNDIS/ECM 模式），无需额外驱动。

```bash
# 插入上网卡后，查看是否识别
ip addr show

# 通常会多出一个 usb0 或 eth1 接口
# 热门型号华为 E8372 还需要执行一次模式切换（仅首次）：
# usb_modeswitch -v 12d1 -p 1f01 -W -M "55534243123456780000000000000011062000000101000100000000000000"
```

### 2. 配置 4G 网卡优先级（关键）

正常情况下，有线网卡（eth0）走局域网（10.21.31.x），上网卡（usb0）走公网。
需要配置策略路由，让 RTMP 推流走上网卡：

```bash
# 假设 usb0 为上网卡，网关为 192.168.8.1（华为设备默认）
# 添加路由规则：去往云推流服务器的流量走 usb0
sudo ip route add <RTMP服务器IP> via 192.168.8.1 dev usb0
```

### 3. 安装 ffmpeg

```bash
# Ubuntu / Debian
sudo apt install ffmpeg -y

# CentOS / Rocky
sudo yum install epel-release -y
sudo yum install ffmpeg -y

# macOS（开发测试）
brew install ffmpeg

# 验证
ffmpeg -version
```

## 四、推流命令

### 基础推流（不转码，CPU 零开销）

```bash
ffmpeg -i rtsp://10.21.31.103:8554/video1 \
  -c copy -f flv \
  rtmp://push.your-company.com/live/robot-dog-001
```

### 降码率推流（省流量，推荐 4G 场景）

```bash
ffmpeg -i rtsp://10.21.31.103:8554/video1 \
  -c:v libx264 -b:v 1500k -maxrate 2000k -bufsize 3000k \
  -preset ultrafast -tune zerolatency \
  -c:a aac -b:a 64k \
  -f flv \
  rtmp://push.your-company.com/live/robot-dog-001
```

| 参数 | 含义 | 4G 推荐值 |
|------|------|-----------|
| `-b:v` | 视频码率 | 1500k（720p 够用） |
| `-maxrate` | 最大码率 | 2000k |
| `-preset ultrafast` | 编码速度优先 | 必选，降低 CPU 负载 |
| `-tune zerolatency` | 低延迟调优 | 必选 |

## 五、Python 集成

参见 `app/video_streamer.py`，封装了上述 ffmpeg 命令的进程管理、自动重连、和断流检测。

启动后：
- FastAPI 在 `lifespan` 中自动拉起推流进程
- ffmpeg 崩溃/断连后自动重试
- 视频流仍通过 `/api/video` 在局域网内提供 MJPEG（现场操作员不受影响）

## 六、测试验证

```bash
# 1. 确认 4G 上网卡连通公网
curl -4 ifconfig.me
# 应返回公网 IP（不是 10.x.x.x）

# 2. 测试推流
ffmpeg -i rtsp://10.21.31.103:8554/video1 -c copy -f flv <推流地址>
# 应看到 "speed=1x" 且无 "Connection refused"

# 3. 用 VLC 打开播放地址验证画面
vlc rtmp://play.your-company.com/live/robot-dog-001

# 4. 浏览器打开 DPlayer 页面验证 HLS 播放
```

## 七、费用估算

| 项目 | 费用 |
|------|------|
| 4G USB 上网卡 | 一次性 ~200元 |
| 物联网流量卡 | 月租 ~30-50元（100-300GB） |
| 云直播下行流量 | 按 2Mbps × 8小时/天 × 30天 ≈ 210GB/月，约 ¥100/月 |
| **合计** | 硬件 200 + 月费 ~150/月 |

> 云直播计费 = 下行流量费（约 0.5元/GB） + 转码费（用 `-c copy` 则无转码费）。
> 只有一个远端工地看的话，走 FLV 直拉，流量可控。
