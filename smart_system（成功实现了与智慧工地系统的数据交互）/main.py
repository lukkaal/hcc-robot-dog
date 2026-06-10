# main.py
import time
from cloud.mqtt_client import MqttManager
from core.data_processor import DataProcessor
from robot.connection import RobotConnection

def main():
    print("="*40)
    print("   山猫 M20 数据网关服务启动   ")
    print("="*40)
    
    # 1. 实例化核心对象
    mqtt_manager = MqttManager()
    robot_conn = RobotConnection(on_data_received_callback=None) 
    
    # 2. 实例化业务大脑，注入云端和机器狗对象
    processor = DataProcessor(mqtt_manager, robot_conn)
    
    # 3. 绑定回调钩子
    robot_conn.on_data_received = processor.process_raw_data    # 机器狗收到数据 -> 传给大脑
    mqtt_manager.command_callback = processor.process_cloud_command # 云端收到指令 -> 传给大脑
    
    try:
        # 4. 启动后台线程服务
        mqtt_manager.start()
        robot_conn.start()
        
        # 5. 挂起主线程，保持服务运行
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n[Sys] 接收到终止信号，准备退出...")
    finally:
        robot_conn.stop()
        mqtt_manager.stop()
        print("[Sys] 网关服务已安全退出")

if __name__ == "__main__":
    main()