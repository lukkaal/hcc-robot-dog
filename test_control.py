import socket
import struct
import json
import time

# 机器人网络配置
ROBOT_IP = "10.21.31.103"  # 机器人默认UDP IP 
ROBOT_PORT = 30000         # 机器人默认UDP 端口 

class LynxRobotController:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_address = (ROBOT_IP, ROBOT_PORT)
        self.msg_id = 0  # 报文 ID，从0开始递增 [cite: 52]

    def _build_apdu(self, payload_dict):
        """
        根据手册 1.1.5 章节构建 16字节协议头部 + ASDU 数据 [cite: 42, 51]
        """
        # 1. 将 Python 字典转换为 JSON 字符串并转为字节
        json_str = json.dumps(payload_dict)
        asdu_bytes = json_str.encode('utf-8')
        asdu_len = len(asdu_bytes)

        # 2. 组装 16 字节的协议头部 [cite: 51]
        # 序号 1-4: 同步字符 固定为 0xeb, 0x91, 0xeb, 0x90 [cite: 52]
        header_sync = b'\xeb\x91\xeb\x90'
        
        # 序号 5: ASDU 长度 (2字节，小端序) [cite: 52]
        header_len = struct.pack('<H', asdu_len)
        
        # 序号 6: 报文 ID (2字节，小端序，自增) [cite: 52]
        header_id = struct.pack('<H', self.msg_id)
        self.msg_id = (self.msg_id + 1) % 65536  # 达到65535后重新从0开始 [cite: 52]
        
        # 序号 7: ASDU 格式 (1字节，JSON格式为 0x01) [cite: 52]
        header_format = b'\x01'
        
        # 序号 8: 预留 (7字节，暂填 0) [cite: 52]
        header_res = b'\x00' * 7

        # 拼接头部 [cite: 51]
        apdu_header = header_sync + header_len + header_id + header_format + header_res
        
        # 返回完整的 APDU 包（头部 + 数据） [cite: 42]
        return apdu_header + asdu_bytes

    def send_axis_command(self, x=0.0, y=0.0, z=0.0, roll=0.0, pitch=0.0, yaw=0.0):
        """
        发送轴控制指令。参数范围均为 [-1.0, 1.0]，代表相对于最大速度的比例 。
        """
        # 组装 1.2.5 要求的 ASDU 消息体 [cite: 53, 243]
        payload = {
            "PatrolDevice": {
                "Type": 2,        # 运动控制固定 Type=2 [cite: 241]
                "Command": 21,    # 运动控制固定 Command=21 [cite: 241]
                "Time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), # 本地时区格式 [cite: 56]
                "Items": {
                    "X": float(x),         # 前后方向速度（1.0 前进，-1.0 后退） 
                    "Y": float(y),         # 左右方向速度（1.0 左移，-1.0 右移） 
                    "Z": float(z),         # 高度方向速度 
                    "Roll": float(roll),   # 翻滚角速度 
                    "Pitch": float(pitch), # 俯仰角速度 
                    "Yaw": float(yaw)      # 偏航角速度（正值逆时针/左转，负值顺时针/右转） 
                }
            }
        }
        
        # 打包并发送
        apdu_packet = self._build_apdu(payload)
        self.sock.sendto(apdu_packet, self.server_address)

    def execute_motion_loop(self, duration, x=0.0, yaw=0.0, description=""):
        """
        以 20Hz 频率持续发送指定动作一段时间（手册推荐控制频率为20Hz） 
        """
        print(f"正在执行动作: {description} ...")
        start_time = time.time()
        
        # 20Hz 对应每帧间隔 0.05 秒 
        interval = 0.05 
        
        while time.time() - start_time < duration:
            loop_start = time.time()
            
            # 发送运动指令
            self.send_axis_command(x=x, yaw=yaw)
            
            # 维持 20Hz 的频率节奏 
            elapsed = time.time() - loop_start
            sleep_time = max(0.0, interval - elapsed)
            time.sleep(sleep_time)
            
        print("动作结束。")

    def stop_robot(self):
        """发送全 0 指令让机器人静止"""
        self.send_axis_command(x=0.0, yaw=0.0)
        print("机器人已下发停止指令。")

    def close(self):
        self.sock.close()

# --- 测试主程序 ---
if __name__ == "__main__":
    controller = LynxRobotController()
    
    try:
        print("=== 山猫M20 运动控制接口测试开始 ===")
        print("请确保机器人当前处于 【常规模式】 且已 【站立】！ [cite: 158, 182]")
        time.sleep(1)

        # 1. 测试慢速向前移动 2 秒 (X 设为最大速度的 15%) 
        controller.execute_motion_loop(duration=2.0, x=0.15, yaw=0.0, description="慢速向前移动")
        
        # 2. 停顿 1 秒
        controller.execute_motion_loop(duration=1.0, x=0.0, yaw=0.0, description="原地原地静止")

        # 3. 测试慢速向后移动 2 秒 (X 设为 -15%) 
        controller.execute_motion_loop(duration=2.0, x=-0.15, yaw=0.0, description="慢速向后移动")
        
        # 4. 停顿 1 秒
        controller.execute_motion_loop(duration=1.0, x=0.0, yaw=0.0, description="原地原地静止")

        # 5. 测试原地左转弯 2 秒 (Yaw 为正值，按右手坐标系逆时针旋转) 
        controller.execute_motion_loop(duration=2.0, x=0.0, yaw=0.2, description="原地左转弯（逆时针）")
        
        # 6. 停顿 1 秒
        controller.execute_motion_loop(duration=1.0, x=0.0, yaw=0.0, description="原地原地静止")

        # 7. 测试原地右转弯 2 秒 (Yaw 为负值，顺时针旋转) 
        controller.execute_motion_loop(duration=2.0, x=0.0, yaw=-0.2, description="原地右转弯（顺时针）")

    except KeyboardInterrupt:
        print("\n用户中断测试！")
    finally:
        # 最终务必下发全0指令使机器人安全停止
        controller.stop_robot()
        controller.close()
        print("=== 测试结束 ===")