import os
import base64
import ipaddress
import socket
from typing import Optional, Tuple, Union
from datetime import datetime
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..storage.models import SystemSettingsModel
from ..storage.repositories import SystemSettingsRepository


class EncryptionError(Exception):
    pass


class MissingEncryptionKeyError(EncryptionError):
    pass


class InvalidEncryptionKeyError(EncryptionError):
    pass


class SecretEncryptionService:
    def __init__(self):
        self._fernet: Optional[Fernet] = None
        self._key_valid = False
        self._initialized = False

    def _ensure_initialized(self):
        if not self._initialized:
            self._initialize_key()
            self._initialized = True

    def _initialize_key(self):
        key = os.getenv("SYSTEM_SETTINGS_SECRET_KEY")
        if not key:
            return
        try:
            if not key.endswith('='):
                key += '=' * (4 - len(key) % 4)
            key_bytes = base64.urlsafe_b64decode(key)
            if len(key_bytes) != 32:
                return
            self._fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
            self._key_valid = True
        except Exception:
            pass

    @property
    def is_available(self) -> bool:
        self._ensure_initialized()
        return self._key_valid

    def encrypt(self, plaintext: str) -> str:
        self._ensure_initialized()
        if not self._fernet:
            raise MissingEncryptionKeyError("SYSTEM_SETTINGS_SECRET_KEY not configured")
        return self._fernet.encrypt(plaintext.encode()).decode()

    def _normalize_ciphertext(self, ciphertext: Union[str, bytes]) -> bytes:
        if isinstance(ciphertext, bytes):
            return ciphertext
        if ciphertext.startswith("\\x"):
            return bytes.fromhex(ciphertext[2:])
        return ciphertext.encode()

    def decrypt(self, ciphertext: Union[str, bytes]) -> str:
        self._ensure_initialized()
        if not self._fernet:
            raise MissingEncryptionKeyError("SYSTEM_SETTINGS_SECRET_KEY not configured")
        try:
            return self._fernet.decrypt(self._normalize_ciphertext(ciphertext)).decode()
        except (InvalidToken, ValueError):
            raise EncryptionError("Failed to decrypt secret")

    def get_last4(self, plaintext: str) -> str:
        if len(plaintext) < 4:
            return plaintext
        return plaintext[-4:]


class SystemSettingsService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SystemSettingsRepository(db)

    def _get_encryption_service(self):
        return SecretEncryptionService()

    def get_settings(self) -> SystemSettingsModel:
        return self.repo.get_singleton()

    def _secret_is_usable(self, encrypted: Optional[Union[str, bytes]]) -> bool:
        if not encrypted:
            return False
        encryption = self._get_encryption_service()
        if not encryption.is_available:
            return False
        try:
            encryption.decrypt(encrypted)
        except EncryptionError:
            return False
        return True

    def get_settings_dict(self) -> dict:
        settings = self.get_settings()
        openai_key_usable = self._secret_is_usable(settings.openai_api_key_encrypted)
        custom_key_usable = self._secret_is_usable(settings.custom_api_key_encrypted)
        return {
            "llm": {
                "provider_mode": settings.provider_mode,
                "default_model": settings.default_model,
                "temperature": settings.temperature,
                "max_tokens": settings.max_tokens,
                "openai_api_key": {
                    "configured": openai_key_usable,
                    "last4": settings.openai_api_key_last4 if openai_key_usable else None,
                    "secret_updated_at": settings.secret_updated_at.isoformat() if settings.secret_updated_at else None,
                    "secret_cleared_at": settings.secret_cleared_at.isoformat() if settings.secret_cleared_at else None,
                },
                "custom_base_url": settings.custom_base_url,
                "custom_api_key": {
                    "configured": custom_key_usable,
                    "last4": settings.custom_api_key_last4 if custom_key_usable else None,
                    "secret_updated_at": settings.custom_secret_updated_at.isoformat() if settings.custom_secret_updated_at else None,
                    "secret_cleared_at": settings.custom_secret_cleared_at.isoformat() if settings.custom_secret_cleared_at else None,
                },
            },
            "ops": {
                "registration_enabled": settings.registration_enabled,
                "maintenance_mode": settings.maintenance_mode,
                "debug_enabled": settings.debug_enabled,
            },
            "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
            "updated_by_user_id": settings.updated_by_user_id,
        }

    @staticmethod
    def _normalize_custom_base_url(url: Optional[str]) -> Optional[str]:
        if url is None:
            return None
        url = url.strip()
        if not url:
            return None
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("custom_base_url must use http:// or https://")
        if not parsed.hostname:
            raise ValueError("custom_base_url must include a hostname")
        if parsed.username or parsed.password:
            raise ValueError("custom_base_url must not contain username or password credentials")
        if os.getenv("APP_ENV") == "production":
            if parsed.scheme != "https":
                raise ValueError("custom_base_url must use https:// in production")
            if os.getenv("ALLOW_PRIVATE_CUSTOM_LLM_ENDPOINTS") != "true":
                hostname = parsed.hostname.lower()
                if hostname == "localhost" or hostname.endswith(".localhost"):
                    raise ValueError("custom_base_url must not target localhost in production")
                try:
                    address = ipaddress.ip_address(hostname)
                except ValueError:
                    address = None
                if address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
                    raise ValueError("custom_base_url must not target private or local addresses in production")
                if address is None:
                    try:
                        resolved_addresses = {
                            item[4][0]
                            for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
                        }
                    except socket.gaierror:
                        raise ValueError("custom_base_url hostname must resolve in production")
                    for resolved in resolved_addresses:
                        resolved_address = ipaddress.ip_address(resolved)
                        if resolved_address.is_private or resolved_address.is_loopback or resolved_address.is_link_local or resolved_address.is_reserved:
                            raise ValueError("custom_base_url must not resolve to private or local addresses in production")
        return url

    def update_settings(self, data: dict, user_id: Optional[str] = None) -> dict:
        update_data = {}
        encryption = self._get_encryption_service()

        if "llm" in data:
            llm = data["llm"]
            if "provider_mode" in llm:
                if llm["provider_mode"] not in ("auto", "openai", "mock", "custom"):
                    raise ValueError("Invalid provider_mode")
                update_data["provider_mode"] = llm["provider_mode"]
            if "default_model" in llm:
                update_data["default_model"] = llm["default_model"]
            if "temperature" in llm:
                temp = llm["temperature"]
                if not (0 <= temp <= 2):
                    raise ValueError("temperature must be between 0 and 2")
                update_data["temperature"] = temp
            if "max_tokens" in llm:
                tokens = llm["max_tokens"]
                if not (1 <= tokens <= 8000):
                    raise ValueError("max_tokens must be between 1 and 8000")
                update_data["max_tokens"] = tokens
            if "openai_api_key" in llm:
                key_data = llm["openai_api_key"]
                action = key_data.get("action", "keep")
                if action == "set":
                    value = key_data.get("value")
                    if not value:
                        raise ValueError("Secret value required for set action")
                    if not encryption.is_available:
                        raise MissingEncryptionKeyError("Cannot set secret: encryption key not configured")
                    encrypted = encryption.encrypt(value)
                    update_data["openai_api_key_encrypted"] = encrypted
                    update_data["openai_api_key_last4"] = encryption.get_last4(value)
                    update_data["secret_updated_at"] = datetime.utcnow()
                    update_data["secret_cleared_at"] = None
                elif action == "clear":
                    update_data["openai_api_key_encrypted"] = None
                    update_data["openai_api_key_last4"] = None
                    update_data["secret_cleared_at"] = datetime.utcnow()
                elif action != "keep":
                    raise ValueError("Invalid secret action")
            if "custom_base_url" in llm:
                update_data["custom_base_url"] = self._normalize_custom_base_url(llm["custom_base_url"])
            if "custom_api_key" in llm:
                key_data = llm["custom_api_key"]
                action = key_data.get("action", "keep")
                if action == "set":
                    value = key_data.get("value")
                    if not value:
                        raise ValueError("Secret value required for set action")
                    if not encryption.is_available:
                        raise MissingEncryptionKeyError("Cannot set secret: encryption key not configured")
                    encrypted = encryption.encrypt(value)
                    update_data["custom_api_key_encrypted"] = encrypted
                    update_data["custom_api_key_last4"] = encryption.get_last4(value)
                    update_data["custom_secret_updated_at"] = datetime.utcnow()
                    update_data["custom_secret_cleared_at"] = None
                elif action == "clear":
                    update_data["custom_api_key_encrypted"] = None
                    update_data["custom_api_key_last4"] = None
                    update_data["custom_secret_cleared_at"] = datetime.utcnow()
                elif action != "keep":
                    raise ValueError("Invalid secret action")

        if "ops" in data:
            ops = data["ops"]
            if "registration_enabled" in ops:
                update_data["registration_enabled"] = bool(ops["registration_enabled"])
            if "maintenance_mode" in ops:
                update_data["maintenance_mode"] = bool(ops["maintenance_mode"])
            if "debug_enabled" in ops:
                update_data["debug_enabled"] = bool(ops["debug_enabled"])

        if update_data:
            self.repo.update_singleton(update_data, user_id)

        return self.get_settings_dict()

    def get_effective_openai_key(self) -> Optional[str]:
        settings = self.get_settings()
        encryption = self._get_encryption_service()
        if settings.openai_api_key_encrypted:
            if not encryption.is_available:
                return None
            try:
                return encryption.decrypt(settings.openai_api_key_encrypted)
            except EncryptionError:
                return None
        return os.getenv("OPENAI_API_KEY")

    def get_effective_custom_api_key(self) -> Optional[str]:
        settings = self.get_settings()
        if not settings.custom_api_key_encrypted:
            return None
        encryption = self._get_encryption_service()
        if not encryption.is_available:
            return None
        try:
            return encryption.decrypt(settings.custom_api_key_encrypted)
        except EncryptionError:
            return None

    def get_effective_custom_base_url(self) -> Optional[str]:
        settings = self.get_settings()
        return settings.custom_base_url

    def get_provider_config(self) -> dict:
        settings = self.get_settings()
        return {
            "provider_mode": settings.provider_mode,
            "default_model": settings.default_model,
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
            "custom_base_url": settings.custom_base_url,
        }


def check_maintenance_mode(db: Session) -> bool:
    service = SystemSettingsService(db)
    settings = service.get_settings()
    return settings.maintenance_mode
