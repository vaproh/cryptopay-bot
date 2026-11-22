# AGENTS.md

Read this before changing code in this repository.

## What this is

A Telegram bot that issues crypto payment links, and the static page clients pay on.
Python 3.12, FastAPI, python-telegram-bot, SQLite. One process, no frontend build.

This code credits payments. A clean-looking change that miscounts one is worse than no
change at all.

## Commands

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
ruff check .

# page preview, no backend needed
python3 -m http.server 8123 --directory web
# http://127.0.0.1:8123/pay.html?chain=bsc&usd=40&t=900&total=1800

# container
docker compose up -d --build
```

Tests must pass without a bot token or network. If a change needs either, document a manual
check in the pull request instead of wiring it into CI.

## Invariants

1. **One credit per txid.** `payments.txid` is the primary key. New credit paths go through
   `db.add_payment` or `db.upsert_payment`.
2. **Tolerance is two conditions.** `received >= quote * 0.99` and
   `received >= quote - 0.50`. Do not replace it with one percentage.
3. **CryptAPI webhooks are unsigned.** The body is a hint; credit only after `/logs/`
   confirms. Do not start trusting the callback.
4. **NOWPayments IPN needs a valid HMAC** over the raw body bytes, not a re-serialised dict.
5. **Expiry is enforced on the server.** `page_state` decides. An expired link must not
   render an address.
6. **Do not invent states.** The nine in `orders.STATUS_MAP` are what the page styles; a new
   one needs page work too.
7. **The page never broadcasts** without `?live=1&addr=<real>`.
8. **No secrets in the repository.** Everything comes from env.

## Where code lives

| File | Owns |
|---|---|
| `app/config.py` | env, validation, defaults |
| `app/db.py` | schema, all SQL, idempotent helpers |
| `app/pricing.py` | chains, floors, expiry windows, payment URIs |
| `app/providers.py` | HTTP to CryptAPI and NOWPayments, IPN signature |
| `app/orders.py` | create, credit, classify, expire, reconcile |
| `app/bot.py` | Telegram UI only, no SQL and no HTTP |
| `app/web.py` | routes, page injection, webhook auth |
| `app/scheduler.py` | timers |
| `web/pay.html` | the page: markup, styles, behaviour, all states |
| `web/README.md` | page parameters and states |

`bot.py` calls `orders.py`. It does not talk to providers or the database directly.

## Style

- Match what is there: small functions, dataclasses for values, no ORM.
- No new dependency for something the standard library does. `httpx` and FastAPI are already
  present; do not add a second HTTP client, a queue or a cache.
- Comments explain why, one line.
- User-facing copy is short and factual: `LINK DEAD`, `PART PAID`, `Send 3.16 USDT more.`
  No em dashes, no hedging, no restating what the reader can see.
- The page has no border-radius, no gradients and no shadows. Keep it that way.
- Documentation is plain prose and tables. No marketing tone, no em dashes.

## Tests

| Area | File |
|---|---|
| tolerance, classification, crediting, expiry | `tests/test_rules.py` |
| page rendering, webhook auth, static files | `tests/test_web.py` |
| the `/new` conversation and guards | `tests/test_flow.py` |

A change to money logic without a test is unfinished.

## Before opening a pull request

- [ ] `pytest -q` and `ruff check .` pass
- [ ] no credential, token or personal domain in any tracked file
- [ ] money still credits once and only once
- [ ] the page fits 360x640 and 390x844 (`scrollHeight <= innerHeight`)
- [ ] QR payloads decode (`zbarimg` on a screenshot of `#qrShell`)
- [ ] README, DEPLOY or web/README updated if behaviour changed

## Known behaviour that looks like a bug

- A CryptAPI address stays payable after expiry. There is no revoke call. That is why the
  grace window and `late_paid` exist.
- A CryptAPI callback with no matching order is dropped on purpose.
- `partially_paid` on NOWPayments is terminal: they keep the funds, so the page must not
  offer a top-up.
- Only CryptAPI offers seven-day links. NOWPayments expires invoices on its side.
- If Telegram auth fails at startup the process keeps serving the page and webhooks and
  retries polling every 30 seconds. That is intended.
