# Role and Context
You are an expert Python Distributed Systems Architect. 
We have a Python-based secure distributed monitoring system with three main components:
1. `core_node.py`: The base class handling SSL/TLS, RSA asymmetric key exchange, Fernet message encryption, and anti-replay timestamps.
2. `server.py`: Runs as either a "primary" (port 11001) or "backup" (port 11002) node using a passive replication model with heartbeats.
3. `sensor.py`: Generates data and sends it to the primary. If primary fails, it fails over to the backup.

# Objective
Implement "Gap 2: State Synchronization upon Node Recovery". 
When the Primary dies, the Backup promotes itself to Primary (Failover). We need the ability to restart the dead node as a NEW Backup. This new Backup must rejoin the network, request historical data from the new Primary to synchronize its state, and trigger the Primary to resume replication.

# Implementation Instructions (Strictly follow these to avoid breaking crypto layers):

## Task 1: Update `server.py` for State History and Sync Request
1. In `ServerNode.__init__`, add `self.state_history = []`.
2. In `ServerNode.start`, if `self.role == "backup"`, start a new daemon thread targeting a new method `self.request_state_sync()`.
3. Create `request_state_sync(self)`: Wait 1.5 seconds, then send a message with `{"type": "sync_request", "timestamp": time.time()}` to the PRIMARY_PORT using `self.send_secure_message(..., target_role="primary")`.

## Task 2: Update `server.py` Data Handling (`handle_client` method)
1. **For `msg_type == "data"`:** Both primary and backup should append the `payload` to `self.state_history`. Keep only the latest 50 records (`if len(self.state_history) > 50: self.state_history.pop(0)`).
2. **For `msg_type == "sync_request"` (Role: Primary):** - Send back `{"type": "sync_response", "history": self.state_history}` to the BACKUP_PORT.
   - If `self.is_standalone` is True, set it to False, print a message that the Backup rejoined, and start a new daemon thread for `self.send_heartbeats()` to resume passive replication.
3. **For `msg_type == "sync_response"` (Role: Backup):**
   - Replace local `self.state_history` with the received history.
   - Update `self.last_heartbeat = time.time()` and `self.first_heartbeat_received = True` so it doesn't instantly trigger a false timeout.

## Task 3: Fix `server.py` Port Binding during Failover (`monitor_heartbeat` method)
Currently, when the Backup promotes to Primary, it keeps its old port bound.
1. In `listen_for_connections`, assign the socket to an instance variable: `self.server_sock = socket.socket(...)`. Catch exceptions gracefully if the socket is closed manually.
2. In `monitor_heartbeat`, right before changing `self.role = "primary"`, explicitly close the old socket: `try: self.server_sock.close() except: pass`. This frees port 11002 for the recovering node.
3. Immediately after `self.role = "primary"`, call `self._init_rsa_keys()` to load the Primary's RSA private key, otherwise it won't be able to decrypt future sensor messages.

## Task 4: Update `sensor.py` for Ping-Pong Failover
If the Backup has promoted to Primary (now on port 11001) and closed port 11002, the sensor will fail to connect to 11002.
1. In `SensorNode.trigger_failover()`, if `self.current_target_port == config.PRIMARY_PORT`, switch to `config.BACKUP_PORT`.
2. Provide an `else` block: If it fails to reach the BACKUP_PORT, switch the `current_target_port` back to `config.PRIMARY_PORT` and `target_role` to `"primary"`. This allows the sensor to successfully find the promoted node.

Please review the existing code in `server.py` and `sensor.py` and implement these precise changes. Do NOT modify the cryptographic logic in `core_node.py`.