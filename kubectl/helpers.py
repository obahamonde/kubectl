"""

Helpers for kubectl

"""
from pydantic import BaseModel, Field # pylint: disable=no-name-in-module
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


class SSHKeyPair(BaseModel): # pylint: disable=too-few-public-methods
    """
    
    An RSA SSH key pair
    
    """
    private_key: str = Field(..., description="Private key in PEM format")
    public_key: str = Field(..., description="Public key in OpenSSH format")


def generate_ssh_key_pair() -> SSHKeyPair:
    """
    
    Generate a SSH key pair    
    
    """
    def generate_rsa_key_pair():
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        public_key = private_key.public_key()

        return (private_key, public_key)

    def serialize_ssh_key_pair(private_key, public_key):
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH
        )

        return (private_pem.decode('utf-8'), public_pem.decode('utf-8'))

    private_key, public_key = generate_rsa_key_pair()
    private_pem, public_pem = serialize_ssh_key_pair(private_key, public_key)

    return SSHKeyPair(private_key=private_pem, public_key=public_pem)
