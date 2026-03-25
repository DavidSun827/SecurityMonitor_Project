import socket
import ssl
import threading
import json
import base64
import config

# Configure attacker proxy listen port and real Primary port
PROXY_HOST = config.HOST
PROXY_PORT = 12000  # Attacker proxy listens on 12000
REAL_PRIMARY_PORT = 11001  # Real Primary (11001)


def handle_client(sensor_sock, primary_sock):
    """Forward Sensor->Primary traffic and tamper with the envelope."""
    try:
        # 1. Receive encrypted envelope from Sensor (raw data)
        data = sensor_sock.recv(4096)
        if not data: return

        print("\n🕵️‍♂️ [Attacker] Intercepted message from Sensor.")

        try:
            # 2. Parse JSON envelope (payload is still Base64-encoded ciphertext)
            envelope = json.loads(data.decode('utf-8'))

            # --- Core tampering logic ---
            # No decryption needed: corrupt a few Base64 chars to break ciphertext or signature.

            # Option A: Tamper with ciphertext
            # This causes Fernet HMAC verification to fail at receiver side.
            original_ciphertext = envelope["ciphertext"]
            # Replace the final three Base64 chars with "BAD"
            tampered_ciphertext = original_ciphertext[:-3] + "BAD"
            envelope["ciphertext"] = tampered_ciphertext
            print("💀 [Attacker] Tampered with Ciphertext (Integrity Attack).")

            '''
            # Option B: Tamper with signature - disable Option A and enable this block to test
            # This causes InvalidSignature during public-key verification.
            original_signature = envelope["signature"]
            tampered_signature = original_signature[:-3] + "BAD"
            envelope["signature"] = tampered_signature
            print("💀 [Attacker] Tampered with Digital Signature (Authenticity Attack).")
            '''

            # 3. Re-serialize tampered envelope as JSON bytes
            tampered_data = json.dumps(envelope).encode('utf-8')

            # 4. Forward to real Primary server
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

    # 1. Initialize SSL context for inbound Sensor connections (acting as server)
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(certfile=config.CERT_FILE, keyfile=config.KEY_FILE)

    # 2. Initialize SSL context for outbound connection to real Primary (acting as client)
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    client_context.check_hostname = False
    client_context.verify_mode = ssl.CERT_NONE

    # 3. Create listening socket
    proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy_sock.bind((PROXY_HOST, PROXY_PORT))
    proxy_sock.listen(5)

    while True:
        try:
            # Accept Sensor connection
            sensor_conn, addr = proxy_sock.accept()
            secure_sensor_sock = server_context.wrap_socket(sensor_conn, server_side=True)

            # Connect to real Primary
            real_primary_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            secure_primary_sock = client_context.wrap_socket(real_primary_sock, server_hostname=PROXY_HOST)
            secure_primary_sock.connect((PROXY_HOST, REAL_PRIMARY_PORT))

            # Spawn thread for forwarding and tampering
            threading.Thread(target=handle_client, args=(secure_sensor_sock, secure_primary_sock), daemon=True).start()
        except Exception as e:
            print(f"[Attacker] Accept Error: {e}")


if __name__ == "__main__":
    start_proxy()