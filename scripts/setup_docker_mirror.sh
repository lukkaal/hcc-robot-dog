#!/bin/bash
# 一键配置 Docker 国内镜像源 + 优先 IPv4
set -e

DAEMON_FILE="/etc/docker/daemon.json"

echo "=== Docker 国内镜像源配置 ==="

# 检查是否有 sudo 权限
if ! sudo -v 2>/dev/null; then
    echo "[ERROR] 需要 sudo 权限，请确认当前用户在 sudoers 组中"
    exit 1
fi

# 备份原有配置
if [ -f "$DAEMON_FILE" ]; then
    BACKUP="${DAEMON_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    echo "[INFO] 备份原有配置 → $BACKUP"
    sudo cp "$DAEMON_FILE" "$BACKUP"
fi

# 写入新配置
echo "[INFO] 写入镜像源配置 ..."
sudo tee "$DAEMON_FILE" > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me"
  ],
  "dns": ["223.5.5.5", "114.114.114.114"]
}
EOF

echo "[INFO] 配置内容:"
sudo cat "$DAEMON_FILE"

# 重启 Docker
echo "[INFO] 重启 Docker 服务 ..."
if command -v systemctl &>/dev/null; then
    sudo systemctl restart docker
    sudo systemctl is-active --quiet docker && echo "[OK] Docker 已重启，配置生效" || echo "[ERROR] Docker 重启失败"
else
    sudo service docker restart
    echo "[OK] Docker 已重启，配置生效"
fi

echo ""
echo "=== 验证: 尝试拉取测试镜像 ==="
docker pull hello-world
