#!/bin/bash
# 轮换镜像源拉取 wvp-pro（应对 Docker Hub 429 限流）
set -e

IMAGE="108360/wvp-pro:latest"
MIRRORS=(
    "https://docker.m.daocloud.io"
    "https://docker.xuanyuan.me"
    "https://docker.1ms.run"
    "https://dockerhub.timeweb.cloud"
    "https://hub.rat.dev"
)

echo "=== 轮换镜像源拉取 ${IMAGE} ==="

for mirror in "${MIRRORS[@]}"; do
    echo ""
    echo ">>> 尝试镜像源: ${mirror}"

    sudo tee /etc/docker/daemon.json > /dev/null <<EOF
{
  "registry-mirrors": ["${mirror}"],
  "dns": ["223.5.5.5", "114.114.114.114"]
}
EOF

    sudo systemctl restart docker

    if docker pull "${IMAGE}" 2>&1; then
        echo ""
        echo "=== 拉取成功！当前镜像源: ${mirror} ==="
        exit 0
    fi

    echo ">>> ${mirror} 拉取失败，换下一个源..."
    sleep 2
done

echo ""
echo "=== 所有镜像源均失败，请检查网络或稍后重试 ==="
exit 1
