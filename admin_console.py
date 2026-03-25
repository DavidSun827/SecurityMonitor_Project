import socket
import time  # <--- 新增
import config


def inject_primary_crash():
    print(f"⚠️  Connecting to Admin Console on port {config.ADMIN_PORT}...")
    try:
        admin_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        admin_socket.connect((config.HOST, config.ADMIN_PORT))

        # --- 自动化记录 T0 ---
        with open("mttr_log.txt", "a") as f:
            f.write(f"T0_CRASH,{time.time()}\n")
        # ----------------------

        admin_socket.sendall(b"INJECT_CRASH_PRIMARY")
        print("✅  FATAL CRASH command sent! Primary Server should be dead now.")

        admin_socket.close()
    except ConnectionRefusedError:
        print("❌  Failed to connect. Is the Primary Server running?")


if __name__ == "__main__":
    inject_primary_crash()