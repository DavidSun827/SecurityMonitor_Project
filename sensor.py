import time
import random
from datetime import datetime
import config
from core_node import CoreNode


class SensorNode(CoreNode):
    def __init__(self, node_id):
        # 【重要修改】告诉底层 CoreNode 自己的角色是 "sensor"，以便它去加载 sensor_private.pem
        super().__init__(node_id=node_id, host=config.HOST, port=0, role="sensor")

        # 默认先连接 Primary Server
        self.current_target_port = config.PRIMARY_PORT
        #self.current_target_port = 12000#这里是模拟黑客就是primary，如果模拟恶意porxy就用这一行
        self.target_name = "Primary Server"
        self.target_role = "primary"  # 【重要修改】记录当前目标的角色，发消息时需要用到它的公钥

    def generate_data(self):
        """生成模拟的监控指标数据"""
        return {
            "sensor_id": self.node_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "temperature": round(random.uniform(20.0, 35.0), 2),
            "status": "NORMAL"
        }

    def trigger_failover(self):
        """容错核心逻辑：发现断开，立刻切换目标"""
        if self.current_target_port == config.PRIMARY_PORT:
            print(f"[{self.node_id}] ⚠️ Connection lost! Executing Failover: Switching to Backup Server...")
            self.current_target_port = config.BACKUP_PORT
            self.target_name = "Backup Server"
            self.target_role = "backup"  # 【重要修改】故障转移后，不仅要换端口，还要换对方的公钥
        else:
            print(f"[{self.node_id}] ❌ Backup Server is also unreachable. Retrying...")

    def run(self):
        print(f"[{self.node_id}] Started. Sending signed data every {config.SENSOR_INTERVAL} seconds...")

        while True:
            data = self.generate_data()

            # 【重要修改】调用时必须传入 self.target_role，底层会用这个角色的公钥去加密 Fernet 密钥
            success = self.send_secure_message(config.HOST, self.current_target_port, data, self.target_role)

            if success:
                print(
                    f"[{self.node_id}] 🔒 Signed & Sent to {self.target_name} ({self.current_target_port}): Temp={data['temperature']}°C")
            else:
                self.trigger_failover()

            time.sleep(config.SENSOR_INTERVAL)


if __name__ == "__main__":
    sensor = SensorNode(node_id="Sensor_1")
    try:
        sensor.run()
    except KeyboardInterrupt:
        print(f"\n[{sensor.node_id}] Shutting down gracefully.")