# ZLMediaKit 国标推流配置指南

## 目标

把机器狗的 RTSP 视频接入视频主站，让主站按 GB/T 28181 点播机器狗画面。

```text
机器狗 RTSP → 网关 PC → WVP-PRO(SIP/GB28181) + ZLMediaKit(媒体转发) → 视频主站 → 远端播放
```

## 结论先行

推荐使用 **WVP-PRO + ZLMediaKit**。

- WVP-PRO 负责 GB/T 28181 信令：SIP 注册、认证、目录/通道、INVITE、SDP、BYE。
- ZLMediaKit 负责媒体能力：拉取机器狗 RTSP，把媒体按 RTP/PS 发给视频主站。
- 不建议只用 ZLMediaKit 独立接主站。ZLM 的 HTTP API 可以发 RTP，但不负责完整 SIP/GB28181 流程，单靠它无法完成主站注册和点播协商。

## 方案选择

| 方案 | 是否推荐 | 说明 |
|------|----------|------|
| WVP-PRO + ZLMediaKit | 推荐 | 最稳妥。WVP 做国标信令，ZLM 做媒体转发 |
| ZLMediaKit + 自写 SIP | 不推荐 | 理论可行，但要自己处理注册、鉴权、INVITE、SDP、SSRC、BYE 等细节 |
| 直接 RTMP/FLV/HLS 推主站 | 仅在主站支持时使用 | 如果主站明确支持 RTMP 直推，比 GB28181 简单很多 |
| 仅 ZLMediaKit 独立模式 | 不可作为完整方案 | 缺少 SIP 注册和国标点播协商 |

## 一、前置条件

### 1.1 向视频主站申请接入设备

调用视频主站 `/devMgr/deviceApply` 接口，为网关/WVP 申请一个要接入主站的设备编码。

如果网关作为一台 NVR 或下级平台接入，可先按 `deviceType=118` 申请；如果主站要求按单 IPC 接入，则改成 `deviceType=132`。这个字段最好和主站运维确认。

```json
{
  "deviceType": "118",
  "regionCode": "440100",
  "deviceTag": "robot-dog",
  "deviceName": "山猫M20网关",
  "channelNum": 1,
  "latitude": "23.127191",
  "longitude": "113.355747",
  "remark": "机器狗前置摄像头"
}
```

返回结果里重点记录：

| 字段 | 用途 |
|------|------|
| `deviceId` | 调主站 HTTP API 时查询/删除设备可能会用到 |
| `deviceCode` | WVP 向主站 SIP 注册时使用的下级设备/平台编码 |
| `accessPassword` | WVP 向主站 SIP 注册认证使用的密码 |
| `channelList[0].channelId` | 调主站 `/stream/start` 开始直播时使用 |
| `channelList[0].channelCode` | GB28181 通道编码，不能直接假设等于 `deviceCode` |
| `channelList[0].channelScode` | 主站自定义通道代码，按需记录 |

> 注意：主站接口文档里的经纬度示例存在字段值反写的情况，实际填写时 `longitude` 应为经度，`latitude` 应为纬度。

### 1.2 向主站方确认参数

部署前向视频主站方确认这些信息：

| 参数 | 说明 |
|------|------|
| 主站 SIP IP/域名 | WVP 要注册到的主站地址 |
| 主站 SIP 端口 | 通常是 `5060/UDP`，以主站为准 |
| 主站平台 ID | GB28181 上级平台国标编码 |
| 主站 SIP 域 | 通常取平台 ID 前 10 位或主站指定值 |
| RTP 收流模式 | UDP、TCP active、TCP passive 哪一种 |
| RTP 端口范围 | 主站用于接收媒体的端口范围 |
| SSRC 规则 | 是否要求主站指定 SSRC，还是下级生成 |
| 视频编码要求 | H.264/H.265、分辨率、帧率、码率 |

### 1.3 确认网关网络

网关 PC 需要同时满足：

- 能拉到机器狗 RTSP：`rtsp://10.21.31.103:8554/video1`
- 能访问视频主站 SIP 地址和端口。
- 主站能访问网关用于 SIP/RTP 的对外 IP，或双方网络已打通。
- 防火墙放行 WVP/ZLM 所需端口。

建议先测试：

```bash
ping 10.21.31.103
ffplay rtsp://10.21.31.103:8554/video1

# 主站 SIP 端口按实际替换
nc -uvz <视频主站IP> 5060
```

## 二、推荐架构

```text
                     SIP REGISTER / INVITE / BYE
                 ┌────────────────────────────────→ 视频主站
                 │
机器狗 RTSP ─→ ZLMediaKit ← HTTP API/control ─ WVP-PRO
                 │
                 └──────────── RTP/PS ───────────→ 视频主站
```

职责边界：

- 机器狗只提供 RTSP。
- ZLMediaKit 负责把 RTSP 拉进来，并在主站点播时发送 RTP。
- WVP-PRO 负责伪装成国标下级设备/平台注册到视频主站。
- 远端播放不直接访问 ZLM，而是调用主站 `/stream/start` 后播放主站返回的 FLV/HLS/WS-FLV/RTMP 地址。

## 三、部署 ZLMediaKit

### 3.1 Docker 启动

Linux 网关建议用 host 网络，避免 SIP/RTP 端口映射问题。

```bash
mkdir -p /opt/zlmediakit

docker run -d \
  --name zlmediakit \
  --restart always \
  --network host \
  -v /opt/zlmediakit/config.ini:/opt/media/conf/config.ini \
  zlmediakit/zlmediakit:master
```

> 如果 `/opt/zlmediakit/config.ini` 不存在，先从容器默认配置拷贝一份再修改。不同 ZLMediaKit 版本的字段名可能略有差异，最终以实际镜像内 `config.ini` 为准。

### 3.2 关键配置

编辑 ZLM `config.ini`，至少确认这些配置：

```ini
[api]
secret=my_secret_key_2025
apiDebug=1

[http]
port=9092
allow_cross_domains=1

[rtsp]
port=8554

[rtp_proxy]
port_range=30000-30500
timeoutSec=15

[general]
mediaServerId=robot-dog-gw-001
```

重启并验证：

```bash
docker restart zlmediakit

curl "http://127.0.0.1:9092/index/api/getServerConfig?secret=my_secret_key_2025"
```

## 四、部署 WVP-PRO

### 4.1 docker-compose 示例

不同 WVP-PRO 镜像和版本的配置结构可能不同，下面只作为部署骨架。实际配置文件请以所选 WVP-PRO 版本文档为准。

```yaml
version: "3.7"

services:
  redis:
    image: redis:7-alpine
    network_mode: host
    restart: always

  zlmediakit:
    image: zlmediakit/zlmediakit:master
    network_mode: host
    restart: always
    volumes:
      - ./zlm-config.ini:/opt/media/conf/config.ini

  wvp:
    image: 108360/wvp-pro:latest
    network_mode: host
    restart: always
    depends_on:
      - redis
      - zlmediakit
    volumes:
      - ./wvp-config:/opt/wvp/config
```

### 4.2 WVP 关键配置思路

WVP 需要配置两类信息：

1. 本级 SIP 信息：WVP 在网关本机监听的 SIP 地址、端口、国标 ID、域。
2. 上级平台信息：视频主站的 SIP 地址、端口、平台 ID、域、注册密码。

示意如下，不要直接照抄成最终配置；不同版本字段名可能不同。

```yaml
# 本级平台/设备信息：WVP 对主站呈现出来的身份
sip:
  ip: <网关PC对主站可达的IP>
  port: 5060
  id: <deviceCode>
  domain: <本级SIP域，通常和deviceCode前10位或主站要求一致>
  password: <accessPassword>

# 上级平台：视频主站
upper-platform:
  enable: true
  server-ip: <视频主站IP>
  server-port: 5060
  server-id: <视频主站平台ID>
  server-domain: <视频主站SIP域>
  username: <deviceCode>
  password: <accessPassword>
  transport: UDP
  expires: 3600

# 媒体服务：ZLMediaKit
media:
  id: robot-dog-gw-001
  ip: 127.0.0.1
  http-port: 9092
  secret: my_secret_key_2025
  rtp-port-range: 30000,30500
```

必须避免 YAML 里出现两个同级 `sip:`。如果写成两个同级 `sip:`，后一个会覆盖前一个，导致配置丢失。

### 4.3 在 WVP 中添加机器狗通道

WVP 需要知道有一路视频通道对应机器狗 RTSP。

实践时有两种方式：

1. 如果 WVP 支持“拉流代理/通道管理”，在 WVP 后台添加一路 RTSP 拉流：
   - 名称：`山猫M20前置摄像头`
   - 应用：`proxy`
   - 流 ID：`robot-dog`
   - RTSP 地址：`rtsp://10.21.31.103:8554/video1`
   - 国标通道编码：填写主站返回的 `channelList[0].channelCode`

2. 如果 WVP 不直接管理这个 RTSP 源，可先用 ZLM `addStreamProxy` 把流拉进来，再在 WVP 中把该 ZLM 流映射成国标通道。

## 五、添加 RTSP 拉流代理

如果采用 ZLM API 拉流，可执行：

```bash
curl -X POST "http://127.0.0.1:9092/index/api/addStreamProxy" \
  -H "Content-Type: application/json" \
  -d '{
    "secret": "my_secret_key_2025",
    "vhost": "__defaultVhost__",
    "app": "proxy",
    "stream": "robot-dog",
    "url": "rtsp://10.21.31.103:8554/video1",
    "enable_rtsp": 1,
    "enable_rtmp": 1,
    "enable_hls": 0,
    "enable_mp4": 0,
    "add_mute_audio": 1,
    "retry_count": -1
  }'
```

验证 ZLM 已经拉到流：

```bash
curl "http://127.0.0.1:9092/index/api/getMediaList?secret=my_secret_key_2025"
ffplay rtsp://127.0.0.1:8554/proxy/robot-dog
```

说明：

- `add_mute_audio=1` 可以在源 RTSP 没有音频时补静音音轨，部分平台播放兼容性更好。
- `enable_hls` 和 `enable_mp4` 对国标上级推流不是必需，测试阶段可关闭以减少资源占用。
- 如果 WVP 后台已经负责拉流，就不要重复用 ZLM API 添加同名流。

## 六、GB28181 点播流程

主站点播时，整体流程应是：

```text
WVP → 主站：SIP REGISTER
主站 → WVP：200 OK

业务系统 → 主站 HTTP API：/stream/start(channelId)
主站 → WVP：SIP INVITE，SDP 中携带 RTP 地址、端口、SSRC、传输模式
WVP → 主站：200 OK
WVP/ZLM → 主站：RTP/PS 媒体流
业务系统/浏览器：播放主站返回的 FLV/HLS/WS-FLV/RTMP 地址
```

主站 `/stream/start` 需要传 `channelId`，不是 `channelCode`：

```json
{
  "channelId": "<channelList[0].channelId>"
}
```

主站返回的播放地址一般带鉴权：

- RTMP 地址通常只有短有效期，且可能播放一次后失效。
- FLV/HLS/WS-FLV 地址通常短有效期，并可能和首次播放 IP 绑定。
- 播放端断线后，应重新调用 `/stream/start` 获取新地址。
- 主站文档说明“视频流在一定时间内没有客户端观看会自动停止直播”，因此无人观看时 WVP/ZLM 侧断流是正常现象。

## 七、验证步骤

### 7.1 验证 RTSP 源

```bash
ffplay rtsp://10.21.31.103:8554/video1
```

能看到画面再继续。

### 7.2 验证 ZLM 拉流

```bash
curl "http://127.0.0.1:9092/index/api/getMediaList?secret=my_secret_key_2025"
ffplay rtsp://127.0.0.1:8554/proxy/robot-dog
```

### 7.3 验证 WVP 注册主站

在 WVP 日志或后台确认：

- 向主站发送 `REGISTER`。
- 主站返回 `200 OK`。
- 主站设备状态变为在线。

也可以调用主站设备状态接口查询，接口名以主站文档实际拼写为准。

### 7.4 验证主站点播

调用主站 `/stream/start`：

```json
{
  "channelId": "<channelList[0].channelId>"
}
```

预期：

- 主站返回 FLV/HLS/WS-FLV/RTMP 播放地址。
- WVP 收到主站 `INVITE`。
- ZLM 开始向主站发送 RTP。
- 浏览器/VLC 能播放主站返回的地址。

## 八、常见问题

| 现象 | 优先检查 |
|------|----------|
| 主站显示设备离线 | WVP 是否成功 REGISTER；`deviceCode`、`accessPassword`、主站平台 ID/域是否正确；5060/UDP 是否可达 |
| 主站能看到设备但无通道 | WVP 是否上报 Catalog；通道编码是否使用 `channelCode`；通道数量是否和申请一致 |
| `/stream/start` 返回设备离线 | 主站侧设备状态未在线，先看 SIP 注册 |
| `/stream/start` 有地址但播放黑屏 | WVP 是否收到 INVITE；ZLM 是否有 `proxy/robot-dog` 流；RTP 端口、防火墙、SSRC 是否匹配 |
| 只有首帧或很卡 | 机器狗码率过高；关键帧间隔太长；网络上行不足；尝试降低 RTSP 源码率 |
| 有视频无音频 | 机器狗源可能无音频；可用 `add_mute_audio=1` 补静音音轨 |
| 播放地址过一会儿失效 | 主站播放 URL 有鉴权有效期，断线后重新调用 `/stream/start` |
| WVP 配置不生效 | 检查 YAML 层级，尤其不要出现两个同级 `sip:` |

## 九、不推荐的轻量自写 SIP 方案

理论上可以自写 SIP 客户端，然后在收到主站 INVITE 后调用 ZLM：

```bash
POST /index/api/startSendRtp
```

但这个 API 只能负责“发送 RTP”这一段。你仍然要自己完成：

- SIP REGISTER 和 401 Digest 认证。
- Catalog/DeviceInfo/Keepalive。
- INVITE/200 OK/ACK/BYE。
- 解析 SDP 中的 RTP 地址、端口、SSRC、TCP/UDP 模式。
- 处理主站重试、超时、断流、重新点播。

因此除非后续明确要做自研国标网关，否则不要把它作为当前落地路径。

## 十、最终建议

实践顺序建议：

1. 先用 `/devMgr/deviceApply` 申请设备，记录 `deviceCode`、`accessPassword`、`channelId`、`channelCode`。
2. 部署 ZLMediaKit，确认能拉到机器狗 RTSP。
3. 部署 WVP-PRO，配置成使用 `deviceCode` 和 `accessPassword` 向视频主站注册。
4. 在 WVP 中把机器狗 RTSP 映射为主站返回的通道编码。
5. 调主站 `/stream/start`，用主站返回的播放地址验证画面。

如果主站方确认支持 RTMP 直推，可以另走 `ffmpeg → RTMP → 主站`，这会比 GB28181 简单很多；否则按本文的 WVP-PRO + ZLMediaKit 方案推进。
