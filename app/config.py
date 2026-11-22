import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


def _req(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        raise ConfigError(f"missing env {name}")
    return v


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int
    public_base: str
    db_path: str
    nowpayments_key: str
    nowpayments_ipn_secret: str
    alert_chat_id: int | None
    tz: str
    min_usd: float
    max_usd: float
    grace_minutes: int
    tolerance_pct: float
    tolerance_abs: float
    cryptapi_base: str
    nowpayments_api: str
    brand_name: str = "PAY"
    brand_logo: str = "icons/logo.svg"
    brand_accent: str = "#c8102e"
    brand_accent2: str = "#ff2b3d"
    brand_bg: str = "#000000"
    brand_text: str = "#e8e5df"


def load() -> Config:
    return Config(
        bot_token=_req("BOT_TOKEN"),
        owner_id=int(_req("OWNER_ID")),
        public_base=_req("PUBLIC_BASE").rstrip("/"),
        db_path=_env("DB_PATH", "/data/payram.db"),
        nowpayments_key=_env("NOWPAYMENTS_KEY"),
        nowpayments_ipn_secret=_env("NOWPAYMENTS_IPN_SECRET"),
        alert_chat_id=int(_env("ALERT_CHAT_ID")) if _env("ALERT_CHAT_ID") else None,
        tz=_env("TZ", "Asia/Kolkata"),
        min_usd=float(_env("MIN_USD", "4")),
        max_usd=float(_env("MAX_USD", "10000")),
        grace_minutes=int(_env("GRACE_MINUTES", "10")),
        tolerance_pct=float(_env("TOLERANCE_PCT", "0.99")),
        tolerance_abs=float(_env("TOLERANCE_ABS", "0.50")),
        cryptapi_base=_env("CRYPTAPI_BASE", "https://api.cryptapi.io"),
        nowpayments_api=_env("NOWPAYMENTS_API", "https://api.nowpayments.io/v1"),
        brand_name=_env("BRAND_NAME", "PAY"),
        brand_logo=_env("BRAND_LOGO", "icons/logo.svg"),
        brand_accent=_env("BRAND_ACCENT", "#c8102e"),
        brand_accent2=_env("BRAND_ACCENT2", "#ff2b3d"),
        brand_bg=_env("BRAND_BG", "#000000"),
        brand_text=_env("BRAND_TEXT", "#e8e5df"),
    )
