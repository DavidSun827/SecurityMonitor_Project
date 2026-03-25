import socket
import threading
import time
import os
import argparse
import config
from core_node import CoreNode


class ServerNode(CoreNode):
    def __init__(self, node_id, role):
        self.role = role
        port = config.PRIMARY_PORT if role == "primary" else config.BACKUP_PORT

        super().__init__(node_id=node_id, host=config.HOST, port=port, role=role)

        # 状态与防抖标记
        self.last_heartbeat = time.time()
        self.is_running = True
        self.first_heartbeat_received = False
        self.is_standalone = False
        self.recovery_logged = False

        # ==========================================
        # 🛡️ 新增：状态历史记录 (用于恢复时的状态同步)
        # ==========================================
        self.state_history = []

    def start(self):
        """启动服务器及其所有后台线程"""
        print(f"[{self.node_id}] Starting as {self.role.upper()} on port {self.port}")

        # 1. 启动主监听线程（接收 SSL 连接）
        threading.Thread(target=self.listen_for_connections, daemon=True).start()

        if self.role == "primary":
            threading.Thread(target=self.send_heartbeats, daemon=True).start()
            threading.Thread(target=self.listen_admin_console, daemon=True).start()
        elif self.role == "backup":
            threading.Thread(target=self.monitor_heartbeat, daemon=True).start()
            # 🚀 新增：Backup 启动时，主动向 Primary 请求同步历史状态
            threading.Thread(target=self.request_state_sync, daemon=True).start()

        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n[{self.node_id}] Shutting down gracefully.")
            self.is_running = False

    def listen_for_connections(self, port_override=None):
        listen_port = port_override or self.port
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((self.host, listen_port))
        server_sock.listen(5)

        print(f"[{self.node_id}] 🛡️ Listening for secure connections on {listen_port}...")

        while self.is_running:
            try:
                client_sock, addr = server_sock.accept()
                secure_sock = self.server_ssl_context.wrap_socket(client_sock, server_side=True)
                threading.Thread(target=self.handle_client, args=(secure_sock,), daemon=True).start()
            except Exception as e:
                if self.is_running:
                    print(f"[{self.node_id}] Accept Error: {e}")

    def handle_client(self, secure_sock):
        try:
            data = secure_sock.recv(4096)
            if data:
                payload = self.decrypt_and_unpack(data)
                if not payload:
                    return

                msg_type = payload.get("type", "data")

                # --------------------------------------------------
                # 1. 处理业务数据 (Data)
                # --------------------------------------------------
                if msg_type == "data":
                    # 无论主备，都把数据存入历史记录 (最多保留 50 条防内存溢出)
                    self.state_history.append(payload)
                    if len(self.state_history) > 50:
                        self.state_history.pop(0)

                    if self.role == "primary":
                        print(f"[{self.node_id}] 📥 Received Valid Data: Temp={payload.get('temperature')}°C")

                        if self.is_standalone and not self.recovery_logged:
                            with open("mttr_log.txt", "a") as f:
                                f.write(f"T_RECOVERY,{time.time()}\n")
                            self.recovery_logged = True

                        if not self.is_standalone:
                            self.send_secure_message(config.HOST, config.BACKUP_PORT, payload, target_role="backup")

                    elif self.role == "backup":
                        print(f"[{self.node_id}] 🗂️ State Replicated securely: Temp={payload.get('temperature')}°C")

                # --------------------------------------------------
                # 2. 处理同步请求 (Backup 刚上线时发来的)
                # --------------------------------------------------
                elif msg_type == "sync_request" and self.role == "primary":
                    print(
                        f"[{self.node_id}] 🔄 Received sync request. Sending {len(self.state_history)} records to Backup.")
                    response = {"type": "sync_response", "history": self.state_history}
                    self.send_secure_message(config.HOST, config.BACKUP_PORT, response, target_role="backup")

                    # 极其重要：如果 Primary 是孤狼模式（前任 Backup 刚篡位的），此时它有了新小弟，彻底解除孤狼模式！
                    if self.is_standalone:
                        print(
                            f"[{self.node_id}] 🤝 New Backup rejoined! Exiting Standalone Mode. Resuming heartbeats & replication.")
                        self.is_standalone = False
                        # 重新启动发心跳的线程
                        threading.Thread(target=self.send_heartbeats, daemon=True).start()

                # --------------------------------------------------
                # 3. 处理同步响应 (Primary 把历史数据发过来了)
                # --------------------------------------------------
                elif msg_type == "sync_response" and self.role == "backup":
                    history = payload.get("history", [])
                    self.state_history = history
                    print(
                        f"[{self.node_id}] ✅ State synchronization complete. Reconciled {len(history)} historical records.")
                    # 同步完成，算作一次有效心跳，防止刚上线就误判超时
                    self.last_heartbeat = time.time()
                    self.first_heartbeat_received = True

                # --------------------------------------------------
                # 4. 处理心跳包 (Heartbeat)
                # --------------------------------------------------
                elif msg_type == "heartbeat" and self.role == "backup":
                    self.last_heartbeat = time.time()
                    self.first_heartbeat_received = True

        except Exception as e:
            print(f"[{self.node_id}] Client Handle Error: {e}")
        finally:
            secure_sock.close()

    def request_state_sync(self):
        """Backup 专属：上线时向 Primary 索要历史数据"""
        time.sleep(1)  # 稍微等一秒，确保 Primary 已经启动
        print(f"[{self.node_id}] 🔄 Requesting state synchronization from Primary...")
        payload = {"type": "sync_request", "timestamp": time.time()}
        self.send_secure_message(config.HOST, config.PRIMARY_PORT, payload, target_role="primary")

    def send_heartbeats(self):
        while self.is_running and self.role == "primary" and not self.is_standalone:
            hb_payload = {"type": "heartbeat", "timestamp": time.time()}
            self.send_secure_message(config.HOST, config.BACKUP_PORT, hb_payload, target_role="backup")
            time.sleep(config.HEARTBEAT_INTERVAL)

    def listen_admin_console(self):
        admin_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        admin_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        admin_sock.bind((self.host, config.ADMIN_PORT))
        admin_sock.listen(1)
        print(f"[{self.node_id}] ⚠️ Admin Fault Injector active on port {config.ADMIN_PORT}...")

        while self.is_running:
            client, _ = admin_sock.accept()
            cmd = client.recv(1024).decode('utf-8')
            if cmd == "INJECT_CRASH_PRIMARY":
                print(f"\n[{self.node_id}] 🚨 FATAL: Received CRASH command from Admin Console!")
                print(f"[{self.node_id}] Terminating process immediately...")
                os._exit(0)
            client.close()

    def monitor_heartbeat(self):
        while self.is_running and self.role == "backup":
            time.sleep(1)
            if self.first_heartbeat_received and (time.time() - self.last_heartbeat > config.HEARTBEAT_TIMEOUT):
                print(f"\n[{self.node_id}] 🚨 CRITICAL: Primary Server heartbeat timeout!")

                with open("mttr_log.txt", "a") as f:
                    f.write(f"T_DETECT,{time.time()}\n")

                print(f"[{self.node_id}] ⚡ Executing FAILOVER: Promoting to Primary...")

                self.role = "primary"
                self.port = config.PRIMARY_PORT
                self.is_standalone = True

                threading.Thread(target=self.listen_for_connections, args=(config.PRIMARY_PORT,), daemon=True).start()
                print(f"[{self.node_id}] ✅ Failover complete. Now acting as Active Primary Server (Standalone Mode).")
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the Server Node")
    parser.add_argument("--role", choices=["primary", "backup"], required=True, help="Server role")
    args = parser.parse_args()

    node_name = "Primary_1" if args.role == "primary" else "Backup_1"
    server = ServerNode(node_id=node_name, role=args.role)
    server.start()