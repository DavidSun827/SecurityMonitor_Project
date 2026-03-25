import socket
import ssl
import json
import base64
import time
from datetime import datetime
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature
import config


class CoreNode:
    def __init__(self, node_id, host, port, role):
        self.node_id = node_id
        self.host = host
        self.port = port
        self.role = role

        self._init_ssl_contexts()
        self._init_rsa_keys()

    def _init_ssl_contexts(self):
        self.server_ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self.server_ssl_context.load_cert_chain(certfile=config.CERT_FILE, keyfile=config.KEY_FILE)

        self.client_ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        self.client_ssl_context.check_hostname = False
        self.client_ssl_context.verify_mode = ssl.CERT_NONE

    def _init_rsa_keys(self):
        try:
            with open(f"keys/{self.role}_private.pem", "rb") as key_file:
                self.private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None
                )
        except FileNotFoundError:
            print(f"❌ [Node {self.node_id}] Private key not found! Run setup_crypto.py first.")

        self.public_keys = {}
        for role_name, path in config.PUBLIC_KEYS.items():
            try:
                with open(path, "rb") as key_file:
                    self.public_keys[role_name] = serialization.load_pem_public_key(key_file.read())
            except FileNotFoundError:
                print(f"❌ [Node {self.node_id}] Public key for {role_name} not found!")

    def pack_and_encrypt(self, data_dict, target_role):
        try:
            data_bytes = json.dumps(data_dict).encode('utf-8')

            signature = self.private_key.sign(
                data_bytes,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256()
            )

            ephemeral_fernet_key = Fernet.generate_key()
            cipher = Fernet(ephemeral_fernet_key)
            ciphertext = cipher.encrypt(data_bytes)

            target_pub_key = self.public_keys[target_role]
            encrypted_fernet_key = target_pub_key.encrypt(
                ephemeral_fernet_key,
                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
            )

            envelope = {
                "sender_role": self.role,
                "encrypted_key": base64.b64encode(encrypted_fernet_key).decode('utf-8'),
                "ciphertext": base64.b64encode(ciphertext).decode('utf-8'),
                "signature": base64.b64encode(signature).decode('utf-8')
            }
            return json.dumps(envelope).encode('utf-8')

        except Exception as e:
            print(f"[{self.node_id}] Encryption/Packing Error: {e}")
            return None

    def decrypt_and_unpack(self, received_bytes):
        try:
            envelope = json.loads(received_bytes.decode('utf-8'))
            sender_role = envelope["sender_role"]
            encrypted_fernet_key = base64.b64decode(envelope["encrypted_key"])
            ciphertext = base64.b64decode(envelope["ciphertext"])
            signature = base64.b64decode(envelope["signature"])

            fernet_key = self.private_key.decrypt(
                encrypted_fernet_key,
                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
            )

            cipher = Fernet(fernet_key)
            data_bytes = cipher.decrypt(ciphertext)

            sender_pub_key = self.public_keys[sender_role]
            sender_pub_key.verify(
                signature,
                data_bytes,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
                hashes.SHA256()
            )

            data_dict = json.loads(data_bytes.decode('utf-8'))

            # ==========================================
            # 🛡️ 新增：防重放攻击检测 (Anti-Replay Mechanism)
            # ==========================================
            if "timestamp" in data_dict:
                try:
                    ts_val = data_dict["timestamp"]
                    # 兼容处理：如果是心跳包的 float，直接用；如果是 Sensor 的 string，则转换
                    if isinstance(ts_val, (float, int)):
                        msg_time = float(ts_val)
                    else:
                        msg_time = datetime.strptime(ts_val, "%Y-%m-%d %H:%M:%S").timestamp()

                    # 如果这根数据包的生成时间距离现在超过了 5 秒，判定为过期/重放攻击！
                    if time.time() - msg_time > 5.0:
                        print(f"🚨 [{self.node_id}] SECURITY ALERT: Message expired/replayed! Payload dropped.")
                        return None
                except ValueError:
                    print(f"⚠️ [{self.node_id}] Invalid timestamp format. Payload dropped.")
                    return None

            return data_dict

        except InvalidSignature:
            print(
                f"🚨 [{self.node_id}] SECURITY ALERT: Invalid Digital Signature from '{sender_role}'! Payload dropped.")
            return None
        except Exception as e:
            print(f"[{self.node_id}] Decryption/Integrity Error: {e}")
            return None

    def send_secure_message(self, target_host, target_port, data_dict, target_role):
        try:
            raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_socket.settimeout(2.0)

            secure_socket = self.client_ssl_context.wrap_socket(raw_socket, server_hostname=target_host)
            secure_socket.connect((target_host, target_port))

            encrypted_envelope = self.pack_and_encrypt(data_dict, target_role)
            if encrypted_envelope:
                secure_socket.sendall(encrypted_envelope)

            secure_socket.close()
            return True
        except ConnectionRefusedError:
            return False
        except Exception as e:
            print(f"[{self.node_id}] Network Error sending to {target_port}: {e}")
            return False