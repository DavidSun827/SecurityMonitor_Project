# config.py
# --------------------------------------------------------
# Global Configuration for Secure Distributed Monitoring System
# --------------------------------------------------------

# 1. Network Settings
HOST = '127.0.0.1'
PRIMARY_PORT = 11001
BACKUP_PORT = 11002
ADMIN_PORT = 11003
#PRIMARY_PORT = 12000#模仿man in the middle attack

# 2. SSL/TLS Settings (Transport Layer Security)
CERT_FILE = 'certs/node_cert.pem'
KEY_FILE = 'certs/node_key.pem'

# 3. RSA Public Keys Directory (Application Layer Security)
# 用于 Explicit Node Authentication (显式节点认证)
PUBLIC_KEYS = {
    "primary": "keys/primary_public.pem",
    "backup": "keys/backup_public.pem",
    "sensor": "keys/sensor_public.pem"
}

# 4. Fault Tolerance Parameters
SENSOR_INTERVAL = 2.0
HEARTBEAT_INTERVAL = 1.0
HEARTBEAT_TIMEOUT = 3.0