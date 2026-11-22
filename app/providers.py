import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx


class ProviderError(RuntimeError):
    pass


@dataclass
class Created:
    address: str
    ref: str
    quote: float          # asset units the customer should send
    raw: dict


class CryptAPI:
    """No account, no key. Callbacks are hints; /logs/ is the source of truth."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    async def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base}/{path}"
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url, params=params)
        except httpx.HTTPError as e:
            raise ProviderError(f"cryptapi unreachable: {e}") from e
        if r.status_code >= 400:
            raise ProviderError(f"cryptapi {r.status_code}: {r.text[:160]}")
        body = r.json()
        if str(body.get("status", "")).lower() not in ("success", ""):
            raise ProviderError(f"cryptapi: {body.get('error', body)}")
        return body

    async def convert(self, ticker: str, usd: float) -> float:
        body = await self._get(f"{ticker}/convert/", {"value": f"{usd:.2f}", "from": "USD"})
        return float(body["value_coin"])

    async def create(self, ticker: str, callback: str) -> Created:
        body = await self._get(f"{ticker}/create/", {
            "callback": callback,
            "pending": 1,      # 0-conf webhooks, so the page can show "seen"
            "convert": 1,      # callback carries fiat value
            "multi_token": 1,  # one EVM address accepts any supported asset
        })
        addr = body.get("address_in")
        if not addr:
            raise ProviderError("cryptapi returned no address_in")
        return Created(address=addr, ref=body.get("callback", callback), quote=0.0, raw=body)

    async def logs(self, ticker: str, callback: str) -> list[dict]:
        body = await self._get(f"{ticker}/logs/", {"callback": callback})
        data = body.get("data")
        return data if isinstance(data, list) else []


class NowPayments:
    def __init__(self, api: str, key: str):
        self.api = api.rstrip("/")
        self.key = key

    async def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self.key:
            raise ProviderError("nowpayments key not set")
        headers = {"x-api-key": self.key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.request(method, f"{self.api}/{path}", headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise ProviderError(f"nowpayments unreachable: {e}") from e
        if r.status_code >= 400:
            raise ProviderError(f"nowpayments {r.status_code}: {r.text[:160]}")
        return r.json()

    async def create(self, *, usd: float, pay_currency: str, order_id: str,
                     ipn_url: str, description: str) -> Created:
        body = await self._call("POST", "payment", {
            "price_amount": round(usd, 2),
            "price_currency": "usd",
            "pay_currency": pay_currency,
            "order_id": order_id,
            "order_description": description[:200],
            "ipn_callback_url": ipn_url,
        })
        addr = body.get("pay_address")
        ref = body.get("payment_id")
        if not addr or not ref:
            raise ProviderError("nowpayments returned no pay_address")
        return Created(address=addr, ref=str(ref),
                       quote=float(body.get("pay_amount") or usd), raw=body)

    async def get(self, payment_id: str) -> dict:
        return await self._call("GET", f"payment/{payment_id}")

    async def status(self) -> dict:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{self.api}/status")
        if r.status_code >= 400:
            raise ProviderError(f"nowpayments status {r.status_code}")
        return r.json()

    def verify_ipn(self, raw: bytes, signature: str | None, secret: str) -> bool:
        if not signature or not secret:
            return False
        try:
            payload = json.loads(raw)
        except ValueError:
            return False
        body = json.dumps(dict(sorted(payload.items())), separators=(",", ":"))
        digest = hmac.new(secret.encode(), body.encode(), hashlib.sha512).hexdigest()
        return hmac.compare_digest(digest, signature.strip())


def callback_url(base: str, provider: str, token: str) -> str:
    return f"{base}/cb/{provider}?{urlencode({'o': token})}"
