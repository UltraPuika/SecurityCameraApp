from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.netguard import parse_networks


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAMDASH_", env_file=None, extra="ignore")

    database_url: str = "sqlite:////data/camdash.db"
    encryption_key: SecretStr
    admin_username: str = Field(default="admin", min_length=3, max_length=64)
    admin_password: SecretStr | None = None
    cookie_secure: bool = True
    session_ttl_hours: int = Field(default=24 * 7, ge=1, le=24 * 90)
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_window_seconds: int = Field(default=900, ge=10, le=86400)
    static_dir: str = "/app/static"
    # Extra CIDRs cameras may live in, beyond RFC 1918 / CGNAT / ULA (comma-separated).
    allowed_camera_networks: str = ""
    probe_timeout_seconds: float = Field(default=8.0, ge=1, le=60)
    go2rtc_url: str = "http://go2rtc:1984"
    stream_idle_seconds: int = Field(default=60, ge=5, le=3600)
    # Not yet measured on a Pi 5; replace with the Stage 5 load-test result.
    max_streams: int = Field(default=6, ge=1, le=64)

    @field_validator("allowed_camera_networks")
    @classmethod
    def _valid_networks(cls, v: str) -> str:
        try:
            parse_networks(v)
        except ValueError as exc:
            msg = "CAMDASH_ALLOWED_CAMERA_NETWORKS must be comma-separated CIDRs"
            raise ValueError(msg) from exc
        return v

    @field_validator("encryption_key")
    @classmethod
    def _valid_fernet_key(cls, v: SecretStr) -> SecretStr:
        try:
            Fernet(v.get_secret_value().encode())
        except Exception as exc:
            raise ValueError(
                "CAMDASH_ENCRYPTION_KEY must be a urlsafe-base64 32-byte key "
                "(generate with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\")"
            ) from exc
        return v

    @field_validator("admin_password")
    @classmethod
    def _strong_enough(cls, v: SecretStr | None) -> SecretStr | None:
        if v is not None and len(v.get_secret_value()) < 12:
            raise ValueError("CAMDASH_ADMIN_PASSWORD must be at least 12 characters")
        return v

    @property
    def session_cookie_name(self) -> str:
        # The __Host- prefix requires Secure, so it is only usable over HTTPS.
        return "__Host-camdash_session" if self.cookie_secure else "camdash_session"


@lru_cache
def get_settings() -> Settings:
    return Settings()
