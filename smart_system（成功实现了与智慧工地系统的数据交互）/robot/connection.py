# robot/connection.py
import socket
import threading
import time
from datetime import datetime
from config import ROBOT_IP, ROBOT_PORT, HEARTBEAT_INTERVAL
from robot.protocol import ProtocolHandler

class RobotConnection:
    def __init__(self, on_data_received_callback):
        self.on_data_received = on_data_received_callback
        self.sock = None
        self.is_running = False
        self.msg_id_counter = 1

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((ROBOT_IP, ROBOT_PORT))
        self.sock.settimeout(0.5)
        self.is_running = True
        print(f"[Robot] 已连接到机器狗 TCP: {ROBOT_IP}:{ROBOT_PORT}")
        
        threading.Thread(target=self._receive_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def send_command(self, cmd_dict: dict):
        """供外部调用的发送方法"""
        if self.sock and self.is_running:
            try:
                self.sock.sendall(ProtocolHandler.pack(cmd_dict, self.msg_id_counter))
                self.msg_id_counter = (self.msg_id_counter + 1) % 65535
            except Exception as e:
                print(f"[Robot] 指令发送失败: {e}")

    def _heartbeat_loop(self):
        while self.is_running:
            heartbeat = {
                "PatrolDevice": {
                    "Type": 100, 
                    "Command": 100, 
                    "Time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                    "Items": {}
                }
            }
            self.send_command(heartbeat)
            time.sleep(HEARTBEAT_INTERVAL)

    def _receive_loop(self):
        buffer = b""
        while self.is_running:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    print("[Robot] 机器狗断开连接")
                    break
                buffer += chunk
                
                while True:
                    data, buffer = ProtocolHandler.unpack_stream(buffer)
                    if data:
                        self.on_data_received(data)
                    else:
                        break
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Robot] 接收异常: {e}")
                break

    def stop(self):
        self.is_running = False
        if self.sock:
            self.sock.close()
        print("[Robot] 连接已关闭")