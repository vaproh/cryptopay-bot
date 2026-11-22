# AGENTS.md

Instructions for coding agents working in this repository. Read this before changing code.

## What this is

A Telegram bot that issues crypto payment links, plus the static page the client pays on.
Python 3.12, FastAPI, python-telegram-bot, SQLite. One process. No frontend build.

Money moves through this code. A plausible-looking change that miscounts a payment is worse
than no change.

## Commands

```sh
# tests (all three suites, no network, no credentials)
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q

# lint
ruff check .

# page preview without the backend
python3 -m http.server 8123 --directory web
# http://127.0.0.1:8123/pay.html?chain=bsc&usd=40&t=900&total=1800

# container
docker compose up -d --build
```

Tests must pass without a bot token. If a change needs one, it belongs in a manual check
documented in the PR, not in CI.

## Invariants — do not break these

1. **Credit once per txid.** `payments.txid` is the primary key. Any new path that credits
   an order goes through `db.add_payment` or `db.upsert_payment`.
2. **Tolerance is two conditions.** `received >= quote * 0.99` **and**
   `received >= quote - 0.50`. Never replace it with a single percentage.
3. **CryptAPI webhooks are unauthenticated.** The body is a hint. Credit only after
   `/logs/` confirms. Do not "optimise" this into trusting the callback.
4. **NOWPayments IPN needs a valid HMAC.** Verify against the raw body bytes, not a
   re-serialised dict.
5. **Expiry is enforced server-side.** `page_state` decides; the browser countdown is
   decoration. An expired link must not render an address.
6. **Never invent a payment state.** The nine states in `orders.STATUS_MAP` are what the
   page styles; a new one needs a page state too.
7. **The page never broadcasts** without `?live=1&addr=<real>`.
8. **No secrets in the repo.** Everything comes from env. `.env` is gitignored.

## Where things live

| File | Owns |
|---|---|
| `app/config.py` | env, validation, defaults |
| `app/db.py` | schema, all SQL, idempotent helpers |
| `app/pricing.py` | chains, floors, expiry windows, payment URIs |
| `app/providers.py` | HTTP to CryptAPI and NOWPayments, IPN signature |
| `app/orders.py` | the money logic: create, credit, classify, expire, reconcile |
| `app/bot.py` | Telegram UI only — no SQL, no HTTP |
| `app/web.py` | routes, page injection, webhook auth |
| `app/scheduler.py` | timers |
| `web/pay.html` | the page: markup, styles, behaviour, all states |
| `web/README.md` | page parameters and state reference |

Keep the boundaries. `bot.py` calls `orders.py`; it does not talk to providers or the
database directly.

## Style

- Match the surrounding code: small functions, dataclasses for values, no ORM.
- No new dependencies for something the standard library does. `httpx` and FastAPI are
  already there; do not add a second HTTP client, a queue, or a cache.
- Comments explain *why*, one line. Do not narrate the obvious.
- User-facing copy is terse and factual: `LINK DEAD`, `PART PAID`, `Send 3.16 USDT more.`
  No em dashes, no hedging, no explaining what the reader can see.
- The page has zero border-radius, zero gradients and no shadows. That is deliberate.

## Testing expectations

Add or extend a test when you touch:

| Area | Test file |
|---|---|
| tolerance, classification, crediting, expiry | `tests/test_rules.py` |
| page rendering, webhook auth, static assets | `tests/test_web.py` |
| the `/new` conversation and guards | `tests/test_flow.py` |

A change to money logic without a test is an incomplete change.

## Review checklist

- [ ] `pytest -q` and `ruff check .` pass
- [ ] no credential, token or personal domain added to any tracked file
- [ ] money paths still credit once and only once
- [ ] the page still fits 360×640 and 390×844 (`scrollHeight <= innerHeight`)
- [ ] QR payloads still decode (`zbarimg` on a screenshot of `#qrShell`)
- [ ] `README.md`, `DEPLOY.md` or `web/README.md` updated if behaviour changed

## Things that look like bugs but are not

- The address is still payable after expiry. CryptAPI has no revoke call; that is why the
  grace window and `late_paid` exist.
- A CryptAPI callback arriving with no matching order is dropped on purpose.
- `partially_paid` on NOWPayments is terminal: they keep the funds, so the page must not
  invite a top-up.
- Only CryptAPI offers seven-day links; NOWPayments expires invoices on their side.
