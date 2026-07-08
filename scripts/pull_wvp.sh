#!/bin/bash
# 拉取 wvp-pro（支持代理）
set -e

IMAGE="108360/wvp-pro:latest"

echo "=== 拉取 ${IMAGE} ==="

# 读取代理（环境变量优先，否则询问）
PROXY="${DOCKER_PULL_PROXY:-}"
if [ -z "$PROXY" ] && [ -f /tmp/docker_proxy.conf ]; then
    PROXY=$(cat /tmp/docker_proxy.conf)
fi

if [ -z "$PROXY" ]; then
    echo ">>> 直连拉取 ..."
    sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "dns": ["223.5.5.5", "114.114.114.114"]
}
EOF
    sudo systemctl restart docker

    if docker pull "${IMAGE}" 2>&1; then
        echo "=== 直连拉取成功 ==="
        exit 0
    fi
    echo ">>> 直连失败，需要代理"
    echo ""
    read -r -p "请输入 HTTP 代理地址 (如 http://127.0.0.1:7890，回车跳过): " PROXY
    if [ -z "$PROXY" ]; then
        echo "未提供代理，退出"
        exit 1
    fi
    # 保存代理地址供后续重试
    echo "$PROXY" > /tmp/docker_proxy.conf
fi

echo ">>> 配置 Docker 代理: ${PROXY}"

# 给 Docker daemon 配代理
sudo mkdir -p /etc/systemd/system/docker.service.d
sudo tee /etc/systemd/system/docker.service.d/http-proxy.conf > /dev/null <<EOF
[Service]
Environment="HTTP_PROXY=${PROXY}"
Environment="HTTPS_PROXY=${PROXY}"
Environment="NO_PROXY=localhost,127.0.0.1"
EOF

sudo systemctl daemon-reload
sudo systemctl restart docker

echo ">>> 通过代理拉取 ..."
if docker pull "${IMAGE}" 2>&1; then
    echo ""
    echo "=== 拉取成功 ==="
    # 拉取成功后清理代理配置
    sudo rm -f /etc/systemd/system/docker.service.d/http-proxy.conf
    sudo systemctl daemon-reload
    sudo systemctl restart docker
    echo "=== 代理配置已清理 ==="
    exit 0
else
    echo ">>> 代理拉取也失败了"
    echo ">>> 检查代理是否可达: curl -I ${PROXY}"
    sudo rm -f /etc/systemd/system/docker.service.d/http-proxy.conf
    sudo systemctl daemon-reload
    sudo systemctl restart docker
    exit 1
fi
