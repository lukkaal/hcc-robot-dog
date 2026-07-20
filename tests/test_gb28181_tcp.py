"""GB/T 28181 SIP REGISTER — TCP 标准国标注册测试"""

import os
import sys

# ====== 从 .env 加载参数 ======
ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

SIP_SERVER_HOST = os.environ.get("GB28181_SIP_SERVER_HOST", "14.116.205.39")
SIP_SERVER_PORT = int(os.environ.get("GB28181_SIP_SERVER_PORT", "5788"))
SIP_SERVER_ID = os.environ.get("GB28181_SIP_SERVER_ID", "44019000002000000001")
SIP_DOMAIN = os.environ.get("GB28181_SIP_DOMAIN", "4401900000")
DEVICE_ID = os.environ.get("GB28181_SIP_USERNAME", "44010600491325000010")
AUTH_ID = os.environ.get("GB28181_SIP_AUTH_ID", "44010600491325000010")
PASSWORD = os.environ.get("GB28181_SIP_PASSWORD", "123456")
LOCAL_SIP_IP = os.environ.get("GB28181_LOCAL_SIP_IP", "192.168.0.200")
LOCAL_SIP_PORT = int(os.environ.get("GB28181_LOCAL_SIP_PORT", "15060"))
# =============================

import hashlib
import re
import socket
import string
import random
import sys


def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"


def random_hex(n=16):
    return "".join(random.choice(string.hexdigits) for _ in range(n))


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def compute_digest(username, realm, password, method, uri, nonce):
    ha1 = md5(f"{username}:{realm}:{password}")
    ha2 = md5(f"{method}:{uri}")
    return md5(f"{ha1}:{nonce}:{ha2}")


def send_sip(sock, msg: str):
    sock.sendall(msg.encode())


def recv_sip(sock, timeout: float = 5.0) -> str:
    """根据 Content-Length 读取完整 SIP 响应"""
    sock.settimeout(timeout)
    buf = b""

    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk

        raw = buf.decode(errors="replace")
        if "\r\n\r\n" in raw:
            m = re.search(r"Content-Length:\s*(\d+)", raw, re.IGNORECASE)
            cl = int(m.group(1)) if m else 0
            header_end = raw.index("\r\n\r\n") + 4
            total_needed = header_end + cl
            if len(buf) >= total_needed:
                return buf[:total_needed].decode(errors="replace")

    return buf.decode(errors="replace")


def build_register_msg(device_id, domain, local_ip, local_port,
                        call_id, from_tag, cseq, expires,
                        nonce=None, realm=None):
    """
    构建 REGISTER 请求，格式严格对齐 GB/T 28181 SIP over TCP 规范。
    """
    branch = "z9hG4bK" + random_hex(16)
    lines = [
        f"REGISTER sip:{device_id}@{domain} SIP/2.0",
        f"Via: SIP/2.0/TCP {local_ip}:{local_port};rport;branch={branch}",
        f"From: <sip:{device_id}@{domain}>;tag={from_tag}",
        f"To: <sip:{device_id}@{domain}>",
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} REGISTER",
        f"Contact: <sip:{device_id}@{local_ip}:{local_port};transport=TCP>",
        "Max-Forwards: 70",
        f"User-Agent: RobotDog-M20-GW",
        f"Expires: {expires}",
    ]

    if nonce:
        realm = realm or domain
        uri = f"sip:{device_id}@{domain}"
        username = AUTH_ID or device_id
        response = compute_digest(username, realm, PASSWORD, "REGISTER", uri, nonce)
        lines.append(
            f'Authorization: Digest username="{username}", realm="{realm}", '
            f'nonce="{nonce}", uri="{uri}", response="{response}", algorithm=MD5'
        )

    # 空 body，以 \r\n\r\n 结尾
    body = ""
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body


def register():
    """标准国标注册流程：TCP 连接 → 无认证 REGISTER → 401 → 带 Digest REGISTER → 200 OK"""
    print("=" * 55)
    print(bold(" GB/T 28181 标准注册"))
    print("=" * 55)
    print(f"  平台: {SIP_SERVER_HOST}:{SIP_SERVER_PORT}")
    print(f"  设备: {DEVICE_ID}")
    print(f"  域:   {SIP_DOMAIN}")

    # --- 建立 TCP 连接 ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)

    print(bold("\n[1] TCP 连接"))
    try:
        sock.connect((SIP_SERVER_HOST, SIP_SERVER_PORT))
        print(f"  {green('OK')} 已连接 {SIP_SERVER_HOST}:{SIP_SERVER_PORT}")
    except socket.timeout:
        print(f"  {red('TIMEOUT')} 连接超时")
        return False
    except ConnectionRefusedError:
        print(f"  {red('REFUSED')} 端口未监听")
        return False
    except Exception as e:
        print(f"  {red('FAIL')} {e}")
        return False

    # --- 会话标识 ---
    call_id = f"{random_hex(16)}@{LOCAL_SIP_IP}"
    from_tag = random_hex(8)

    try:
        # --- 第一次 REGISTER（无认证）---
        print(bold("\n[2] 发送 REGISTER（无认证）"))
        msg = build_register_msg(
            DEVICE_ID, SIP_DOMAIN, LOCAL_SIP_IP, LOCAL_SIP_PORT,
            call_id, from_tag, cseq=1, expires=3600,
        )
        print(f"  → {msg.split(chr(13)+chr(10))[0]}")
        send_sip(sock, msg)

        raw = recv_sip(sock, timeout=5.0)
        if not raw:
            print(f"  {red('TIMEOUT')} 无响应")
            return False

        first_line = raw.split("\r\n")[0]
        print(f"  ← {first_line}")

        if "200" in first_line:
            print(f"  {green('SUCCESS')} 无需认证，已注册！")
            return True

        if "401" not in first_line and "407" not in first_line:
            print(f"  {red('FAIL')} 非预期的响应码")
            return False

        # --- 提取认证参数 ---
        m_nonce = re.search(r'nonce="([^"]+)"', raw)
        m_realm = re.search(r'realm="([^"]+)"', raw)

        if not m_nonce:
            print(f"  {red('FAIL')} 401 响应中未找到 nonce")
            return False

        nonce = m_nonce.group(1)
        realm = m_realm.group(1) if m_realm else SIP_DOMAIN
        print(f"  {green('OK')} 提取 nonce={nonce[:20]}..., realm={realm}")

        # --- 第二次 REGISTER（带 Digest 认证）---
        print(bold("\n[3] 发送 REGISTER（MD5 Digest 认证）"))
        msg = build_register_msg(
            DEVICE_ID, SIP_DOMAIN, LOCAL_SIP_IP, LOCAL_SIP_PORT,
            call_id, from_tag, cseq=2, expires=3600,
            nonce=nonce, realm=realm,
        )
        print(f"  → {msg.split(chr(13)+chr(10))[0]}")
        send_sip(sock, msg)

        raw2 = recv_sip(sock, timeout=5.0)
        if not raw2:
            print(f"  {red('TIMEOUT')} 无响应")
            return False

        first_line2 = raw2.split("\r\n")[0]
        print(f"  ← {first_line2}")

        if "200" in first_line2:
            print(f"\n  {green('SUCCESS')} 设备注册成功！")
            return True
        else:
            print(f"  {red('FAIL')} 认证注册被拒绝")
            return False

    except Exception as e:
        print(f"  {red('异常')} {e}")
        return False
    finally:
        sock.close()


if __name__ == "__main__":
    ok = register()
    sys.exit(0 if ok else 1)
