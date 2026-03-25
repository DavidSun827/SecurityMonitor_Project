import time
import random
from datetime import datetime
import config
from core_node import CoreNode


class SensorNode(CoreNode):
    def __init__(self, node_id):
        # Important: set role to "sensor" so CoreNode loads sensor_private.pem
        super().__init__(node_id=node_id, host=config.HOST, port=0, role="sensor")

        # Default target is Primary Server
        self.current_target_port = config.PRIMARY_PORT
        # self.current_target_port = 12000  # Use this line to route through the attack proxy in lab tests
        self.target_name = "Primary Server"
        self.target_role = "primary"  # Track target role so encryption uses the correct peer public key

    def generate_data(self):
        """Generate simulated monitoring telemetry."""
        return {
            "sensor_id": self.node_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "temperature": round(random.uniform(20.0, 35.0), 2),
            "status": "NORMAL"
        }

    def trigger_failover(self):
        """Fault-tolerance logic: on connection loss, switch target immediately."""
        if self.current_target_port == config.PRIMARY_PORT:
            print(f"[{self.node_id}] ⚠️ Connection lost! Executing Failover: Switching to Backup Server...")
            self.current_target_port = config.BACKUP_PORT
            self.target_name = "Backup Server"
            self.target_role = "backup"  # After failover, switch both port and target peer public key
        else:
            print(f"[{self.node_id}] ❌ Backup Server is also unreachable. Retrying...")

    def run(self):
        print(f"[{self.node_id}] Started. Sending signed data every {config.SENSOR_INTERVAL} seconds...")

        while True:
            data = self.generate_data()

            # Pass self.target_role so CoreNode encrypts the Fernet key with the correct public key
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