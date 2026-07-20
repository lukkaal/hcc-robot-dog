"""GB/T 28181 SIP REGISTER — UDP 标准国标注册（格式对齐 WVP-Pro）"""

import os
import sys

# ====== 从 .env 加载参数 ======
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
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
DEVICE_DOMAIN = DEVICE_ID[:10]
# =============================

import hashlib
import re
import socket
import string
import random
import uuid
import sys


def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"


def random_hex(n=16):
    return "".join(random.choice(string.hexdigits) for _ in range(n))


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def compute_digest(username, realm, password, method, uri, nonce,
                   qop=None, cnonce=None, nc=None):
    """支持 qop=auth 的 MD5 Digest 计算"""
    ha1 = md5(f"{username}:{realm}:{password}")
    ha2 = md5(f"{method}:{uri}")
    if qop == "auth":
        return md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    else:
        return md5(f"{ha1}:{nonce}:{ha2}")


def build_register_msg(device_id, device_domain, server_id, server_host, server_port,
                        local_ip, local_port, call_id, from_tag, cseq, expires,
                        nonce=None, realm=None, qop=None):
    """
    格式严格对齐 WVP-Pro 注册报文:
      REGISTER sip:平台ID@平台IP:平台端口 SIP/2.0
      From/To: sip:设备ID@设备域
      Contact: sip:设备ID@本机IP:本机端口
    """
    branch = "z9hG4bK" + random_hex(16)
    request_uri = f"sip:{server_id}@{server_host}:{server_port}"

    lines = [
        f"REGISTER {request_uri} SIP/2.0",
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} REGISTER",
        f"From: <sip:{device_id}@{device_domain}>;tag={from_tag}",
        f"To: <sip:{device_id}@{device_domain}>",
        f"Via: SIP/2.0/UDP {local_ip}:{local_port};branch={branch};rport",
        "Max-Forwards: 70",
        f"Contact: <sip:{device_id}@{local_ip}:{local_port}>",
        f"Expires: {expires}",
        "User-Agent: RobotDog-M20-GW",
    ]

    if nonce:
        realm = realm or SIP_DOMAIN
        cnonce = str(uuid.uuid4())
        nc = "00000001"
        response = compute_digest(
            AUTH_ID or device_id, realm, PASSWORD, "REGISTER", request_uri, nonce,
            qop=qop, cnonce=cnonce, nc=nc,
        )
        auth = (
            f'Authorization: Digest username="{AUTH_ID or device_id}",'
            f'realm="{realm}",'
            f'nonce="{nonce}",'
            f'uri="{request_uri}",'
            f'response="{response}",'
            f'algorithm=MD5'
        )
        if qop == "auth":
            auth += f',qop={qop},cnonce="{cnonce}",nc={nc}'
        lines.append(auth)

    body = ""
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n\r\n" + body


def register():
    print("=" * 55)
    print(bold(" GB/T 28181 UDP 标准注册"))
    print("=" * 55)
    print(f"  平台: {SIP_SERVER_HOST}:{SIP_SERVER_PORT}")
    print(f"  平台ID: {SIP_SERVER_ID}")
    print(f"  设备: {DEVICE_ID}")
    print(f"  设备域: {DEVICE_DOMAIN}")
    print(f"  平台域(realm): {SIP_DOMAIN}")
    print(f"  本机: {LOCAL_SIP_IP}:{LOCAL_SIP_PORT}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LOCAL_SIP_PORT))
    sock.settimeout(5)

    call_id = f"{random_hex(32)}@0:0:0:0:0:0:0:0"
    from_tag = random_hex(16)

    try:
        # --- 第一次 REGISTER（无认证）---
        print(bold("\n[1] 发送 REGISTER（无认证）"))
        msg = build_register_msg(
            DEVICE_ID, DEVICE_DOMAIN,
            SIP_SERVER_ID, SIP_SERVER_HOST, SIP_SERVER_PORT,
            LOCAL_SIP_IP, LOCAL_SIP_PORT,
            call_id, from_tag, cseq=91374, expires=300,
        )
        print(f"  → {msg.split(chr(13)+chr(10))[0]}")
        sock.sendto(msg.encode(), (SIP_SERVER_HOST, SIP_SERVER_PORT))

        data, addr = sock.recvfrom(8192)
        raw = data.decode(errors="replace")
        first_line = raw.split("\r\n")[0]
        print(f"  ← {first_line}")
        print(f"  来自: {addr[0]}:{addr[1]}")

        if "200" in first_line:
            print(f"  {green('SUCCESS')} 无需认证，已注册！")
            return True

        if "401" not in first_line and "407" not in first_line:
            print(f"  {red('FAIL')} 非预期的响应码")
            print(f"  raw[:300]: {raw[:300]}")
            return False

        # --- 提取认证参数 ---
        m_nonce = re.search(r'nonce="([^"]+)"', raw)
        m_realm = re.search(r'realm="([^"]+)"', raw)
        m_qop = re.search(r'qop="([^"]+)"', raw)

        if not m_nonce:
            print(f"  {red('FAIL')} 401 中无 nonce")
            return False

        nonce = m_nonce.group(1)
        realm = m_realm.group(1) if m_realm else SIP_DOMAIN
        qop = m_qop.group(1) if m_qop else None
        print(f"  {green('OK')} nonce={nonce[:20]}..., realm={realm}, qop={qop}")

        # --- 第二次 REGISTER（带 Digest 认证）---
        print(bold("\n[2] 发送 REGISTER（MD5 Digest 认证）"))
        msg = build_register_msg(
            DEVICE_ID, DEVICE_DOMAIN,
            SIP_SERVER_ID, SIP_SERVER_HOST, SIP_SERVER_PORT,
            LOCAL_SIP_IP, LOCAL_SIP_PORT,
            call_id, from_tag, cseq=91375, expires=300,
            nonce=nonce, realm=realm, qop=qop,
        )
        print(f"  → {msg.split(chr(13)+chr(10))[0]}")
        sock.sendto(msg.encode(), (SIP_SERVER_HOST, SIP_SERVER_PORT))

        data2, _ = sock.recvfrom(8192)
        raw2 = data2.decode(errors="replace")
        first_line2 = raw2.split("\r\n")[0]
        print(f"  ← {first_line2}")

        if "200" in first_line2:
            print(f"\n  {green('SUCCESS')} 设备注册成功！")
            return True
        else:
            print(f"  {red('FAIL')} 认证注册被拒绝")
            return False

    except socket.timeout:
        print(f"  {red('TIMEOUT')} 未收到响应")
        return False
    except Exception as e:
        print(f"  {red('异常')} {e}")
        return False
    finally:
        sock.close()


if __name__ == "__main__":
    ok = register()
    sys.exit(0 if ok else 1)
