"""GB/T 28181 SIP 信令客户端 — 替代 WVP-PRO

职责：
  1. 向视频主站 SIP 注册（MD5 Digest 认证），失败自动重试
  2. 定时心跳保活
  3. 接收 INVITE → 调 ZLMediaKit API 推送 RTP → 回复 200 OK
  4. 接收 BYE → 停止推流
  5. 提供 selfcheck() 诊断当前状态

所有配置从 .env 读取，零外部依赖（只用标准库）。
"""

import hashlib
import json
import os
import random
import re
import socket
import string
import threading
import time
import urllib.request
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 配置
# ============================================================

@dataclass
class Gb28181Config:
    local_sip_ip: str = "192.168.0.200"
    local_sip_port: int = 15060

    server_ip: str = "14.116.205.39"
    server_port: int = 5788
    server_id: str = "44019000002000000001"
    server_domain: str = "4401900000"

    device_id: str = "44010600491325000010"
    auth_id: str = "44010600491325000010"
    password: str = "123456"
    channel_id: str = "44010600491315000014"

    expires: int = 3600
    heartbeat_sec: int = 60
    register_retry_sec: int = 15          # 注册失败后重试间隔
    register_timeout_sec: int = 10        # 无认证 REGISTER 发送后等待 401 的超时

    zlm_base: str = "http://127.0.0.1:9092"
    zlm_secret: str = "my_secret_key_2025"
    zlm_stream_app: str = "proxy"
    zlm_stream_name: str = "robot-dog"

    debug: bool = False                   # True 时打印原始 SIP 报文


def _load_config_from_env() -> Gb28181Config:
    cfg = Gb28181Config()

    sip_ip = os.environ.get("SIP_IP", os.environ.get("GB28181_LOCAL_SIP_IP"))
    if sip_ip:
        cfg.local_sip_ip = sip_ip
    sip_port = os.environ.get("GB28181_LOCAL_SIP_PORT")
    if sip_port:
        cfg.local_sip_port = int(sip_port)

    for key, attr, cast in [
        ("GB28181_SIP_SERVER_HOST", "server_ip", str),
        ("GB28181_SIP_SERVER_PORT", "server_port", int),
        ("GB28181_SIP_SERVER_ID", "server_id", str),
        ("GB28181_SIP_DOMAIN", "server_domain", str),
        ("GB28181_SIP_USERNAME", "device_id", str),
        ("GB28181_SIP_AUTH_ID", "auth_id", str),
        ("GB28181_SIP_PASSWORD", "password", str),
        ("GB28181_CHANNEL_ID", "channel_id", str),
    ]:
        val = os.environ.get(key)
        if val:
            setattr(cfg, attr, cast(val))

    cfg.debug = os.environ.get("GB28181_DEBUG", "").lower() in ("1", "true", "yes")
    return cfg


# ============================================================
# 诊断结果
# ============================================================

@dataclass
class Gb28181Status:
    running: bool = False
    registered: bool = False
    push_active: bool = False
    local_sip: str = ""
    server_sip: str = ""
    device_id: str = ""
    push_target: str = ""          # "ip:port" when pushing
    last_error: str = ""
    heartbeat_fail_count: int = 0  # 连续心跳失败次数
    zlm_rtsp_ok: bool = False      # ZLM RTSP 源流正常
    zlm_rtp_active: bool = False   # ZLM RTP 正在推流
    zlm_rtp_bytes: int = 0         # RTP 已发送字节数


# ============================================================
# SIP 工具函数
# ============================================================

def _random_hex(n: int = 16) -> str:
    return "".join(random.choice(string.hexdigits) for _ in range(n))


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _compute_digest(username: str, realm: str, password: str,
                    method: str, uri: str, nonce: str,
                    qop: str = None, cnonce: str = None, nc: str = None) -> str:
    """GB28181 MD5 Digest: 支持 qop=auth"""
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
    if qop == "auth":
        return _md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        return _md5(f"{ha1}:{nonce}:{ha2}")


def _branch() -> str:
    return "z9hG4bK" + _random_hex(16)


def _tag() -> str:
    return _random_hex(8)


# ============================================================
# SDP 解析
# ============================================================

@dataclass
class SdpInfo:
    dst_ip: str = ""
    dst_port: int = 0
    is_udp: bool = True
    ssrc: str = ""
    pt: int = 96


def _parse_sdp(body: str) -> SdpInfo:
    info = SdpInfo()

    m = re.search(r"c=IN\s+IP4\s+(\S+)", body)
    if m:
        info.dst_ip = m.group(1)

    m = re.search(r"m=video\s+(\d+)\s+(\S+)", body)
    if m:
        info.dst_port = int(m.group(1))
        info.is_udp = "TCP" not in m.group(2).upper()

    m = re.search(r"^y=(\d+)", body, re.MULTILINE)
    if m:
        info.ssrc = f"{int(m.group(1)):08X}"

    if not info.ssrc:
        m = re.search(r"a=ssrc:(\d+)", body)
        if m:
            info.ssrc = f"{int(m.group(1)):08X}"

    m = re.search(r"m=video\s+\d+\s+\S+\s+(\d+)", body)
    if m:
        info.pt = int(m.group(1))

    return info


def _build_response_sdp(cfg: Gb28181Config, invite_sdp: SdpInfo) -> str:
    sid = str(int(time.time()))
    lines = [
        "v=0",
        f"o={cfg.device_id} {sid} {sid} IN IP4 {cfg.local_sip_ip}",
        "s=Play",
        f"c=IN IP4 {cfg.local_sip_ip}",
        "t=0 0",
        f"m=video {invite_sdp.dst_port} {'RTP/AVP' if invite_sdp.is_udp else 'TCP/RTP/AVP'} {invite_sdp.pt}",
        "a=sendonly",
        f"a=rtpmap:{invite_sdp.pt} PS/90000",
    ]
    if invite_sdp.ssrc:
        lines.append(f"y={int(invite_sdp.ssrc, 16)}")
    return "\r\n".join(lines) + "\r\n"


# ============================================================
# SIP 消息解析（提取必须回显的头部字段）
# ============================================================

@dataclass
class _SipRequestInfo:
    """从收到的 SIP 请求中提取需要回显的字段"""
    method: str = ""
    via_full: str = ""        # 完整 Via 头值（不含 "Via: " 前缀）
    from_tag: str = ""
    to_tag: str = ""
    call_id: str = ""
    cseq: str = ""
    cseq_method: str = ""
    from_uri: str = ""
    to_uri: str = ""


def _extract_request_info(raw: str) -> _SipRequestInfo:
    info = _SipRequestInfo()

    m = re.search(r"^(\w+)\s+sip:", raw, re.IGNORECASE | re.MULTILINE)
    if m:
        info.method = m.group(1).upper()

    # 提取完整 Via 头值（Via: 之后的部分），用于原样回显
    m = re.search(r'^Via:\s*(.+)$', raw, re.IGNORECASE | re.MULTILINE)
    if m:
        info.via_full = m.group(1).strip()

    m = re.search(r'From:.*?;tag=(\S+)', raw, re.IGNORECASE)
    if m:
        info.from_tag = m.group(1).rstrip(">").rstrip(";")

    m = re.search(r'From:\s*<([^>]+)>', raw, re.IGNORECASE)
    if m:
        info.from_uri = m.group(1)

    m = re.search(r'To:.*?;tag=(\S+)', raw, re.IGNORECASE)
    if m:
        info.to_tag = m.group(1).rstrip(">").rstrip(";")

    m = re.search(r'To:\s*<([^>]+)>', raw, re.IGNORECASE)
    if m:
        info.to_uri = m.group(1)

    m = re.search(r'Call-ID:\s*(\S+)', raw, re.IGNORECASE)
    if m:
        info.call_id = m.group(1)

    m = re.search(r'CSeq:\s*(\d+)\s+(\w+)', raw, re.IGNORECASE)
    if m:
        info.cseq = m.group(1)
        info.cseq_method = m.group(2).upper()

    return info


# ============================================================
# 核心客户端
# ============================================================

class Gb28181Client:

    def __init__(self, config: Gb28181Config = None):
        self.cfg = config or _load_config_from_env()
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._cseq = 0
        self._call_id = ""
        self._from_tag = _tag()
        self._nonce: Optional[str] = None
        self._realm = self.cfg.server_domain
        self._qop: Optional[str] = None
        self._registered = False
        self._push_active = False
        self._push_target = ""
        self._last_error = ""
        self._last_register_ok = 0.0           # 最后一次收到 REGISTER 200 OK 的时间
        self._heartbeat_fail_count = 0         # 连续心跳失败计数
        self._recv_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._register_thread: Optional[threading.Thread] = None

    # ====== 生命周期 ======

    def start(self):
        print("[GB28181] ── 启动 SIP 客户端 ──")
        print(f"[GB28181]   本地: {self.cfg.local_sip_ip}:{self.cfg.local_sip_port}")
        print(f"[GB28181]   主站: {self.cfg.server_ip}:{self.cfg.server_port}")
        print(f"[GB28181]   设备: {self.cfg.device_id}")
        print(f"[GB28181]   通道: {self.cfg.channel_id}")

        # 网络可达性检查
        if not self._check_network():
            print("[GB28181] ⚠ 网络不可达，将继续尝试注册（后台重试）")

        self._call_id = f"{_random_hex(16)}@{self.cfg.local_sip_ip}"

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind(("0.0.0.0", self.cfg.local_sip_port))
        except OSError as e:
            self._last_error = f"端口 {self.cfg.local_sip_port} 绑定失败: {e}"
            print(f"[GB28181] ✗ {self._last_error}")
            return

        self._sock.settimeout(2.0)
        self._running = True

        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        # 后台线程执行注册（不断重试直到成功）
        self._register_thread = threading.Thread(target=self._register_loop, daemon=True)
        self._register_thread.start()

        print("[GB28181] SIP 客户端已启动（后台注册中...）")

    def stop(self):
        print("[GB28181] 正在停止 ...")
        self._running = False

        if self._registered:
            self._send_register(expires=0)
            time.sleep(0.5)

        if self._push_active:
            self._stop_rtp_push()

        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

        print("[GB28181] SIP 客户端已停止")

    # ====== 网络检查 ======

    def _check_network(self) -> bool:
        """检查 UDP 是否可达 SIP 服务器"""
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        test_sock.settimeout(3)
        try:
            test_sock.sendto(b"", (self.cfg.server_ip, self.cfg.server_port))
            print(f"[GB28181] ✓ UDP 可达 {self.cfg.server_ip}:{self.cfg.server_port}")
            return True
        except Exception as e:
            self._last_error = f"UDP 不可达 {self.cfg.server_ip}:{self.cfg.server_port}: {e}"
            print(f"[GB28181] ✗ {self._last_error}")
            print(f"[GB28181]   排查: nc -zvu {self.cfg.server_ip} {self.cfg.server_port}")
            return False
        finally:
            test_sock.close()

    # ====== 注册循环（后台重试） ======

    def _register_loop(self):
        """后台线程：循环注册直到成功"""
        while self._running and not self._registered:
            attempt = 0
            self._nonce = None
            self._qop = None
            self._cseq = 0
            self._call_id = f"{_random_hex(16)}@{self.cfg.local_sip_ip}"

            # 发送无认证 REGISTER
            print("[GB28181] → REGISTER (无认证，等待 401 挑战...)")
            self._send_register(expires=self.cfg.expires)

            # 等待 401 → 发带认证 REGISTER → 等 200
            deadline = time.time() + self.cfg.register_timeout_sec
            got_401 = False

            while self._running and not self._registered and time.time() < deadline:
                if self._nonce and not got_401:
                    got_401 = True
                    print(f"[GB28181] ← 收到 401 挑战, nonce={self._nonce[:16]}...")
                    print("[GB28181] → REGISTER (带 MD5 认证)...")
                    self._send_register(expires=self.cfg.expires)
                    deadline = time.time() + self.cfg.register_timeout_sec

                # 等待 _handle_register_ok 设置 _registered
                time.sleep(0.5)

            if self._registered:
                print("[GB28181] ★ 注册成功！设备已上线")
                self._start_heartbeat()
                return

            # 本轮失败
            self._last_error = "注册超时：主站未响应 401 或 200"
            print(f"[GB28181] ✗ {self._last_error}")
            print(f"[GB28181]   排查: 检查 SIP 端口/防火墙/主站是否在线")
            print(f"[GB28181]   {self.cfg.register_retry_sec}s 后重试...")
            time.sleep(self.cfg.register_retry_sec)

    def _start_heartbeat(self):
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        """心跳保活 + 掉线检测 + 自动重注册"""
        while self._running:
            time.sleep(self.cfg.heartbeat_sec)
            if not self._running:
                break
            if not self._registered:
                continue

            # 发送心跳 REGISTER
            heartbeat_sent = time.time()
            print("[GB28181] ♡ 心跳 REGISTER ...")
            self._send_register(expires=self.cfg.expires)

            # 等待 200 OK（最多 5 秒）
            time.sleep(5.0)

            if not self._running:
                break

            # 判断心跳是否成功（recv_loop 收到 200 会更新 _last_register_ok）
            if self._last_register_ok >= heartbeat_sent:
                continue  # 成功，继续下一轮

            # 心跳失败
            self._heartbeat_fail_count += 1
            print(f"[GB28181] ⚠ 心跳无响应 ({self._heartbeat_fail_count}/3)")

            if self._heartbeat_fail_count >= 3:
                print("[GB28181] ✗ 连续 3 次心跳失败，标记掉线，开始重注册...")
                self._last_error = "心跳超时，设备已掉线"
                self._registered = False
                self._nonce = None
                self._qop = None
                self._register_thread = threading.Thread(
                    target=self._register_loop, daemon=True
                )
                self._register_thread.start()

    # ====== UDP 收发 ======

    def _send_raw(self, data: bytes):
        if self.cfg.debug:
            print(f"[GB28181-DEBUG] >>>\n{data.decode(errors='replace')}")
        try:
            self._sock.sendto(data, (self.cfg.server_ip, self.cfg.server_port))
        except Exception as e:
            print(f"[GB28181] 发送失败: {e}")

    def _recv_loop(self):
        buf = bytearray(8192)
        while self._running:
            try:
                n, addr = self._sock.recvfrom_into(buf)
                raw = buf[:n].decode("utf-8", errors="replace")
                if self.cfg.debug:
                    print(f"[GB28181-DEBUG] <<<\n{raw}")
                self._on_message(raw)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"[GB28181] 接收异常: {e}")

    def _on_message(self, raw: str):
        first_line = raw.split("\r\n")[0] if raw else ""

        if first_line.upper().startswith("SIP/2.0"):
            status_code = first_line.split(" ")[1] if len(first_line.split(" ")) > 1 else ""
            cseq_m = re.search(r"CSeq:\s*(\d+)\s+(\w+)", raw, re.IGNORECASE)
            method = cseq_m.group(2).upper() if cseq_m else "?"

            if status_code == "401" and method == "REGISTER":
                self._handle_401(raw)
            elif status_code == "200" and method == "REGISTER":
                self._handle_register_ok(raw)
            elif status_code == "200":
                print(f"[GB28181] ← {status_code} ({method})")
            else:
                print(f"[GB28181] ← {status_code} ({method})")
        else:
            method = first_line.split(" ")[0].upper()
            if method == "INVITE":
                print("[GB28181] ← INVITE（点播请求）")
                self._handle_invite(raw)
            elif method == "BYE":
                print("[GB28181] ← BYE（停止点播）")
                self._handle_bye(raw)
            elif method == "MESSAGE":
                print("[GB28181] ← MESSAGE（控制指令）")
                self._handle_message(raw)
            elif method == "SUBSCRIBE":
                self._handle_subscribe(raw)
            elif method == "ACK":
                pass  # ACK 不需要处理
            else:
                print(f"[GB28181] ← {method}（未处理）")

    # ====== REGISTER / 401 / 200 ======

    def _build_register(self, expires: int, with_auth: bool) -> bytes:
        self._cseq += 1
        device_domain = self.cfg.device_id[:10]
        request_uri = f"sip:{self.cfg.server_id}@{self.cfg.server_ip}:{self.cfg.server_port}"

        lines = [
            f"REGISTER {request_uri} SIP/2.0",
            f"Call-ID: {self._call_id}",
            f"CSeq: {self._cseq} REGISTER",
            f"From: <sip:{self.cfg.device_id}@{device_domain}>;tag={self._from_tag}",
            f"To: <sip:{self.cfg.device_id}@{device_domain}>",
            f"Via: SIP/2.0/UDP {self.cfg.local_sip_ip}:{self.cfg.local_sip_port};branch={_branch()};rport",
            "Max-Forwards: 70",
            f"Contact: <sip:{self.cfg.device_id}@{self.cfg.local_sip_ip}:{self.cfg.local_sip_port}>",
            f"Expires: {expires}",
            "User-Agent: RobotDog-M20-GW",
        ]

        if with_auth and self._nonce:
            auth_user = self.cfg.auth_id or self.cfg.device_id
            cnonce = str(_uuid.uuid4())
            nc = "00000001"
            resp = _compute_digest(auth_user, self._realm, self.cfg.password,
                                   "REGISTER", request_uri, self._nonce,
                                   qop=self._qop, cnonce=cnonce, nc=nc)
            auth = (
                f'Authorization: Digest username="{auth_user}",'
                f'realm="{self._realm}",'
                f'nonce="{self._nonce}",'
                f'uri="{request_uri}",'
                f'response="{resp}",'
                f'algorithm=MD5'
            )
            if self._qop == "auth":
                auth += f',qop={self._qop},cnonce="{cnonce}",nc={nc}'
            lines.append(auth)

        body = ""
        lines.append(f"Content-Length: {len(body.encode())}")
        return ("\r\n".join(lines) + "\r\n\r\n" + body).encode()

    def _send_register(self, expires: int = 3600):
        with_auth = self._nonce is not None
        data = self._build_register(expires=expires, with_auth=with_auth)
        self._send_raw(data)

    def _handle_401(self, raw: str):
        m = re.search(r'nonce="([^"]+)"', raw)
        if m:
            self._nonce = m.group(1)
        m = re.search(r'realm="([^"]+)"', raw)
        if m:
            self._realm = m.group(1)
        m = re.search(r'qop="([^"]+)"', raw)
        if m:
            self._qop = m.group(1)

        # 如果已注册状态下收到 401（平台重启 nonce 过期），立刻用新 nonce 重发
        if self._registered and self._nonce:
            print("[GB28181]   平台重启检测（新 nonce），立即重新认证...")
            self._send_register(expires=self.cfg.expires)

    def _handle_register_ok(self, raw: str):
        self._last_register_ok = time.time()
        self._heartbeat_fail_count = 0
        if not self._registered:
            self._registered = True

    # ====== INVITE ======

    def _handle_invite(self, raw: str):
        req = _extract_request_info(raw)
        parts = raw.split("\r\n\r\n", 1)
        body = parts[1] if len(parts) > 1 else ""

        if not body:
            print("[GB28181] INVITE 无 SDP body")
            self._send_sip_response(req, 400)
            return

        sdp = _parse_sdp(body)
        target = f"{sdp.dst_ip}:{sdp.dst_port}"
        print(f"[GB28181]   RTP 目标: {target} "
              f"({'UDP' if sdp.is_udp else 'TCP'}) SSRC={sdp.ssrc} PT={sdp.pt}")

        # 同一个目标+SSRC的重复 INVITE 直接回 200 OK，不重复启流
        if self._push_active and self._push_target == target:
            sdp_body = _build_response_sdp(self.cfg, sdp)
            self._send_sip_response(req, 200, sdp_body)
            print(f"[GB28181]   重复 INVITE，跳过（推流已在进行）")
            return

        ok, local_port = self._start_rtp_push(sdp)
        if ok:
            self._push_active = True
            self._push_target = target
            sdp_body = _build_response_sdp(self.cfg, sdp)
            self._send_sip_response(req, 200, sdp_body)
            print(f"[GB28181] ★ 推流已启动 → {target}")
            threading.Thread(target=self._delayed_zlm_check, daemon=True).start()
        else:
            self._last_error = "RTP 推流启动失败"
            print(f"[GB28181] ✗ {self._last_error}")
            self._send_sip_response(req, 500)

    # ====== BYE ======

    def _handle_bye(self, raw: str):
        req = _extract_request_info(raw)
        self._stop_rtp_push()
        self._push_active = False
        self._push_target = ""
        self._send_sip_response(req, 200)
        print("[GB28181] 推流已停止")

    # ====== MESSAGE: MANSCDP 控制指令处理 ======

    def _parse_manuscdp_xml(self, body: str) -> dict:
        """从 MANSCDP XML body 中提取 CmdType, SN, DeviceID"""
        result = {}
        for field in ["CmdType", "SN", "DeviceID"]:
            m = re.search(rf"<{field}>(.*?)</{field}>", body, re.IGNORECASE)
            if m:
                result[field] = m.group(1).strip()
        return result

    def _build_catalog_response(self, sn: str) -> bytes:
        """构建 Catalog 应答 MANSCDP XML"""
        xml = (
            '<?xml version="1.0" encoding="gb2312"?>\r\n'
            '<Response>\r\n'
            f'<CmdType>Catalog</CmdType>\r\n'
            f'<SN>{sn}</SN>\r\n'
            f'<DeviceID>{self.cfg.device_id}</DeviceID>\r\n'
            '<SumNum>1</SumNum>\r\n'
            '<DeviceList Num="1">\r\n'
            '<Item>\r\n'
            f'<DeviceID>{self.cfg.channel_id}</DeviceID>\r\n'
            '<Name>RobotDog-M20-Channel</Name>\r\n'
            '<Manufacturer>ShanMao</Manufacturer>\r\n'
            '<Model>M20</Model>\r\n'
            '<Owner>RobotDog</Owner>\r\n'
            '<CivilCode>440106</CivilCode>\r\n'
            '<Address>Local</Address>\r\n'
            '<Parental>0</Parental>\r\n'
            f'<ParentID>{self.cfg.device_id}</ParentID>\r\n'
            '<SafetyWay>0</SafetyWay>\r\n'
            '<RegisterWay>1</RegisterWay>\r\n'
            '<Secrecy>0</Secrecy>\r\n'
            '<Status>ON</Status>\r\n'
            '</Item>\r\n'
            '</DeviceList>\r\n'
            '</Response>'
        )
        return xml.encode("gb2312")

    def _send_message_request(self, body_bytes: bytes):
        """发送 MESSAGE 请求到平台（设备 → 平台）"""
        self._cseq += 1
        device_domain = self.cfg.device_id[:10]
        request_uri = f"sip:{self.cfg.server_id}@{self.cfg.server_ip}:{self.cfg.server_port}"
        call_id = f"{_random_hex(16)}@{self.cfg.local_sip_ip}"
        branch = _branch()
        from_tag = _tag()

        lines = [
            f"MESSAGE {request_uri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.cfg.local_sip_ip}:{self.cfg.local_sip_port};rport;branch={branch}",
            f"From: <sip:{self.cfg.device_id}@{device_domain}>;tag={from_tag}",
            f"To: <sip:{self.cfg.server_id}@{self.cfg.server_domain}>",
            f"Call-ID: {call_id}",
            f"CSeq: {self._cseq} MESSAGE",
            f"Contact: <sip:{self.cfg.device_id}@{self.cfg.local_sip_ip}:{self.cfg.local_sip_port}>",
            "Max-Forwards: 70",
            "User-Agent: RobotDog-M20-GW",
            "Content-Type: Application/MANSCDP+xml",
            f"Content-Length: {len(body_bytes)}",
        ]

        header = "\r\n".join(lines) + "\r\n\r\n"
        print(f"[GB28181] → MESSAGE ({len(body_bytes)} bytes)")
        self._send_raw(header.encode() + body_bytes)

    def _handle_message(self, raw: str):
        """收到的 MESSAGE → 先回 200 OK → 根据 CmdType 处理"""
        req = _extract_request_info(raw)
        parts = raw.split("\r\n\r\n", 1)
        body = parts[1] if len(parts) > 1 else ""

        if not body:
            print("[GB28181]   MESSAGE 无 body，仅回 200 OK")
            self._send_sip_response(req, 200)
            return

        parsed = self._parse_manuscdp_xml(body)
        cmd = parsed.get("CmdType", "?")
        sn = parsed.get("SN", "1")
        print(f"[GB28181]   CmdType={cmd}, SN={sn}")

        # 第一步：回 200 OK 确认收到
        self._send_sip_response(req, 200)

        # 第二步：按指令类型处理
        if cmd == "Catalog":
            resp_bytes = self._build_catalog_response(sn)
            self._send_message_request(resp_bytes)
            print(f"[GB28181] ★ Catalog 应答已发送")
        elif cmd == "DeviceInfo":
            # 设备信息查询，暂回简单确认
            pass
        elif cmd == "DeviceStatus":
            # 设备状态查询
            pass
        elif cmd == "Keepalive":
            # 心跳
            pass
        else:
            print(f"[GB28181]   未处理的 CmdType: {cmd}")

    # ====== SUBSCRIBE ======

    def _handle_subscribe(self, raw: str):
        """平台订阅事件（上下线/告警等），回复 200 OK 即可"""
        req = _extract_request_info(raw)
        self._send_sip_response(req, 200)
        print("[GB28181]   SUBSCRIBE → 200 OK")

    # ====== SIP 响应（正确回显请求头部） ======

    def _send_sip_response(self, req: _SipRequestInfo, code: int, sdp: str = ""):
        """发送 SIP 响应，Via/From/To/Call-ID/CSeq 必须原样回显请求头"""
        reason = {200: "OK", 400: "Bad Request", 500: "Server Internal Error",
                  481: "Call/Transaction Does Not Exist"}.get(code, "OK")

        local_tag = _tag()

        lines = [
            f"SIP/2.0 {code} {reason}",
            f"Via: {req.via_full}" if req.via_full else f"Via: SIP/2.0/UDP {self.cfg.local_sip_ip}:{self.cfg.local_sip_port};rport;branch=z9hG4bK{_random_hex(10)}",
            f"From: <{req.from_uri}>;tag={req.from_tag}",
            f"To: <{req.to_uri}>;tag={req.to_tag or local_tag}",
            f"Call-ID: {req.call_id}",
            f"CSeq: {req.cseq} {req.cseq_method}",
            "User-Agent: RobotDog-M20-GW",
        ]

        if sdp:
            lines.append(f"Content-Type: application/sdp")
            lines.append(f"Content-Length: {len(sdp.encode())}")
            body = sdp.rstrip("\r\n") + "\r\n"
        else:
            body = ""
            lines.append("Content-Length: 0")

        raw = "\r\n".join(lines) + "\r\n\r\n" + body
        print(f"[GB28181] → {code} {reason}")
        self._send_raw(raw.encode())

    # ====== ZLMediaKit HTTP API ======

    def _start_rtp_push(self, sdp: SdpInfo) -> tuple:
        body = json.dumps({
            "secret": self.cfg.zlm_secret,
            "vhost": "__defaultVhost__",
            "app": self.cfg.zlm_stream_app,
            "stream": self.cfg.zlm_stream_name,
            "ssrc": sdp.ssrc,
            "dst_url": sdp.dst_ip,
            "dst_port": sdp.dst_port,
            "is_udp": 1 if sdp.is_udp else 0,
            "src_port": 0,
            "pt": sdp.pt,
            "use_ps": 1,
            "only_audio": 0,
        })

        url = f"{self.cfg.zlm_base}/index/api/startSendRtp"
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    url, data=body.encode(),
                    headers={"Content-Type": "application/json"},
                )
                resp = urllib.request.urlopen(req, timeout=5)
                result = json.loads(resp.read().decode())
                if result.get("code") == 0:
                    local_port = result.get("data", {}).get("local_port", 0)
                    print(f"[GB28181] ZLM RTP 推送就绪, local_port={local_port}")
                    return True, local_port
                else:
                    self._last_error = f"ZLM startSendRtp: {result.get('msg', '?')}"
                    print(f"[GB28181] {self._last_error}")
            except Exception as e:
                print(f"[GB28181] ZLM API 异常 ({attempt + 1}/3): {e}")
                time.sleep(1)
        return False, 0

    def _delayed_zlm_check(self):
        """后台线程：延迟 2 秒后检查 ZLM 推流状态，不阻塞 SIP 收包"""
        time.sleep(2)
        zlm = self._check_zlm_stream()
        print(f"[GB28181]   ZLM 状态: RTSP源={'OK' if zlm['rtsp_ok'] else '异常'} "
              f"| RTP推流={'OK' if zlm['rtp_active'] else '失败'} "
              f"| 已发 {zlm['rtp_bytes']} bytes")

    def _check_zlm_stream(self) -> dict:
        """查询 ZLM RTSP 源流和 RTP 推流状态"""
        result = {"rtsp_ok": False, "rtp_active": False, "rtp_bytes": 0}
        stream_id = f"{self.cfg.zlm_stream_app}/{self.cfg.zlm_stream_name}"
        try:
            # RTSP 源流 — 用 getMediaList 检查流是否存在且有 track
            api = f"{self.cfg.zlm_base}/index/api/getMediaList?secret={self.cfg.zlm_secret}"
            req = urllib.request.Request(api)
            resp = json.loads(urllib.request.urlopen(req, timeout=3).read())
            if resp.get("code") == 0:
                for s in resp.get("data", []):
                    if s.get("stream") == self.cfg.zlm_stream_name:
                        result["rtsp_ok"] = len(s.get("tracks", [])) > 0
                        break

            # RTP 推流 — getRtpInfo 需要 stream_id 参数
            api = (f"{self.cfg.zlm_base}/index/api/getRtpInfo"
                   f"?secret={self.cfg.zlm_secret}&stream_id={stream_id}")
            req = urllib.request.Request(api)
            resp = json.loads(urllib.request.urlopen(req, timeout=3).read())
            if resp.get("code") == 0:
                for s in resp.get("data", []):
                    result["rtp_active"] = True
                    result["rtp_bytes"] += int(s.get("totalBytes", 0))
        except Exception:
            pass
        return result

    def _stop_rtp_push(self):
        body = json.dumps({
            "secret": self.cfg.zlm_secret,
            "vhost": "__defaultVhost__",
            "app": self.cfg.zlm_stream_app,
            "stream": self.cfg.zlm_stream_name,
        })
        url = f"{self.cfg.zlm_base}/index/api/stopSendRtp"
        try:
            req = urllib.request.Request(
                url, data=body.encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=5)
            result = json.loads(resp.read().decode())
            print(f"[GB28181] ZLM 推送已停止: {result.get('msg', 'ok')}")
        except Exception as e:
            print(f"[GB28181] ZLM stopSendRtp 异常: {e}")

    # ====== 诊断 API ======

    def selfcheck(self) -> Gb28181Status:
        """返回当前状态，供 main.py 查询"""
        zlm = self._check_zlm_stream() if self._push_active else {}
        return Gb28181Status(
            running=self._running,
            registered=self._registered,
            push_active=self._push_active,
            local_sip=f"{self.cfg.local_sip_ip}:{self.cfg.local_sip_port}",
            server_sip=f"{self.cfg.server_ip}:{self.cfg.server_port}",
            device_id=self.cfg.device_id,
            push_target=self._push_target,
            last_error=self._last_error,
            heartbeat_fail_count=self._heartbeat_fail_count,
            zlm_rtsp_ok=zlm.get("rtsp_ok", False),
            zlm_rtp_active=zlm.get("rtp_active", False),
            zlm_rtp_bytes=zlm.get("rtp_bytes", 0),
        )


# ============================================================
# 工厂
# ============================================================

_gb_client: Optional[Gb28181Client] = None


def get_client() -> Gb28181Client:
    global _gb_client
    if _gb_client is None:
        _gb_client = Gb28181Client(_load_config_from_env())
    return _gb_client
