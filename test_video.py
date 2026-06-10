import cv2
import sys

def main():
    # 机器狗前广角相机的标准 RTSP 地址
    rtsp_url = "rtsp://10.21.31.103:8554/video1"
    
    print("正在连接机器狗前置摄像头视频流...")
    print("RTSP URL:", rtsp_url)
    
    # 初始化 VideoCapture
    cap = cv2.VideoCapture(rtsp_url)
    
    # 检查是否成功打开视频流
    if not cap.isOpened():
        print("错误: 无法打开视频流。请检查：")
        print("1. 您的电脑是否与机器狗连接在同一局域网内。")
        print("2. 机器狗的 IP 是否为 10.21.31.103，且相机模块已通电启动。")
        sys.exit(1)
        
    print("视频流连接成功！正在播放画面...")
    print("提示: 在画面窗口上按下 【ESC】 键可退出播放。")
    
    # 创建一个可调大小的窗口
    window_name = "DEEP Robotics - Lynx M20 Front Camera"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    
    try:
        while True:
            # 逐帧读取视频
            ret, frame = cap.read()
            
            # 如果读取失败（例如网络丢包或流断开），进行提示
            if not ret:
                print("警告: 无法接收视频帧 (Stream end?)。正在尝试重新读取...")
                cv2.waitKey(1000) # 等待 1 秒
                continue
                
            # 显示当前帧画面
            cv2.imshow(window_name, frame)
            
            # 检测按键，按 ESC (键码 27) 退出
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                print("用户按下 ESC，正在安全退出...")
                break
                
    except KeyboardInterrupt:
        print("\n检测到终端中断，正在关闭...")
        
    finally:
        # 释放资源并关闭所有窗口
        cap.release()
        cv2.destroyAllWindows()
        print("资源已释放，程序正常结束。")

if __name__ == "__main__":
    main()