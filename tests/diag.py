"""GB28181 全链路诊断脚本 — 从摄像头到平台逐段排查"""

import json
import os
import socket
import subprocess
import sys
import urllib.request

from dotenv import load_dotenv
load_dotenv()

RTSP = os.environ.get("ROBOT_RTSP_URL", "")
ZLM_BASE = "http://127.0.0.1:9092"
ZLM_SECRET = os.environ.get("ZLM_SECRET", "")
SIP_IP = os.environ.get("GB28181_SIP_SERVER_HOST", "")
SIP_PORT = int(os.environ.get("GB28181_SIP_SERVER_PORT", "0"))
TCP_PORTS = [30000, 30006]
ZLM_APP = "proxy"
ZLM_STREAM = "robot-dog"


def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def ok(s):     print(f"  {green('OK')}  {s}")
def fail(s):   print(f"  {red('FAIL')} {s}")
def warn(s):   print(f"  {yellow('WARN')} {s}")
def info(s):   print(f"  {s}")


def zlm_api(path: str) -> dict:
    url = f"{ZLM_BASE}{path}"
    if "?" in url:
        url += f"&secret={ZLM_SECRET}"
    else:
        url += f"?secret={ZLM_SECRET}"
    try:
        req = urllib.request.Request(url)
        resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
        return resp
    except Exception as e:
        return {"_error": str(e)}


def zlm_api_post(path: str, body: dict) -> dict:
    body["secret"] = ZLM_SECRET
    url = f"{ZLM_BASE}{path}"
    try:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
        return resp
    except Exception as e:
        return {"_error": str(e)}


# ============================================================
print("=" * 60)
print(bold(" GB28181 全链路诊断"))
print("=" * 60)

# ---- 1. 摄像头 ----
print(bold("\n[1] 摄像头 RTSP 源"))
print(f"  地址: {RTSP}")

# ffprobe
try:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", RTSP],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        fail(f"ffprobe 返回非0: {r.stderr.strip()[-200:]}")
    else:
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            fail("ffprobe 输出不是有效JSON")
            data = {}

        streams = data.get("streams", [])
        if not streams:
            fail("未检测到媒体流")
        for s in streams:
            codec = s.get("codec_name", "?")
            w = s.get("width", "?")
            h = s.get("height", "?")
            fps = s.get("r_frame_rate", "?")
            ctype = s.get("codec_type", "?")
            status = green("H.264") if codec == "h264" else \
                     yellow(f"HEVC/H.265 (平台需确认兼容)") if codec in ("hevc", "h265") else \
                     red(f"未知编码: {codec}")
            info(f"[{ctype}] {codec}  {w}x{h}  {fps}fps  →  {status}")
except FileNotFoundError:
    warn("ffprobe 未安装，跳过编码检测")
except Exception as e:
    fail(f"ffprobe 异常: {e}")

# TCP 连通性
try:
    host, port_str = RTSP.replace("rtsp://", "").split("/")[0].split(":")
    port = int(port_str) if ":" in RTSP.split("/")[2] else 554
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    sock.connect((RTSP.replace("rtsp://", "").split("/")[0].split(":")[0],
                  int(RTSP.replace("rtsp://", "").split("/")[0].split(":")[1])))
    sock.close()
    ok(f"摄像头 TCP 可达")
except Exception as e:
    fail(f"摄像头不可达: {e}")

# ---- 2. Docker / ZLM ----
print(bold("\n[2] ZLMediaKit 容器"))

r = subprocess.run(
    ["docker", "inspect", "-f", "{{.State.Running}}|{{.State.Status}}",
     "dog-zlmediakit"],
    capture_output=True, text=True, timeout=5,
)
if r.returncode != 0:
    fail("dog-zlmediakit 容器不存在")
else:
    running, status = r.stdout.strip().split("|")
    if running == "true":
        ok(f"容器运行中 (status={status})")
    else:
        fail(f"容器未运行 (status={status})")

# ZLM API
zlm_cfg = zlm_api("/index/api/getServerConfig")
if zlm_cfg.get("_error"):
    fail(f"ZLM API 不可达: {zlm_cfg['_error']}")
elif zlm_cfg.get("code") == 0:
    ok("ZLM HTTP API 正常")
else:
    fail(f"ZLM API 异常: {zlm_cfg.get('msg', '?')}")

# ---- 3. ZLM RTSP 拉流代理 ----
print(bold(f"\n[3] RTSP 拉流代理 ({ZLM_APP}/{ZLM_STREAM})"))

media = zlm_api("/index/api/getMediaList")
streams_found = []
if media.get("code") == 0:
    for s in media.get("data", []):
        if s.get("stream") == ZLM_STREAM and s.get("app") == ZLM_APP:
            streams_found.append(s)
else:
    fail(f"getMediaList 失败: {media.get('msg', '?')}")

if not streams_found:
    fail(f"未找到流 {ZLM_APP}/{ZLM_STREAM}，RTSP 代理可能未添加或已断开")
else:
    # 取第一个（去重）
    s = streams_found[0]
    origin_url = s.get("originUrl", "?")
    total_bytes = s.get("totalBytes", 0)
    reader_count = s.get("totalReaderCount", 0)
    tracks = s.get("tracks", [])
    alive_sec = s.get("aliveSecond", 0)
    track_info = ", ".join(
        f"{t.get('codec_type','?')}/{t.get('codec_name','?')} "
        f"{t.get('width','?')}x{t.get('height','?')}"
        for t in tracks
    )

    ok(f"流已存在  源URL={origin_url}")
    info(f"  上行流量: {total_bytes / 1024 / 1024:.1f} MB")
    info(f"  在线时长: {alive_sec}s")
    info(f"  读者数量: {reader_count}")
    info(f"  Tracks:   {track_info}")
    if len(streams_found) > 1:
        warn(f"发现 {len(streams_found)} 个同名流（可能有残留 session）")

# ---- 4. RTP 推流状态 ----
print(bold("\n[4] RTP 推流状态"))

stream_id = f"{ZLM_APP}/{ZLM_STREAM}"
rtp = zlm_api(f"/index/api/getRtpInfo?stream_id={stream_id}")
if rtp.get("_error"):
    fail(f"getRtpInfo 异常: {rtp['_error']}")
elif rtp.get("code") != 0:
    warn(f"无活跃 RTP 推流 (msg={rtp.get('msg','?')})")
else:
    sessions = rtp.get("data", [])
    if not sessions:
        warn("RTP 推流列表为空，平台尚未点播或推流已断开")
    for sess in sessions:
        dst = f"{sess.get('dst_url','?')}:{sess.get('dst_port','?')}"
        proto = "UDP" if sess.get("is_udp") else "TCP"
        ssrc = sess.get("ssrc", "?")
        sent = int(sess.get("totalBytes", 0))
        local_port = sess.get("local_port", "?")
        ok(f"活跃推流 → {dst} ({proto})  SSRC={ssrc}  已发送={sent/1024:.1f}KB  local_port={local_port}")

# ---- 5. 网络 ----
print(bold("\n[5] 平台网络可达性"))

# SIP 端口
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    sock.sendto(b"", (SIP_IP, SIP_PORT))
    sock.close()
    ok(f"UDP {SIP_IP}:{SIP_PORT} (SIP信令)")
except Exception as e:
    fail(f"UDP {SIP_IP}:{SIP_PORT} 不可达: {e}")

# 常用媒体端口范围
for port in [30000, 30006, 554]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((SIP_IP, port))
        sock.close()
        ok(f"TCP {SIP_IP}:{port} (媒体)")
    except Exception:
        warn(f"TCP {SIP_IP}:{port} 不可达")

# ---- 6. 本机 SIP 端口 ----
print(bold("\n[6] 本机 SIP 端口"))
local_sip_port = int(os.environ.get("GB28181_LOCAL_SIP_PORT", "15060"))
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", local_sip_port))
    sock.close()
    ok(f"UDP :{local_sip_port} 可绑定")
except Exception as e:
    fail(f"UDP :{local_sip_port} 绑定失败: {e}")

# ---- 7. ZLM 最近日志 ----
print(bold(f"\n[7] ZLM 最近关键日志 (最近 20 行)"))
r = subprocess.run(
    ["docker", "logs", "--tail", "20", "dog-zlmediakit"],
    capture_output=True, text=True, timeout=10,
)
for line in r.stdout.strip().split("\n"):
    line = line.strip()
    if not line:
        continue
    if any(kw in line for kw in ["startSend", "stopSend", "onErr", "connect",
                                   "rtp", "Rtsp", "error", "Error", "fail"]):
        print(f"  {yellow('▶')} {line[-160:]}")
    elif any(kw in line for kw in ["rtsp://", "GET_PARAMETER", "onConnect"]):
        print(f"  {line[-160:]}")  # 常规 RTSP 心跳，不标色

# ---- 8. 本地服务端口 (8000) ----
print(bold(f"\n[8] 本地服务端口 8000"))
r = subprocess.run(
    ["lsof", "-ti", "tcp:8000"],
    capture_output=True, text=True, timeout=5,
)
pids = [p for p in r.stdout.strip().split("\n") if p]
if pids:
    r2 = subprocess.run(["ps", "-p", ",".join(pids), "-o", "pid,comm", "--no-headers"],
                        capture_output=True, text=True, timeout=5)
    warn(f"端口 8000 已被占用 ({len(pids)} 个进程):")
    for line in r2.stdout.strip().split("\n"):
        if line.strip():
            info(f"  {line.strip()}")
    if "--kill" in sys.argv:
        for pid in pids:
            try:
                subprocess.run(["kill", "-9", pid], capture_output=True, timeout=3)
                ok(f"已终止 PID {pid}")
            except Exception as e:
                fail(f"终止 PID {pid} 失败: {e}")
        print("  现在可以启动 uvicorn 了")
    else:
        warn("  加 --kill 参数自动清理后重启: uv run python diag.py --kill")
else:
    ok("端口 8000 空闲")
    if "--kill" in sys.argv:
        info("无需清理，可直接启动 uvicorn")

# ---- 总结 ----
print("\n" + "=" * 60)
print(bold(" 诊断结果汇总"))
print("=" * 60)

issues = []

# 检查各项
if not streams_found:
    issues.append("ZLM 没有拉流代理 → 检查 add_rtsp_proxy() 是否执行成功")
else:
    s = streams_found[0]
    tracks = s.get("tracks", [])
    if not tracks:
        issues.append("流存在但无 track → RTSP 源可能断连")
    for t in tracks:
        if t.get("codec_name") in ("hevc", "h265"):
            issues.append("摄像头输出 HEVC/H.265，平台需确认兼容，否则需 FFmpeg 转码")

rtp_ok = rtp.get("code") == 0 and len(rtp.get("data", [])) > 0
if not rtp_ok:
    issues.append("无活跃 RTP 推流 → 等待平台发 INVITE 点播")

if issues:
    print(bold("\n 待解决:"))
    for i, issue in enumerate(issues, 1):
        print(f"   {i}. {issue}")
else:
    print(green("\n ✓ 全链路正常，等待平台 INVITE 即可"))

print()
