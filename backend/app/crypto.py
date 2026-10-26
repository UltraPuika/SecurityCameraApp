from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    """Encrypts secrets (camera passwords, API keys) for storage at rest."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("secret could not be decrypted (wrong encryption key?)") from exc
