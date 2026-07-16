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
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 配置
# ============================================================

@dataclass
class Gb28181Config:
    local_sip_ip: str = "192.168.0.194"
    local_sip_port: int = 15060

    server_ip: str = "42.193.245.235"
    server_port: int = 15692
    server_id: str = "44010082442009000088"
    server_domain: str = "4401008244"

    device_id: str = "440103004913250000002"
    auth_id: str = "440103004913250000002"
    password: str = "SntVMP_1a3c"
    channel_id: str = "440103004913150000002"

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


# ============================================================
# SIP 工具函数
# ============================================================

def _random_hex(n: int = 16) -> str:
    return "".join(random.choice(string.hexdigits) for _ in range(n))


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def _compute_digest(username: str, realm: str, password: str,
                    method: str, uri: str, nonce: str) -> str:
    """GB28181 MD5 Digest: HA1=MD5(user:realm:pwd), HA2=MD5(method:uri),
       response=MD5(HA1:nonce:HA2)"""
    ha1 = _md5(f"{username}:{realm}:{password}")
    ha2 = _md5(f"{method}:{uri}")
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
    via_branch: str = ""
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

    m = re.search(r'Via:\s*\S+[\s;]+branch=(\S+)', raw, re.IGNORECASE)
    if m:
        info.via_branch = m.group(1).rstrip(";")

    m = re.search(r'From:.*?;tag=(\S+)', raw, re.IGNORECASE)
    if m:
        info.from_tag = m.group(1).rstrip(">").rstrip(";")

    m = re.search(r'From:\s*<([^>]+)>', raw, re.IGNORECASE)
    if m:
        info.from_uri = m.group(1)

    # To 里可能有或没有 tag
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
        self._registered = False
        self._push_active = False
        self._push_target = ""
        self._last_error = ""
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
            test_sock.connect((self.cfg.server_ip, self.cfg.server_port))
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
        while self._running and self._registered:
            time.sleep(self.cfg.heartbeat_sec)
            if self._running and self._registered:
                print("[GB28181] ♡ 心跳 REGISTER ...")
                self._send_register(expires=self.cfg.expires)

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
                print("[GB28181] ← MESSAGE（忽略）")
            elif method == "ACK":
                pass  # ACK 不需要处理
            else:
                print(f"[GB28181] ← {method}（未处理）")

    # ====== REGISTER / 401 / 200 ======

    def _build_register(self, expires: int, with_auth: bool) -> bytes:
        self._cseq += 1
        sa = f"{self.cfg.server_ip}:{self.cfg.server_port}"

        lines = [
            f"REGISTER sip:{self.cfg.server_domain} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.cfg.local_sip_ip}:{self.cfg.local_sip_port};rport;branch={_branch()}",
            f"From: <sip:{self.cfg.device_id}@{self.cfg.server_domain}>;tag={self._from_tag}",
            f"To: <sip:{self.cfg.device_id}@{self.cfg.server_domain}>",
            f"Call-ID: {self._call_id}",
            f"CSeq: {self._cseq} REGISTER",
            f"Contact: <sip:{self.cfg.device_id}@{self.cfg.local_sip_ip}:{self.cfg.local_sip_port}>",
            "Max-Forwards: 70",
            "User-Agent: RobotDog-M20-GW",
            f"Expires: {expires}",
        ]

        if with_auth and self._nonce:
            uri = f"sip:{self.cfg.server_domain}"
            auth_user = self.cfg.auth_id or self.cfg.device_id
            resp = _compute_digest(auth_user, self._realm, self.cfg.password,
                                   "REGISTER", uri, self._nonce)
            lines.append(
                f'Authorization: Digest username="{auth_user}", realm="{self._realm}",'
                f' nonce="{self._nonce}", uri="{uri}", response="{resp}", algorithm=MD5'
            )

        lines.append("Content-Length: 0")
        return ("\r\n".join(lines) + "\r\n").encode()

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

    def _handle_register_ok(self, raw: str):
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
        print(f"[GB28181]   RTP 目标: {sdp.dst_ip}:{sdp.dst_port} "
              f"({'UDP' if sdp.is_udp else 'TCP'}) SSRC={sdp.ssrc} PT={sdp.pt}")

        ok, local_port = self._start_rtp_push(sdp)
        if ok:
            self._push_active = True
            self._push_target = f"{sdp.dst_ip}:{sdp.dst_port}"
            sdp_body = _build_response_sdp(self.cfg, sdp)
            self._send_sip_response(req, 200, sdp_body)
            print(f"[GB28181] ★ 推流已启动 → {sdp.dst_ip}:{sdp.dst_port}")
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

    # ====== SIP 响应（正确回显请求头部） ======

    def _send_sip_response(self, req: _SipRequestInfo, code: int, sdp: str = ""):
        """发送 SIP 响应，关键：Via branch / From tag / To tag / Call-ID / CSeq 必须回显"""
        reason = {200: "OK", 400: "Bad Request", 500: "Server Internal Error",
                  481: "Call/Transaction Does Not Exist"}.get(code, "OK")

        # 本地 tag 用于 To 头（如果请求里没有）
        local_tag = _tag()

        lines = [
            f"SIP/2.0 {code} {reason}",
            f"Via: SIP/2.0/UDP {self.cfg.local_sip_ip}:{self.cfg.local_sip_port};rport;branch={req.via_branch}",
            f"From: <{req.from_uri}>;tag={req.from_tag}",
            f"To: <{req.to_uri}>;tag={req.to_tag or local_tag}",
            f"Call-ID: {req.call_id}",
            f"CSeq: {req.cseq} {req.cseq_method}",
            "User-Agent: RobotDog-M20-GW",
        ]

        if sdp:
            lines.append(f"Content-Type: application/sdp")
            lines.append(f"Content-Length: {len(sdp.encode())}")
            lines.append("")
            lines.append(sdp.rstrip("\r\n"))
        else:
            lines.append("Content-Length: 0")

        raw = "\r\n".join(lines) + "\r\n"
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
        return Gb28181Status(
            running=self._running,
            registered=self._registered,
            push_active=self._push_active,
            local_sip=f"{self.cfg.local_sip_ip}:{self.cfg.local_sip_port}",
            server_sip=f"{self.cfg.server_ip}:{self.cfg.server_port}",
            device_id=self.cfg.device_id,
            push_target=self._push_target,
            last_error=self._last_error,
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
