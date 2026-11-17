"""Settings. Every secret is read from the environment here and nowhere else (P1).

A blank value means "not configured". Tools that need it refuse with
``NotConfigured`` instead of pretending (P6).
"""

from __future__ import annotations

import os
import secrets
from decimal import Decimal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from providers.catalog import CATALOG, ProviderSpec

ENV_FILE = Path(".env")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_file() -> str:
    """Which file to read defaults from. JARVIS_ENV_FILE lets the test suite point
    at a file that does not exist, so a developer's real keys never reach a test."""
    return os.environ.get("JARVIS_ENV_FILE", str(ENV_FILE))


def _catalog_names() -> set[str]:
    return set(CATALOG)


def _catalog_spec(name: str | None) -> ProviderSpec | None:
    return CATALOG.get((name or "").strip().lower())


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
    llm_provider: str = "stub"  # stub | any name in providers/catalog.py
    llm_fallbacks: str = ""  # comma-separated: tried in order when the first is down
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    groq_api_key: str = ""
    gemini_api_key: str = ""
    cerebras_api_key: str = ""
    llm_model_strong: str = "gpt-4o-mini"
    llm_model_cheap: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # speech
    tts_provider: str = "deepgram"  # deepgram (en) | elevenlabs (multilingual) | azure
    deepgram_api_key: str = ""
    deepgram_stt_model: str = "nova-3"
    deepgram_lang_en: str = "en"
    deepgram_lang_zh: str = "zh-TW"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""  # blank: pick from /v1/voices at call time
    elevenlabs_model: str = "eleven_turbo_v2_5"
    deepgram_tts_model_en: str = "aura-2-thalia-en"
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
        return self.llm_provider in {name for name in _catalog_names()} and bool(self.llm_api_key)

    @property
    def llm_api_key(self) -> str:
        """The key for whichever provider is selected, so no caller has to branch."""
        spec = _catalog_spec(self.llm_provider)
        if spec is None:
            return ""
        return str(getattr(self, spec.name + "_api_key", ""))

    @property
    def llm_base_url(self) -> str:
        """Explicit *_BASE_URL wins; otherwise the catalog default."""
        spec = _catalog_spec(self.llm_provider)
        if spec is None:
            return self.openai_base_url
        override = str(getattr(self, spec.name + "_base_url", "") or "")
        return override or spec.base_url

    @property
    def llm_key_env_name(self) -> str:
        """Named in refusals so the operator is told which line to fill."""
        spec = _catalog_spec(self.llm_provider)
        return spec.key_env if spec else "OPENAI_API_KEY"

    @property
    def llm_chain(self) -> list[str]:
        """Primary then fallbacks, order preserved, duplicates and unknowns dropped."""
        chain: list[str] = []
        for name in [self.llm_provider, *self.llm_fallbacks.split(",")]:
            cleaned = name.strip().lower()
            if cleaned in {"stub", ""} or cleaned in chain:
                continue
            if _catalog_spec(cleaned) is not None:
                chain.append(cleaned)
        return chain

    def key_for(self, provider: str) -> str:
        spec = _catalog_spec(provider)
        return "" if spec is None else str(getattr(self, spec.name + "_api_key", ""))

    def model_for(self, provider: str) -> str:
        """The primary honours LLM_MODEL_STRONG; fallbacks use their catalog default."""
        if provider == self.llm_provider:
            return self.llm_model_strong
        spec = _catalog_spec(provider)
        return spec.default_model if spec else ""

    @property
    def tts_configured(self) -> bool:
        if self.tts_provider == "elevenlabs":
            return bool(self.elevenlabs_api_key)
        if self.tts_provider == "deepgram":
            # One key, ears and mouth: no second signup for English speech.
            return bool(self.deepgram_api_key)
        return bool(self.azure_speech_key)

    @property
    def tts_key_env_name(self) -> str:
        if self.tts_provider == "elevenlabs":
            return "ELEVENLABS_API_KEY"
        if self.tts_provider == "deepgram":
            return "DEEPGRAM_API_KEY"
        return "AZURE_SPEECH_KEY"


_cached: Settings | None = None


def get_settings() -> Settings:
    global _cached
    if _cached is None:
        _cached = Settings(_env_file=_env_file())
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
