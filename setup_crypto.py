import os
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def generate_rsa_keys():
    # Create the keys directory for RSA key material
    os.makedirs('keys', exist_ok=True)
    roles = ['primary', 'backup', 'sensor']

    print("🔑 Generating RSA Key Pairs for all nodes...")

    for role in roles:
        # 1. Generate RSA private key (2048-bit)
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()

        # 2. Save private key to PEM file
        with open(f'keys/{role}_private.pem', 'wb') as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ))

        # 3. Save public key to PEM file
        with open(f'keys/{role}_public.pem', 'wb') as f:
            f.write(public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ))
        print(f"✅ Generated keys for: {role.upper()}")

    print("\n🎉 All RSA keys successfully saved in the 'keys/' directory!")


if __name__ == "__main__":
    generate_rsa_keys()