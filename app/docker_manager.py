"""Docker 容器管理：ZLMediaKit + WVP-PRO（纯 docker CLI，不依赖 compose 插件）"""

import subprocess
import time
import os

DOCKER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docker")
NETWORK = "dog-net"

CONTAINERS = [
    {
        "name": "dog-redis",
        "image": "redis:7-alpine",
        "aliases": ["redis"],
        "ports": ["6379:6379"],
    },
    {
        "name": "dog-zlmediakit",
        "image": "zlmediakit/zlmediakit:master",
        "aliases": ["zlmediakit"],
        "ports": [
            "9092:9092",
            "8554:8554",
            "1935:1935",
            "30000-30500:30000-30500/tcp",
            "30000-30500:30000-30500/udp",
        ],
        "volumes": [
            f"{os.path.join(DOCKER_DIR, 'zlm-config', 'config.ini')}:/opt/media/conf/config.ini",
        ],
    },
    {
        "name": "dog-wvp",
        "image": "108360/wvp-pro:latest",
        "aliases": [],
        "ports": ["18080:18080", "15060:15060/udp"],
        "volumes": [
            f"{os.path.join(DOCKER_DIR, 'wvp-config', 'application.yml')}:/opt/wvp/config/application.yml",
        ],
        "env": {"SIP_IP": os.environ.get("SIP_IP", "192.168.0.194")},
    },
]


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
    """创建 dog-net 桥接网络，使容器间可通过别名互相访问"""
    if _network_exists(NETWORK):
        _log(f"网络 {NETWORK} 已存在")
        return True

    _log(f"创建 Docker 网络: {NETWORK}")
    r = _run("docker", "network", "create", NETWORK)
    if r.returncode != 0:
        _log(f"创建网络失败: {r.stderr}")
        return False
    _log(f"网络 {NETWORK} 创建成功")
    return True


def _pull_image(image: str):
    """拉取镜像，失败不阻塞"""
    _log(f"拉取镜像: {image}")
    r = _run("docker", "pull", image, timeout=300)
    if r.returncode != 0:
        _log(f"拉取 {image} 失败（将继续尝试运行）: {r.stderr.strip()}")
    else:
        _log(f"镜像 {image} 拉取完成")


def _start_container(cfg: dict) -> bool:
    """启动单个容器；已存在则跳过，已运行则直接返回"""
    name = cfg["name"]

    if _container_running(name):
        _log(f"容器 {name} 已在运行，跳过")
        return True

    if _container_exists(name):
        _log(f"容器 {name} 已存在但未运行，移除后重建...")
        _run("docker", "rm", "-f", name)

    # 拉镜像（仅当本地没有时才会真正下载）
    _pull_image(cfg["image"])

    # 构建 docker run 命令
    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "--network", NETWORK,
        "--restart", "unless-stopped",
    ]

    # 网络别名（用于容器间按服务名互访，如 wvp 通过 "redis" 访问 redis）
    for alias in cfg.get("aliases", []):
        cmd += ["--network-alias", alias]

    # 端口映射
    for port in cfg.get("ports", []):
        cmd += ["-p", port]

    # 卷挂载
    for vol in cfg.get("volumes", []):
        cmd += ["-v", vol]

    # 环境变量
    for k, v in cfg.get("env", {}).items():
        cmd += ["-e", f"{k}={v}"]

    cmd.append(cfg["image"])

    _log(f"启动容器: {name}")
    r = _run(*cmd)
    if r.returncode != 0:
        _log(f"容器 {name} 启动失败: {r.stderr}")
        return False

    _log(f"容器 {name} 启动成功 ({r.stdout.strip()})")
    return True


def ensure_containers():
    """确保 ZLMediaKit + WVP-PRO 容器已启动；首次运行会自动创建"""

    if not _is_docker_available():
        _log("Docker 不可用，跳过 GB28181 视频推流服务")
        return False

    # 检查是否全部运行中
    all_running = all(_container_running(c["name"]) for c in CONTAINERS)
    if all_running:
        _log("GB28181 容器均已运行")
        return True

    _log("正在启动 GB28181 视频推流容器 ...")

    # 1. 创建共享网络
    if not _ensure_network():
        return False

    # 2. 依次启动容器
    for cfg in CONTAINERS:
        if not _start_container(cfg):
            _log(f"启动失败，终止后续容器")
            return False
        time.sleep(1)  # 给容器一点喘息时间

    # 3. 等待 ZLMediaKit HTTP API 就绪
    _log("等待 ZLMediaKit HTTP API 就绪 ...")
    import urllib.request
    for i in range(30):
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:9092/index/api/getServerConfig?secret=my_secret_key_2025",
                timeout=2,
            )
            _log("ZLMediaKit API 就绪")
            break
        except Exception:
            if i % 5 == 0:
                _log(f"  等待中... ({i}s)")
            time.sleep(1)
    else:
        _log("警告: ZLMediaKit API 未能在 30s 内就绪，推流可能不稳定")

    _log("GB28181 容器启动完成")
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
    """打印容器最近日志"""
    for name in ["dog-zlmediakit", "dog-wvp"]:
        print(f"\n--- {name} 日志 (最近 {lines} 行) ---")
        r = subprocess.run(
            ["docker", "logs", "--tail", str(lines), name],
            capture_output=True, text=True, timeout=10,
        )
        print(r.stdout or r.stderr)


def _print_status():
    for cfg in CONTAINERS:
        name = cfg["name"]
        status = "运行中" if _container_running(name) else "未运行"
        print(f"  {name}: {status}")


def stop_containers():
    """停止并删除所有 GB28181 容器"""
    if not _is_docker_available():
        return

    _log("正在停止 GB28181 容器 ...")
    for cfg in CONTAINERS:
        name = cfg["name"]
        if _container_exists(name):
            _log(f"  停止并删除: {name}")
            _run("docker", "stop", "-t", "5", name)
            _run("docker", "rm", "-f", name)
        else:
            _log(f"  容器 {name} 不存在，跳过")

    # 清理网络
    if _network_exists(NETWORK):
        _run("docker", "network", "rm", NETWORK)

    _log("容器已停止")
