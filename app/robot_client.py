import socket
import json
import time

ROBOT_DEFAULT_IP = "10.21.31.103"
ROBOT_DEFAULT_PORT = 30000
DEFAULT_SPEED = 0.10          # 安全默认低速（最大速度的10%）
CONTROL_HZ = 20               # 控制频率 20Hz
CONTROL_INTERVAL = 1.0 / CONTROL_HZ


class RobotClient:
    """封装山猫M20机器狗UDP运动控制协议（无状态脉冲式）"""

    def __init__(self, ip: str = ROBOT_DEFAULT_IP, port: int = ROBOT_DEFAULT_PORT,
                 default_speed: float = DEFAULT_SPEED, pulse_duration: float = 0.5):
        self.server_address = (ip, port)
        self.default_speed = default_speed
        self.pulse_duration = pulse_duration
        self.msg_id = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # ==================== 协议打包 ====================

    def _build_apdu(self, payload: dict) -> bytes:
        json_str = json.dumps(payload)
        asdu_bytes = json_str.encode("utf-8")
        asdu_len = len(asdu_bytes)

        header = bytearray(16)
        header[0:4] = b"\xeb\x91\xeb\x90"
        header[4] = asdu_len & 0xFF
        header[5] = (asdu_len >> 8) & 0xFF
        header[6] = self.msg_id & 0xFF
        header[7] = (self.msg_id >> 8) & 0xFF
        header[8] = 0x01
        self.msg_id = (self.msg_id + 1) % 65536

        return bytes(header) + asdu_bytes

    def _send_axis_command(self, x: float = 0.0, yaw: float = 0.0):
        payload = {
            "PatrolDevice": {
                "Type": 2,
                "Command": 21,
                "Time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "Items": {
                    "X": x, "Y": 0.0, "Z": 0.0,
                    "Roll": 0.0, "Pitch": 0.0, "Yaw": yaw,
                },
            }
        }
        self._sock.sendto(self._build_apdu(payload), self.server_address)

    # ==================== 脉冲式运动控制 ====================

    def _pulse(self, x: float, yaw: float, duration: float = None):
        """发送一段持续 duration 秒的 20Hz 控制脉冲，结束后自动停发（UDP断流即停）"""
        if duration is None:
            duration = self.pulse_duration
        deadline = time.time() + duration
        while time.time() < deadline:
            loop_start = time.time()
            self._send_axis_command(x=x, yaw=yaw)
            elapsed = time.time() - loop_start
            sleep_time = CONTROL_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def move(self, x: float, yaw: float, duration: float = None):
        """通用运动：发脉冲 → 自动归零"""
        self._pulse(x=x, yaw=yaw, duration=duration)

    # ==================== 高层语义接口 ====================

    def forward(self, duration: float = None):
        self._pulse(x=self.default_speed, yaw=0.0, duration=duration)

    def backward(self, duration: float = None):
        self._pulse(x=-self.default_speed, yaw=0.0, duration=duration)

    def turn_left(self, duration: float = None):
        self._pulse(x=0.0, yaw=self.default_speed, duration=duration)

    def turn_right(self, duration: float = None):
        self._pulse(x=0.0, yaw=-self.default_speed, duration=duration)

    def close(self):
        self._send_axis_command(x=0.0, yaw=0.0)
        self._sock.close()
