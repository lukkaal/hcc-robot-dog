# 山猫M20 遥控网关

基于 FastAPI 的机器狗 Web 遥控面板，支持前后移动、左右转向及实时视频监控，内置 MQTT 桥接打通云端智慧工地平台到机器狗的远程控制链路。

## 环境管理

使用 `uv` 管理 Python 虚拟环境和依赖：

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## 启动网关

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后浏览器打开 http://localhost:8000 即可访问遥控面板。

## 项目结构

- `app/main.py` — FastAPI 入口，生命周期管理、控制API、视频流
- `app/robot_client.py` — 机器狗 UDP 控制协议封装
- `app/mqtt_bridge.py` — MQTT 桥接：云端指令 → 本地 HTTP
- `app/static/` — Web 遥控面板前端
- `smart_system（成功实现了与智慧工地系统的数据交互）/` — 智慧工地系统对接模块
