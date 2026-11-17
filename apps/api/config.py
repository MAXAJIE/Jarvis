"""Settings. Every secret is read from the environment here and nowhere else (P1).

A blank value means "not configured". Tools that need it refuse with
``NotConfigured`` instead of pretending (P6).
"""

from __future__ import annotations

import secrets
from decimal import Decimal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(".env")
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    # core
    app_env: str = "dev"
    app_base_url: str = "http://127.0.0.1:8000"
    secret_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./var/jarvis.db"
    operator_email: str = "operator@localhost"

    # operator credentials (written by scripts/setup_operator.py)
    operator_password_hash: str = ""
    operator_totp_secret: str = ""

    # models
    llm_provider: str = "stub"  # stub | openai | openrouter
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model_strong: str = "gpt-4o-mini"
    llm_model_cheap: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # speech
    deepgram_api_key: str = ""
    deepgram_lang_en: str = "en"
    deepgram_lang_zh: str = "zh-TW"
    azure_speech_key: str = ""
    azure_speech_region: str = "southeastasia"
    azure_voice_en: str = "en-MY-YasminNeural"
    azure_voice_zh: str = "zh-TW-HsiaoChenNeural"

    # telephony
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_webhook_base: str = ""
    twilio_default_line_e164: str = ""

    # messaging / mail
    telegram_bot_token: str = ""
    telegram_allowed_chat_id: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # safety
    sandbox_image: str = ""
    sandbox_egress_allowlist: str = ""
    monthly_budget_usd: Decimal = Decimal("20")
    budget_alarm_usd: Decimal = Decimal("15")
    fixed_monthly_usd: Decimal = Decimal("11.80")
    call_max_duration_s: int = 600
    approval_ttl_minutes: int = 30

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    @property
    def llm_configured(self) -> bool:
        """A real provider *and* the key its calls need. The stub is never "configured"."""
        return self.llm_provider in {"openai", "openrouter"} and bool(self.llm_api_key)

    @property
    def llm_api_key(self) -> str:
        """The key for whichever provider is selected, so no caller has to branch."""
        if self.llm_provider == "openrouter":
            return self.openrouter_api_key
        return self.openai_api_key

    @property
    def llm_base_url(self) -> str:
        """OpenRouter is OpenAI-compatible, so only the base URL moves."""
        if self.llm_provider == "openrouter":
            return self.openrouter_base_url
        return self.openai_base_url

    @property
    def llm_key_env_name(self) -> str:
        """Named in refusals so the operator is told which line to fill."""
        return "OPENROUTER_API_KEY" if self.llm_provider == "openrouter" else "OPENAI_API_KEY"


_cached: Settings | None = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        _cached = Settings()
    return _cached


def reset_settings_cache() -> None:
    """Tests swap env vars between cases; this drops the memoised instance."""
    global _cached
    _cached = None


def ensure_secret_key() -> str:
    """Create SECRET_KEY on first boot and persist it to .env.

    Not in code (P1), not printed, not derived from anything guessable. Session
    cookies are signed with it, so an ephemeral value would log the operator out
    on every restart, which is why it is written down once.
    """
    settings = get_settings()
    if settings.secret_key:
        return settings.secret_key
    generated = secrets.token_urlsafe(48)
    path = REPO_ROOT / ENV_FILE
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{prefix}SECRET_KEY={generated}\n")
    settings.secret_key = generated
    return generated
