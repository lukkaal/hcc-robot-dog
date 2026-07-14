"""GB/T 28181 SIP TCP 连接测试 — 测试主站是否走 TCP 信令"""

# ====== SIP 主站凭据 ======
SIP_SERVER_HOST = "1.12.248.179"
SIP_SERVER_PORT = 30000
SIP_SERVER_ID = "44019000002000000001"
SIP_DOMAIN = "4401900000"
DEVICE_ID = "440103004913250000001"
AUTH_ID = "44010400491325000001"
PASSWORD = "admin123"
LOCAL_SIP_IP = "192.168.0.194"
LOCAL_SIP_PORT = 15060
# ===========================

import hashlib
import re
import socket
import string
import random
import time
import sys
import struct


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

def branch():
    return "z9hG4bK" + random_hex(16)

def tag():
    return random_hex(8)


def send_tcp_sip(sock, msg: str):
    """TCP 方式发送 SIP 消息（SIP over TCP"""
    data = msg.encode()
    sock.sendall(data)


def recv_tcp_sip(sock, timeout: float = 5.0) -> str:
    """TCP 方式接收 SIP 响应（根据 Content-Length 读取完整消息）"""
    sock.settimeout(timeout)
    buf = b""

    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk

        raw = buf.decode(errors="replace")
        if "\r\n\r\n" in raw:
            # 查 Content-Length
            m = re.search(r"Content-Length:\s*(\d+)", raw, re.IGNORECASE)
            cl = int(m.group(1)) if m else 0
            header_end = raw.index("\r\n\r\n") + 4
            total_needed = header_end + cl
            if len(buf) >= total_needed:
                return buf[:total_needed].decode(errors="replace")

    return buf.decode(errors="replace")


def build_register(cseq, call_id, from_tag, expires, nonce, realm):
    lines = [
        f"REGISTER sip:{DEVICE_ID}@{SIP_DOMAIN} SIP/2.0",
        f"Via: SIP/2.0/TCP {LOCAL_SIP_IP}:{LOCAL_SIP_PORT};rport;branch={branch()}",
        f"From: <sip:{DEVICE_ID}@{SIP_DOMAIN}>;tag={from_tag}",
        f"To: <sip:{DEVICE_ID}@{SIP_DOMAIN}>",
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} REGISTER",
        f"Contact: <sip:{DEVICE_ID}@{LOCAL_SIP_IP}:{LOCAL_SIP_PORT};transport=TCP>",
        "Max-Forwards: 70",
        "User-Agent: RobotDog-M20-Test",
        f"Expires: {expires}",
    ]

    if nonce:
        uri = f"sip:{SIP_DOMAIN}"
        auth_user = AUTH_ID or DEVICE_ID
        resp = compute_digest(auth_user, realm, PASSWORD, "REGISTER", uri, nonce)
        lines.append(
            f'Authorization: Digest username="{auth_user}", realm="{realm}",'
            f' nonce="{nonce}", uri="{uri}", response="{resp}", algorithm=MD5'
        )

    body = ""
    lines.append(f"Content-Length: {len(body.encode())}")
    return "\r\n".join(lines) + "\r\n" + body


# ========== 步骤 1: TCP 连通性 ==========

def step1_tcp_check():
    print(bold("\n[1/3] TCP 连通性检测"))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((SIP_SERVER_HOST, SIP_SERVER_PORT))
        print(f"  {green('OK')} TCP 连接 {SIP_SERVER_HOST}:{SIP_SERVER_PORT} 成功")
        sock.close()
        return True
    except socket.timeout:
        print(f"  {red('TIMEOUT')} TCP 连接超时")
        return False
    except ConnectionRefusedError:
        print(f"  {red('REFUSED')} TCP 连接被拒绝（端口未监听）")
        return False
    except Exception as e:
        print(f"  {red('FAIL')} {e}")
        return False


# ========== 步骤 2: OPTIONS over TCP ==========

def step2_options_tcp():
    print(bold("\n[2/3] SIP OPTIONS over TCP"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((SIP_SERVER_HOST, SIP_SERVER_PORT))
    except Exception as e:
        print(f"  {red('FAIL')} 无法建立 TCP 连接: {e}")
        return False

    call_id = f"{random_hex(16)}@{LOCAL_SIP_IP}"
    from_tag = tag()
    cseq = random.randint(1000, 9999)

    msg = "\r\n".join([
        f"OPTIONS sip:{DEVICE_ID}@{SIP_DOMAIN} SIP/2.0",
        f"Via: SIP/2.0/TCP {LOCAL_SIP_IP}:{LOCAL_SIP_PORT};rport;branch={branch()}",
        f"From: <sip:{DEVICE_ID}@{SIP_DOMAIN}>;tag={from_tag}",
        f"To: <sip:{SIP_SERVER_ID}@{SIP_DOMAIN}>",
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} OPTIONS",
        "Max-Forwards: 70",
        "User-Agent: RobotDog-M20-Test",
        "Content-Length: 0",
    ]) + "\r\n"

    print(f"  → OPTIONS sip:{DEVICE_ID}@{SIP_DOMAIN}")
    send_tcp_sip(sock, msg)

    try:
        raw = recv_tcp_sip(sock, timeout=5.0)
        if raw:
            first_line = raw.split("\r\n")[0]
            print(f"  ← {green(first_line)}")
            return True
        else:
            print(f"  {red('TIMEOUT')} 无 SIP 响应")
            return False
    except socket.timeout:
        print(f"  {red('TIMEOUT')} 无 SIP 响应")
        return False
    except Exception as e:
        print(f"  {red('FAIL')} {e}")
        return False
    finally:
        sock.close()


# ========== 步骤 3: REGISTER over TCP ==========

def step3_register_tcp():
    print(bold("\n[3/3] SIP REGISTER over TCP"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((SIP_SERVER_HOST, SIP_SERVER_PORT))
    except Exception as e:
        print(f"  {red('FAIL')} 无法建立 TCP 连接: {e}")
        return False

    call_id = f"{random_hex(16)}@{LOCAL_SIP_IP}"
    from_tag = tag()
    cseq = 1
    nonce = None
    realm = SIP_DOMAIN
    registered = False

    try:
        # 无认证 REGISTER
        print(f"  → REGISTER (无认证)")
        msg = build_register(cseq, call_id, from_tag, 3600, nonce, realm)
        send_tcp_sip(sock, msg)

        raw = recv_tcp_sip(sock, timeout=5.0)
        if not raw:
            print(f"  {red('TIMEOUT')} 未收到响应")
            return False

        first_line = raw.split("\r\n")[0]
        print(f"  ← {first_line}")

        if "SIP/2.0" not in first_line:
            print(f"  {red('FAIL')} 返回的不是 SIP 协议响应")
            print(f"  raw: {raw[:200]}")
            return False

        if "401" in first_line or "407" in first_line:
            m = re.search(r'nonce="([^"]+)"', raw)
            if m:
                nonce = m.group(1)
                print(f"  {green('OK')} 收到 401 挑战, nonce={nonce[:16]}...")
            m = re.search(r'realm="([^"]+)"', raw)
            if m:
                realm = m.group(1)

            cseq += 1
            print(f"  → REGISTER (带 MD5 Digest)")
            msg = build_register(cseq, call_id, from_tag, 3600, nonce, realm)
            send_tcp_sip(sock, msg)

            raw2 = recv_tcp_sip(sock, timeout=5.0)
            if not raw2:
                print(f"  {red('TIMEOUT')} 未收到认证后响应")
                return False

            first_line2 = raw2.split("\r\n")[0]
            print(f"  ← {first_line2}")

            if "200" in first_line2:
                print(f"  {green('SUCCESS')} 设备注册成功！")
                registered = True
            else:
                print(f"  {red('FAIL')} 带认证 REGISTER 被拒绝")

        elif "200" in first_line:
            print(f"  {green('OK')} 无需认证直接 200 OK")
            registered = True
        else:
            print(f"  {red('FAIL')} 未预期的响应码")

        # 注销
        if registered:
            cseq += 1
            print(f"  → REGISTER (expires=0, 注销)")
            msg = build_register(cseq, call_id, from_tag, 0, nonce, realm)
            send_tcp_sip(sock, msg)
            try:
                raw3 = recv_tcp_sip(sock, timeout=3.0)
                print(f"  ← {raw3.split(chr(13)+chr(10))[0]}")
            except Exception:
                pass

    except Exception as e:
        print(f"  {red('异常')} {e}")
        return False
    finally:
        sock.close()

    return registered


# ========== 主入口 ==========

def main():
    print("=" * 55)
    print(bold(" GB/T 28181 SIP TCP 连接测试"))
    print("=" * 55)
    print(f"  主站: {SIP_SERVER_HOST}:{SIP_SERVER_PORT} (TCP)")
    print(f"  设备: {DEVICE_ID}")
    print(f"  域:   {SIP_DOMAIN}")

    results = {}

    results["tcp"] = step1_tcp_check()
    if not results["tcp"]:
        print(red("\nTCP 不通，端口未监听或被防火墙拦截。"))
        print("对方大概率用的是 UDP，不是 TCP。回到 UDP 路径排查端口号。")
        sys.exit(1)

    results["options"] = step2_options_tcp()
    results["register"] = step3_register_tcp()

    print("\n" + "=" * 55)
    print(bold(" 测试结果汇总"))
    print("=" * 55)
    print(f"  TCP 连通:     {'通过' if results.get('tcp') else '失败'}")
    print(f"  OPTIONS TCP:  {'通过（SIP 服务响应）' if results.get('options') else '无响应'}")
    print(f"  REGISTER TCP: {'通过 — 可以注册' if results.get('register') else '失败/未测试'}")

    if results.get("register"):
        print(green("\n  对方 SIP 信令走 TCP！需要把 gb28181_client.py 改为 SOCK_STREAM。"))
    elif results.get("options"):
        print(yellow("\n  OPTIONS 有响应但 REGISTER 失败，检查认证参数。"))
    elif results.get("tcp"):
        print(yellow("\n  TCP 能连但 SIP 无响应 — 对方大概率用 UDP 信令。"))
        print("  回到 UDP 路径排查，重点确认端口号是否正确。")

    print("=" * 55)


if __name__ == "__main__":
    main()
