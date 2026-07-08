"""Docker 容器管理：ZLMediaKit + WVP-PRO"""

import subprocess
import time
import os
import sys

DOCKER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docker")
CONTAINERS = ["dog-redis", "dog-zlmediakit", "dog-wvp"]


def _is_docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def _compose(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", os.path.join(DOCKER_DIR, "docker-compose.yml")]
        + list(args),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _container_running(name: str) -> bool:
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def _container_exists(name: str) -> bool:
    r = subprocess.run(
        ["docker", "inspect", name], capture_output=True, timeout=5
    )
    return r.returncode == 0


def ensure_containers():
    """确保 ZLMediaKit + WVP-PRO 容器已启动；首次运行会自动创建"""

    if not _is_docker_available():
        print("[Docker] Docker 不可用，跳过 GB28181 视频推流服务")
        return False

    all_running = all(_container_running(c) for c in CONTAINERS)

    if all_running:
        print("[Docker] GB28181 容器已运行")
        return True

    print("[Docker] 正在启动 GB28181 视频推流容器 ...")

    if not _container_exists("dog-redis"):
        print("[Docker] 首次启动，拉取镜像并创建容器（可能需要几分钟）...")

    r = _compose("up", "-d")
    if r.returncode != 0:
        print(f"[Docker] 启动失败:\n{r.stderr}")
        return False

    # 等待 ZLMediaKit HTTP API 就绪
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(
                "http://127.0.0.1:9092/index/api/getServerConfig?secret=my_secret_key_2025",
                timeout=2,
            )
            break
        except Exception:
            time.sleep(1)

    print("[Docker] GB28181 容器启动完成")
    _print_status()
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

    for _ in range(10):
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:9092/index/api/addStreamProxy",
                data=data.encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=5)
            print(f"[ZLM] RTSP 拉流代理已添加: {rtsp_url} → proxy/robot-dog")
            print(f"[ZLM] 响应: {resp.read().decode()}")
            return True
        except Exception as e:
            print(f"[ZLM] 添加拉流代理重试: {e}")
            time.sleep(2)
    return False


def stream_logs(lines: int = 20):
    """打印容器最近日志"""
    for name in ["dog-zlmediakit", "dog-wvp"]:
        print(f"\n--- {name} 日志 (最近 {lines} 行) ---")
        r = subprocess.run(
            ["docker", "logs", "--tail", str(lines), name],
            capture_output=True, text=True, timeout=10,
        )
        print(r.stdout or r.stderr)


def _print_status():
    for name in CONTAINERS:
        status = "运行中" if _container_running(name) else "未运行"
        print(f"  {name}: {status}")


def stop_containers():
    """停止所有 GB28181 容器"""
    if not _is_docker_available():
        return
    print("[Docker] 正在停止 GB28181 容器 ...")
    _compose("down")
    print("[Docker] 容器已停止")
