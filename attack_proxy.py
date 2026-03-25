import socket
import ssl
import threading
import json
import base64
import config

# 配置黑客代理的监听端口，以及真实 Primary 的端口
PROXY_HOST = config.HOST
PROXY_PORT = 12000  # 黑客代理监听 12000
REAL_PRIMARY_PORT = 11001  # 真实 Primary (11001)


def handle_client(sensor_sock, primary_sock):
    """处理从 Sensor 到 Primary 的数据转发，并进行篡改"""
    try:
        # 1. 从 Sensor 接收加密的数字信封 (原始数据)
        data = sensor_sock.recv(4096)
        if not data: return

        print("\n🕵️‍♂️ [Attacker] Intercepted message from Sensor.")

        try:
            # 2. 解析 JSON 信封 (此时数据还是 Base64 加密的，黑客解不开)
            envelope = json.loads(data.decode('utf-8'))

            # --- 核心篡改逻辑 ---
            # 我们不需要解密，只需要破坏 Base64 字符串中的几个字符，就能破坏密文或签名。

            # 方案 A：篡改密文 (Ciphertext)
            # 这将导致接收方在进行 Fernet 解密时，HMAC 校验失败。
            original_ciphertext = envelope["ciphertext"]
            # 把密文 Base64 字符串的最后三个字符改成 "BAD"
            tampered_ciphertext = original_ciphertext[:-3] + "BAD"
            envelope["ciphertext"] = tampered_ciphertext
            print("💀 [Attacker] Tampered with Ciphertext (Integrity Attack).")

            '''
            # 方案 B：篡改签名 (Signature) - 你可以注释掉上面，启用这段试试
            # 这将导致接收方在用公钥验签时，抛出 InvalidSignature 异常。
            original_signature = envelope["signature"]
            tampered_signature = original_signature[:-3] + "BAD"
            envelope["signature"] = tampered_signature
            print("💀 [Attacker] Tampered with Digital Signature (Authenticity Attack).")
            '''

            # 3. 将篡改后的信封重新打包成 JSON 字节流
            tampered_data = json.dumps(envelope).encode('utf-8')

            # 4. 转发给真正的 Primary Server
            primary_sock.sendall(tampered_data)
            print("➡️ [Attacker] Forwarded tampered message to Real Primary.")

        except json.JSONDecodeError:
            print("❌ [Attacker] Intercepted data is not valid JSON. Forwarding as-is.")
            primary_sock.sendall(data)

    except Exception as e:
        print(f"[Attacker] Error: {e}")
    finally:
        sensor_sock.close()
        primary_sock.close()


def start_proxy():
    print(f"😈 Secure MitM Proxy started. Listening on {PROXY_PORT}, forwarding to {REAL_PRIMARY_PORT}...")

    # 1. 初始化用于接收 Sensor 连接的 SSL 上下文 (伪装成服务器)
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(certfile=config.CERT_FILE, keyfile=config.KEY_FILE)

    # 2. 初始化用于连接真实 Primary 的 SSL 上下文 (作为客户端)
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    client_context.check_hostname = False
    client_context.verify_mode = ssl.CERT_NONE

    # 3. 创建监听 Socket
    proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy_sock.bind((PROXY_HOST, PROXY_PORT))
    proxy_sock.listen(5)

    while True:
        try:
            # 接收 Sensor 连接
            sensor_conn, addr = proxy_sock.accept()
            secure_sensor_sock = server_context.wrap_socket(sensor_conn, server_side=True)

            # 连接真实 Primary
            real_primary_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            secure_primary_sock = client_context.wrap_socket(real_primary_sock, server_hostname=PROXY_HOST)
            secure_primary_sock.connect((PROXY_HOST, REAL_PRIMARY_PORT))

            # 开线程处理转发和篡改
            threading.Thread(target=handle_client, args=(secure_sensor_sock, secure_primary_sock), daemon=True).start()
        except Exception as e:
            print(f"[Attacker] Accept Error: {e}")


if __name__ == "__main__":
    start_proxy()