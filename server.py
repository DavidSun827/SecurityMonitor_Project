import socket
import threading
import time
import os
import argparse
import json
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
        self.server_sock = None
        self.sync_completed = False
        project_root = os.path.dirname(os.path.abspath(__file__))
        self.delta_recovery_file = os.path.join(project_root, "recovered_delta_data.txt")
        self.local_state_file = os.path.join(project_root, f"node_state_{self.node_id}.txt")

        # ==========================================
        # 🛡️ 新增：状态历史记录 (用于恢复时的状态同步)
        # ==========================================
        self.state_history = []
        self._ensure_delta_file_exists()
        self._ensure_local_state_file_exists()
        self.persisted_signatures = self._load_local_state_signatures()

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

    def _record_signature(self, record):
        """生成稳定签名，用于差量去重比对。"""
        return json.dumps(record, sort_keys=True, ensure_ascii=False)

    def _extract_delta_records(self, new_history):
        """从同步历史中提取本节点宕机前未持久化过的差量记录。"""
        return [item for item in new_history if self._record_signature(item) not in self.persisted_signatures]

    def _persist_delta_records(self, delta_records):
        """把差量记录持久化到 txt，防止重联后内存状态丢失。"""
        if not delta_records:
            return

        with open(self.delta_recovery_file, "a", encoding="utf-8") as f:
            f.write(f"\n=== SYNC_AT,{time.time()} ===\n")
            for record in delta_records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _ensure_delta_file_exists(self):
        """启动时确保恢复日志文件可见，避免无差量时用户看不到文件。"""
        if os.path.exists(self.delta_recovery_file):
            return

        with open(self.delta_recovery_file, "w", encoding="utf-8") as f:
            f.write("# recovered delta data log\n")
            f.write("# each sync appends records missed during disconnection\n")

    def _log_sync_status(self, status):
        with open(self.delta_recovery_file, "a", encoding="utf-8") as f:
            f.write(f"\n=== SYNC_STATUS,{time.time()},{status} ===\n")

    def _ensure_local_state_file_exists(self):
        if os.path.exists(self.local_state_file):
            return

        with open(self.local_state_file, "w", encoding="utf-8") as f:
            f.write("# local durable state records for this node\n")

    def _load_local_state_signatures(self):
        signatures = set()
        with open(self.local_state_file, "r", encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                try:
                    record = json.loads(text)
                    signatures.add(self._record_signature(record))
                except json.JSONDecodeError:
                    continue
        return signatures

    def _append_local_state_record(self, record):
        signature = self._record_signature(record)
        if signature in self.persisted_signatures:
            return

        with open(self.local_state_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.persisted_signatures.add(signature)

    def listen_for_connections(self, port_override=None):
        listen_port = port_override or self.port
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, listen_port))
        self.server_sock.listen(5)

        print(f"[{self.node_id}] 🛡️ Listening for secure connections on {listen_port}...")

        while self.is_running:
            try:
                client_sock, addr = self.server_sock.accept()
                secure_sock = self.server_ssl_context.wrap_socket(client_sock, server_side=True)
                threading.Thread(target=self.handle_client, args=(secure_sock,), daemon=True).start()
            except OSError:
                # Socket 被手动关闭（例如故障切换时释放旧端口），结束当前监听线程
                break
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
                    self._append_local_state_record(payload)
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
                    self.sync_completed = True
                    print(
                        f"[{self.node_id}] ✅ State synchronization complete. Reconciled {len(history)} historical records.")
                    # 同步完成，算作一次有效心跳，防止刚上线就误判超时

                    # 提取并持久化“真正缺失”的差量数据，避免重联后丢失
                    delta_records = self._extract_delta_records(history)
                    self._persist_delta_records(delta_records)
                    for record in delta_records:
                        self._append_local_state_record(record)
                    if delta_records:
                        print(
                            f"[{self.node_id}] 💾 Persisted {len(delta_records)} delta records to {self.delta_recovery_file}")
                        self._log_sync_status(f"DELTA_{len(delta_records)}")
                    else:
                        self._log_sync_status("NO_DELTA")

                    # ==========================================
                    # 🚀 新增：把宕机期间错过的历史数据打印出来！
                    # ==========================================
                    if delta_records:
                        print(f"[{self.node_id}] 📜 Replaying missed data from Primary:")
                        for record in delta_records:
                            temp = record.get('temperature', 'N/A')
                            ts = record.get('timestamp', 'Unknown')
                            print(f"    -> Recovered Record: Temp={temp}°C (Generated at {ts})")
                    # ==========================================
                    
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
        time.sleep(1.5)  # 稍微等待，确保 Primary 已经启动并稳定监听
        while self.is_running and self.role == "backup" and not self.sync_completed:
            print(f"[{self.node_id}] 🔄 Requesting state synchronization from Primary...")
            payload = {"type": "sync_request", "timestamp": time.time()}
            success = self.send_secure_message(config.HOST, config.PRIMARY_PORT, payload, target_role="primary")
            if not success:
                self._log_sync_status("REQUEST_SEND_FAILED")
            time.sleep(2)

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

                try:
                    if self.server_sock:
                        self.server_sock.close()
                except Exception:
                    pass

                self.role = "primary"
                self._init_rsa_keys()
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