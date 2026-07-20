# core/data_processor.py
import time
import json
from datetime import datetime
from config import UPLOAD_INTERVAL

class DataProcessor:
    def __init__(self, mqtt_manager, robot_connection):
        self.mqtt = mqtt_manager
        self.robot = robot_connection
        self.last_upload_time = 0

    # ================= 1. 上行：处理机器狗发来的数据 =================
    def process_raw_data(self, data: dict):
        root = data.get("PatrolDevice", {})
        
        # 处理设备状态上报 (Type 1002, Command 5)
        if root.get("Type") == 1002 and root.get("Command") == 5:
            self._handle_device_status(root)

    def _handle_device_status(self, root: dict):
        items = root.get("Items", {})
        batt = items.get("BatteryStatus", {})
        gps = items.get("GPS", {})

        # 强制使用边缘设备系统时间
        record_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 计算电量/电压平均值
        volt_l, volt_r = batt.get("VoltageLeft", 0), batt.get("VoltageRight", 0)
        bat_l, bat_r = batt.get("BatteryLevelLeft", 0), batt.get("BatteryLevelRight", 0)
        avg_volt = round((volt_l + volt_r) / 2.0, 1) if (volt_l or volt_r) else 0
        avg_bat = round((bat_l + bat_r) / 2.0) if (bat_l or bat_r) else 0

        # 只要左电池或右电池任意一个在充电，就认为机器狗在充电
        is_charging = batt.get("chargeLeft", False) or batt.get("chargeRight", False)
        charge_str = "1" if is_charging else "0"

        # 获取GPS
        lon, lat = gps.get("Longitude", 0), gps.get("Latitude", 0)
        lon_str = str(lon) if lon not in (0, 0.0) else ""
        lat_str = str(lat) if lat not in (0, 0.0) else ""

        payload = [
            {"id": "deviceNo", "value": "LYNX_M20", "remark": "设备编号"},
            {"id": "recordTime", "value": record_time, "remark": "数据时间"},
            {"id": "batteryVoltage", "value": str(avg_volt), "remark": "电池电压"},
            {"id": "batPercent", "value": str(avg_bat), "remark": "电池电量"},
            {"id": "isCharging", "value": charge_str, "remark": "是否充电(1是/0否)"},
            {"id": "longitude", "value": lon_str, "remark": "经度"},
            {"id": "latitude", "value": lat_str, "remark": "纬度"}
        ]

        # 频率控制
        current_time = time.time()
        if current_time - self.last_upload_time >= UPLOAD_INTERVAL:
            self.mqtt.publish_status(payload)
            self.last_upload_time = current_time

            # 日志中也打印出充电状态，方便您调试观察
            charge_log = "⚡充电中" if is_charging else "🔋未充电"
            print(f"[Processor] 定时上报 | 电量: {avg_bat}% | {charge_log} | 电压: {avg_volt}V")

    # ================= 2. 下行：处理云端发来的指令 =================
    def process_cloud_command(self, payload_str: str):
        try:
            # 1. 解析 JSON 字符串
            cmd_data = json.loads(payload_str)
            
            # 定义变量暂存提取出的指令
            move_action = None
            move_speed = "未设置"
            move_duration = "未设置"

            # 2. 判断数据格式并提取参数
            if isinstance(cmd_data, list):
                # 如果是数组格式：[{"id": "moveAction", "value": "1"}, ...]
                print(f"\n[Processor] 收到云端指令数组，正在解析...")
                for item in cmd_data:
                    item_id = item.get("id")
                    item_value = item.get("value")
                    
                    if item_id == "moveAction":
                        move_action = int(item_value)
                    elif item_id == "moveSpeed":
                        move_speed = int(item_value)
                    elif item_id == "moveDuration":
                        move_duration = int(item_value)
            # 4. 处理运动指令 (仅打印测试)
            if move_action is not None:
                # 动作映射字典
                action_map = {
                    0: "停止", 1: "前进", 2: "后退", 3: "左移",
                    4: "右移", 5: "左转", 6: "右转"
                }
                action_name = action_map.get(move_action, f"未知动作({move_action})")

                print("\n" + "▼"*45)
                print("🎯 成功解析云端移动指令 (数组/字典格式)：")
                print(f"   ▶ 动作类型: {move_action} [{action_name}]")
                print(f"   ▶ 设定速度: {move_speed}")
                print(f"   ▶ 持续时间: {move_duration}")
                print("   ⚠️ [测试拦截]：暂不下发给机器狗硬件")
                print("▲"*45 + "\n")
            else:
                print(f"\n[Processor] 收到未知指令内容: {payload_str}")

        except json.JSONDecodeError:
            print(f"\n[Processor] ❌ 格式错误，收到的不是合法JSON: {payload_str}")
        except Exception as e:
            print(f"\n[Processor] ❌ 指令处理异常: {e}")