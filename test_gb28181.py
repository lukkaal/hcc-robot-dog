"""GB/T 28181 SIP 连接测试脚本 — 逐步诊断 REGISTER 流程"""

# ====== 在这里填写 SIP 主站凭据（与 .env 一致） ======
SIP_SERVER_HOST = "42.193.245.235"
SIP_SERVER_PORT = 15692
SIP_SERVER_ID = "44010082442009000088"
SIP_DOMAIN = "4401008244"
DEVICE_ID = "440103004913250000002"
AUTH_ID = "440103004913250000002"
PASSWORD = "SntVMP_1a3c"
CHANNEL_ID = "440103004913150000002"
LOCAL_SIP_IP = "192.168.0.194"       # 本机对主站可达的 IP
LOCAL_SIP_PORT = 15060
# ======================================================

import hashlib
import re
import socket
import string
import random
import time
import sys


def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"


# ========== 工具函数（与 gb28181_client.py 一致） ==========

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


# ========== 步骤 1: UDP 可达性 ==========

def step1_udp_check():
    print(bold("\n[1/4] UDP 可达性检测"))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)
    try:
        sock.connect((SIP_SERVER_HOST, SIP_SERVER_PORT))
        sock.sendto(b"", (SIP_SERVER_HOST, SIP_SERVER_PORT))
        print(f"  {green('OK')} UDP 可达 {SIP_SERVER_HOST}:{SIP_SERVER_PORT}")
        return True
    except Exception as e:
        print(f"  {red('FAIL')} {e}")
        print(f"  排查: nc -zvu {SIP_SERVER_HOST} {SIP_SERVER_PORT}")
        return False
    finally:
        sock.close()


# ========== 步骤 2: 发送 OPTIONS 探测 ==========

def step2_options_ping():
    print(bold("\n[2/4] SIP OPTIONS 探测（无需认证）"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LOCAL_SIP_PORT))
    sock.settimeout(3)

    call_id = f"{random_hex(16)}@{LOCAL_SIP_IP}"
    from_tag = tag()
    cseq = random.randint(1000, 9999)

    msg = "\r\n".join([
        f"OPTIONS sip:{SIP_SERVER_ID}@{SIP_SERVER_HOST}:{SIP_SERVER_PORT} SIP/2.0",
        f"Via: SIP/2.0/UDP {LOCAL_SIP_IP}:{LOCAL_SIP_PORT};rport;branch={branch()}",
        f"From: <sip:{DEVICE_ID}@{SIP_DOMAIN}>;tag={from_tag}",
        f"To: <sip:{SIP_SERVER_ID}@{SIP_DOMAIN}>",
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} OPTIONS",
        "Max-Forwards: 70",
        "User-Agent: RobotDog-M20-Test",
        "Content-Length: 0",
    ]) + "\r\n"

    print(f"  → OPTIONS sip:{SIP_SERVER_HOST}:{SIP_SERVER_PORT}")
    sock.sendto(msg.encode(), (SIP_SERVER_HOST, SIP_SERVER_PORT))

    try:
        data, addr = sock.recvfrom(8192)
        raw = data.decode(errors="replace")
        first_line = raw.split("\r\n")[0]
        print(f"  ← {green(first_line)}")
        print(f"  来自: {addr[0]}:{addr[1]}")

        if "SIP/2.0" in first_line.upper():
            code = first_line.split(" ")[1] if len(first_line.split(" ")) > 1 else "?"
            if code == "200":
                print(f"  {green('OK')} 主站 SIP 服务正常响应")
            elif code == "401" or code == "403":
                print(f"  {yellow('OK')} 主站在线，OPTIONS 被拦截但说明服务可达")
            else:
                print(f"  {yellow('?')}  响应码 {code}，但至少收到了回复")
        return True, addr
    except socket.timeout:
        print(f"  {red('TIMEOUT')} OPTIONS 未收到响应")
        print(f"  可能原因: 端口不是 SIP 服务 / 防火墙过滤 / 主站不响应 OPTIONS")
        return False, None
    finally:
        sock.close()


# ========== 步骤 3: REGISTER + 401 挑战 ==========

def step3_register_auth():
    print(bold("\n[3/4] SIP REGISTER 认证流程"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LOCAL_SIP_PORT))
    sock.settimeout(5)

    call_id = f"{random_hex(16)}@{LOCAL_SIP_IP}"
    from_tag = tag()
    cseq = 1
    nonce = None
    realm = SIP_DOMAIN
    registered = False

    # 发送无认证 REGISTER
    print(f"  → REGISTER (无认证) sip:{DEVICE_ID}@{SIP_DOMAIN}")
    msg = build_register(cseq, call_id, from_tag, 3600, nonce, realm)
    sock.sendto(msg.encode(), (SIP_SERVER_HOST, SIP_SERVER_PORT))

    try:
        data, addr = sock.recvfrom(8192)
        raw = data.decode(errors="replace")
        first_line = raw.split("\r\n")[0]
        print(f"  ← {first_line}")

        if "401" in first_line or "407" in first_line:
            m = re.search(r'nonce="([^"]+)"', raw)
            if m:
                nonce = m.group(1)
                print(f"  {green('OK')} 收到 401 挑战, nonce={nonce[:16]}...")
            m = re.search(r'realm="([^"]+)"', raw)
            if m:
                realm = m.group(1)

            # 发送带认证 REGISTER
            cseq += 1
            print(f"  → REGISTER (带 MD5 Digest) sip:{DEVICE_ID}@{SIP_DOMAIN}")
            msg = build_register(cseq, call_id, from_tag, 3600, nonce, realm)
            sock.sendto(msg.encode(), (SIP_SERVER_HOST, SIP_SERVER_PORT))

            data2, _ = sock.recvfrom(8192)
            raw2 = data2.decode(errors="replace")
            first_line2 = raw2.split("\r\n")[0]
            print(f"  ← {first_line2}")

            if "200" in first_line2:
                print(f"  {green('SUCCESS')} REGISTER 200 OK — 设备注册成功！")
                registered = True
            else:
                print(f"  {red('FAIL')} 带认证 REGISTER 被拒绝")

        elif "200" in first_line:
            print(f"  {green('OK')} REGISTER 直接 200 OK（无需认证），设备已在线")
            registered = True
        else:
            print(f"  {red('FAIL')} 未预期的响应: {first_line}")

    except socket.timeout:
        print(f"  {red('TIMEOUT')} 未收到响应")
        print(f"  排查: 确认 {SIP_SERVER_HOST}:{SIP_SERVER_PORT} 是 SIP 信令端口")
    finally:
        # 如果注册成功，发一个 expires=0 的注销
        if registered:
            cseq += 1
            print(f"  → REGISTER (expires=0, 注销)")
            msg = build_register(cseq, call_id, from_tag, 0, nonce, realm)
            sock.sendto(msg.encode(), (SIP_SERVER_HOST, SIP_SERVER_PORT))
            time.sleep(0.3)
        sock.close()

    return registered


# ========== 步骤 4: 总结 ==========

def step4_status_check():
    print(bold("\n[4/4] 本地 UDP 端口状态"))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", LOCAL_SIP_PORT))
        print(f"  {green('OK')} 端口 {LOCAL_SIP_PORT}/UDP 可用")
    except OSError as e:
        print(f"  {red('FAIL')} 端口 {LOCAL_SIP_PORT} 不可用: {e}")
    finally:
        sock.close()


# ========== 辅助: 构建 REGISTER ==========

def build_register(cseq, call_id, from_tag, expires, nonce, realm):
    lines = [
        f"REGISTER sip:{DEVICE_ID}@{SIP_DOMAIN} SIP/2.0",
        f"Via: SIP/2.0/UDP {LOCAL_SIP_IP}:{LOCAL_SIP_PORT};rport;branch={branch()}",
        f"From: <sip:{DEVICE_ID}@{SIP_DOMAIN}>;tag={from_tag}",
        f"To: <sip:{DEVICE_ID}@{SIP_DOMAIN}>",
        f"Call-ID: {call_id}",
        f"CSeq: {cseq} REGISTER",
        f"Contact: <sip:{DEVICE_ID}@{LOCAL_SIP_IP}:{LOCAL_SIP_PORT}>",
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

    lines.append("Content-Length: 0")
    return "\r\n".join(lines) + "\r\n"


# ========== 主入口 ==========

def main():
    print("=" * 55)
    print(bold(" GB/T 28181 SIP 连接测试"))
    print("=" * 55)
    print(f"  主站: {SIP_SERVER_HOST}:{SIP_SERVER_PORT}")
    print(f"  设备: {DEVICE_ID}")
    print(f"  本机: {LOCAL_SIP_IP}:{LOCAL_SIP_PORT}")
    print(f"  域:   {SIP_DOMAIN}")

    results = {}

    # Step 1
    results["udp"] = step1_udp_check()
    if not results["udp"]:
        print(red("\nUDP 不通，后续测试无意义。请检查网络/防火墙。"))
        sys.exit(1)

    # Step 2
    ok, addr = step2_options_ping()
    results["options"] = ok

    # Step 3
    if sys.argv[-1] == "--skip-register":
        print(yellow("\n[3/4] 跳过 REGISTER（--skip-register）"))
    else:
        results["register"] = step3_register_auth()

    # Step 4
    step4_status_check()

    # 汇总
    print("\n" + "=" * 55)
    print(bold(" 测试结果汇总"))
    print("=" * 55)
    print(f"  UDP 可达:     {'通过' if results.get('udp') else '失败'}")
    print(f"  OPTIONS 响应: {'通过' if results.get('options') else '无响应（不一定失败）'}")
    print(f"  REGISTER:     {'通过 — 设备可上线' if results.get('register') else '未测试或失败'}")
    print()
    if results.get("register"):
        print(green("  SIP 连接正常，可以启动完整网关进行推流测试。"))
        print(f"  启动命令: uvicorn app.main:app --host 0.0.0.0 --port 8000")
    else:
        print(yellow("  基础连接已确认，但 REGISTER 未通过。请核查:"))
        print(f"    - SIP username/device_id 是否正确")
        print(f"    - auth_id / password 是否匹配主站分配的值")
        print(f"    - 主站是否已通过 /devMgr/deviceApply 创建了该设备")
    print("=" * 55)


if __name__ == "__main__":
    main()
