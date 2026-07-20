import os
import threading
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

import cv2
import numpy as np
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.robot_client import RobotClient
from app.mqtt_bridge import MqttBridge
from app.docker_manager import ensure_containers, add_rtsp_proxy, stream_logs, start_ffmpeg_transcode, stop_ffmpeg_transcode
from app.gb28181_client import Gb28181Client, _load_config_from_env

RTSP_URL = os.environ.get("ROBOT_RTSP_URL", "rtsp://10.21.31.103:8554/video1")

robot: RobotClient = None
bridge: MqttBridge = None
gb_client: Gb28181Client = None
_frame_lock = threading.Lock()
_latest_frame: bytes | None = None


def _make_placeholder_frame():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(img, "NO SIGNAL", (140, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (100, 100, 255), 3)
    cv2.putText(img, "RTSP: " + RTSP_URL, (60, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
    _, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return jpeg.tobytes()


def _video_capture_loop():
    global _latest_frame
    retry_interval = 5.0
    while True:
        cap = cv2.VideoCapture(RTSP_URL)
        if not cap.isOpened():
            print(f"[Video] 无法打开RTSP视频流，{retry_interval}s后重试...")
            placeholder = _make_placeholder_frame()
            with _frame_lock:
                _latest_frame = placeholder
            time.sleep(retry_interval)
            continue

        print(f"[Video] 视频流已连接: {RTSP_URL}")
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    print("[Video] 视频流断开，尝试重连...")
                    break
                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                with _frame_lock:
                    _latest_frame = jpeg.tobytes()
        finally:
            cap.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global robot, bridge, gb_client

    print("[App] 初始化 GB28181 视频推流容器 ...")
    gb28181_ok = ensure_containers()
    if gb28181_ok:
        stream_logs()
        if start_ffmpeg_transcode():
            print("[App] HEVC→H.264 转码已启动，GB28181 推流将使用转码流")
        else:
            print("[App] 转码未启用，回退到直接 RTSP 代理")
            add_rtsp_proxy()

    print("[App] 正在初始化机器人控制器...")
    robot = RobotClient(default_speed=0.10, pulse_duration=0.5)
    print(f"[App] 机器人客户端就绪  |  默认速度: {robot.default_speed}  |  脉冲时长: {robot.pulse_duration}s")

    print("[App] 启动视频采集线程...")
    threading.Thread(target=_video_capture_loop, daemon=True).start()

    print("[App] 启动 MQTT 桥接（连接公网云端指令通道）...")
    bridge = MqttBridge()
    bridge.start()

    print("[App] 启动 GB28181 SIP 信令客户端 ...")
    gb_client = Gb28181Client(_load_config_from_env())
    gb_client.start()

    print("=" * 50)
    print("  山猫M20 遥控网关已就绪")
    print("  Web面板:    http://localhost:8000")
    print("  云端指令:    MQTT → 本机 :8000")
    print(f"  GB28181推流: {'已启用' if gb28181_ok else '未启用（Docker不可用）'}")
    print(f"  SIP注册状态: 启动中...")
    print(f"  视频主站:    {os.environ.get('GB28181_SIP_SERVER_HOST', '未配置')}")
    print("=" * 50)

    yield

    print("[App] 正在关闭...")
    gb_client.stop()
    bridge.stop()
    stop_ffmpeg_transcode()
    robot.close()
    print("[App] 已安全退出")


app = FastAPI(title="山猫M20 遥控网关", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 控制 API ====================

@app.post("/api/forward")
def api_forward(duration: float = Query(default=None, description="运动时长(秒)，默认0.5")):
    robot.forward(duration)
    return {"status": "ok", "action": "forward", "speed": robot.default_speed}


@app.post("/api/backward")
def api_backward(duration: float = Query(default=None, description="运动时长(秒)，默认0.5")):
    robot.backward(duration)
    return {"status": "ok", "action": "backward", "speed": robot.default_speed}


@app.post("/api/turn-left")
def api_turn_left(duration: float = Query(default=None, description="运动时长(秒)，默认0.5")):
    robot.turn_left(duration)
    return {"status": "ok", "action": "turn_left", "speed": robot.default_speed}


@app.post("/api/turn-right")
def api_turn_right(duration: float = Query(default=None, description="运动时长(秒)，默认0.5")):
    robot.turn_right(duration)
    return {"status": "ok", "action": "turn_right", "speed": robot.default_speed}


# ==================== 诊断 API ====================

@app.get("/api/status")
def api_status():
    """返回网关整体状态，包括 GB28181 SIP 注册状态"""
    gb_status = gb_client.selfcheck() if gb_client else None
    return {
        "robot": "connected" if robot else "disconnected",
        "mqtt": bridge.connected if bridge else None,
        "gb28181": {
            "running": gb_status.running,
            "registered": gb_status.registered,
            "push_active": gb_status.push_active,
            "local_sip": gb_status.local_sip,
            "server_sip": gb_status.server_sip,
            "device_id": gb_status.device_id,
            "push_target": gb_status.push_target,
            "last_error": gb_status.last_error,
            "heartbeat_fail": gb_status.heartbeat_fail_count,
            "zlm_rtsp_ok": gb_status.zlm_rtsp_ok,
            "zlm_rtp_active": gb_status.zlm_rtp_active,
            "zlm_rtp_bytes": gb_status.zlm_rtp_bytes,
        } if gb_status else None,
    }


# ==================== 视频流 API ====================

def _generate_mjpeg():
    last_frame_time = 0
    frame_interval = 1.0 / 15  # 15fps, 避免洪水淹没浏览器
    while True:
        with _frame_lock:
            frame = _latest_frame
        if frame is None:
            time.sleep(0.05)
            continue
        now = time.time()
        if now - last_frame_time < frame_interval:
            time.sleep(0.01)
            continue
        last_frame_time = now
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        )


@app.get("/api/video")
async def api_video():
    return StreamingResponse(
        _generate_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ==================== 前端页面 ====================

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
