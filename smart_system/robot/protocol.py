# robot/protocol.py
import json

class ProtocolHandler:
    @staticmethod
    def pack(asdu_dict: dict, msg_id: int = 1) -> bytes:
        """将字典打包为 16字节头 + JSON 字节流"""
        content = json.dumps(asdu_dict).encode('utf-8')
        data_len = len(content)
        
        header = bytearray(16)
        header[0:4] = b'\xeb\x91\xeb\x90'
        header[4] = data_len & 0xFF
        header[5] = (data_len >> 8) & 0xFF
        header[6] = msg_id & 0xFF
        header[7] = (msg_id >> 8) & 0xFF
        header[8] = 0x01  # 0x01 表示 JSON 格式
        return header + content

    @staticmethod
    def unpack_stream(buffer: bytes):
        """流式解析：提取出一个完整的 JSON 包和剩余的 buffer"""
        if len(buffer) < 16:
            return None, buffer
            
        if buffer[0:4] != b'\xeb\x91\xeb\x90':
            return None, buffer[1:]
            
        asdu_len = buffer[4] | (buffer[5] << 8)
        total_len = 16 + asdu_len
        
        if len(buffer) < total_len:
            return None, buffer
            
        asdu_bytes = buffer[16:total_len]
        try:
            data = json.loads(asdu_bytes.decode('utf-8'))
            return data, buffer[total_len:]
        except json.JSONDecodeError:
            return None, buffer[total_len:]