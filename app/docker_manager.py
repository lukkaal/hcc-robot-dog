"""Docker 容器管理：ZLMediaKit（纯 docker CLI，不依赖 compose 插件）

GB28181 信令由 app/gb28181_client.py 处理，不再需要 WVP-PRO / Redis。"""

import subprocess
import time
import os

DOCKER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docker")
NETWORK = "dog-net"
CONTAINER_NAME = "dog-zlmediakit"
IMAGE = "zlmediakit/zlmediakit:master"


def _log(msg: str):
    print(f"[Docker] {msg}")


def _run(*args, timeout: int = 120) -> subprocess.CompletedProcess:
    cmd = list(args)
    _log(f"  >> {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _is_docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def _container_running(name: str) -> bool:
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True, text=True, timeout=5,
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def _container_exists(name: str) -> bool:
    r = subprocess.run(["docker", "inspect", name], capture_output=True, timeout=5)
    return r.returncode == 0


def _network_exists(name: str) -> bool:
    r = subprocess.run(
        ["docker", "network", "inspect", name], capture_output=True, timeout=5
    )
    return r.returncode == 0


def _ensure_network():
    """创建桥接网络"""
    if _network_exists(NETWORK):
        return True
    _log(f"创建 Docker 网络: {NETWORK}")
    r = _run("docker", "network", "create", NETWORK)
    return r.returncode == 0


def ensure_containers():
    """确保 ZLMediaKit 容器已启动；首次运行会自动创建"""

    if not _is_docker_available():
        _log("Docker 不可用，跳过 GB28181 视频推流服务")
        return False

    if _container_running(CONTAINER_NAME):
        _log("ZLMediaKit 容器已运行")
        return True

    _log("正在启动 ZLMediaKit 流媒体容器 ...")

    if not _ensure_network():
        return False

    if _container_exists(CONTAINER_NAME):
        _log(f"移除旧容器: {CONTAINER_NAME}")
        _run("docker", "rm", "-f", CONTAINER_NAME)

    # 拉取镜像（仅本地没有时下载）
    r = subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0:
        _log(f"本地无镜像，拉取: {IMAGE}")
        _run("docker", "pull", IMAGE, timeout=300)

    config_path = os.path.join(DOCKER_DIR, "zlm-config", "config.ini")

    cmd = [
        "docker", "run", "-d",
        "--name", CONTAINER_NAME,
        "--network", NETWORK,
        "--restart", "unless-stopped",
        "-p", "9092:9092",
        "-p", "8554:8554",
        "-p", "1935:1935",
        "-p", "30000-30500:30000-30500/tcp",
        "-p", "30000-30500:30000-30500/udp",
        "-v", f"{config_path}:/opt/media/conf/config.ini",
        IMAGE,
    ]

    _log(f"启动容器: {CONTAINER_NAME}")
    r = _run(*cmd)
    if r.returncode != 0:
        _log(f"容器启动失败: {r.stderr}")
        return False

    _log(f"容器 {CONTAINER_NAME} 启动成功")

    # 等待 ZLMediaKit HTTP API 就绪
    _log("等待 ZLMediaKit HTTP API 就绪 ...")
    import urllib.request
    for i in range(30):
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:9092/index/api/getServerConfig?secret=my_secret_key_2025",
                timeout=2,
            )
            _log(f"ZLMediaKit API 就绪")
            break
        except Exception:
            if i % 5 == 0:
                _log(f"  等待中... ({i}s)")
            time.sleep(1)
    else:
        _log("警告: ZLMediaKit API 未能在 30s 内就绪")

    _log("ZLMediaKit 容器启动完成")
    return True


def add_rtsp_proxy():
    """向 ZLMediaKit 添加机器狗 RTSP 拉流代理"""
    import urllib.request

    rtsp_url = os.environ.get("ROBOT_RTSP_URL", "rtsp://10.21.31.103:8554/video1")
    data = (
        '{"secret":"my_secret_key_2025","vhost":"__defaultVhost__",'
        '"app":"proxy","stream":"robot-dog",'
        f'"url":"{rtsp_url}",'
        '"enable_rtsp":1,"enable_rtmp":1,"enable_hls":0,"enable_mp4":0,'
        '"add_mute_audio":1,"retry_count":-1}'
    )

    _log(f"添加 RTSP 拉流代理: {rtsp_url}")
    for i in range(10):
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:9092/index/api/addStreamProxy",
                data=data.encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=5)
            _log(f"RTSP 拉流代理已添加: {rtsp_url} → proxy/robot-dog")
            _log(f"ZLM 响应: {resp.read().decode()}")
            return True
        except Exception as e:
            _log(f"添加拉流代理重试 ({i+1}/10): {e}")
            time.sleep(2)
    return False


def stream_logs(lines: int = 20):
    """打印 ZLMediaKit 容器最近日志"""
    print(f"\n--- {CONTAINER_NAME} 日志 (最近 {lines} 行) ---")
    r = subprocess.run(
        ["docker", "logs", "--tail", str(lines), CONTAINER_NAME],
        capture_output=True, text=True, timeout=10,
    )
    print(r.stdout or r.stderr)


def stop_containers():
    """停止并删除 ZLMediaKit 容器"""
    if not _is_docker_available():
        return

    _log("正在停止 ZLMediaKit 容器 ...")
    if _container_exists(CONTAINER_NAME):
        _run("docker", "stop", "-t", "5", CONTAINER_NAME)
        _run("docker", "rm", "-f", CONTAINER_NAME)

    if _network_exists(NETWORK):
        _run("docker", "network", "rm", NETWORK)

    _log("容器已停止")
