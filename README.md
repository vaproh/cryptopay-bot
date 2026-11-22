# cryptopay-bot

A self-hosted crypto checkout for a small team, driven entirely from Telegram.

Someone on your team types an amount in USD, picks a chain, and gets a payment link. They
send that link to the client. The client opens a page, scans a QR, pays. The team member who
created the order gets one message back when the money lands.

No dashboard, no customer accounts, no KYC onboarding, no per-transaction platform account.
One container, one SQLite file, two payment providers behind a routing table.

```
                                   ┌──────────────────┐
  team member ──/new──────────────▶│  Telegram bot    │
                                   │  (allowlist)     │
                                   └────────┬─────────┘
                                            │ creates order
                    ┌───────────────────────┴────────────────────┐
                    ▼                                            ▼
             CryptAPI (BSC, Polygon, Solana)        NOWPayments (ETH, Arbitrum, Base)
                    │  webhook                           │  IPN
                    └───────────────┬────────────────────┘
                                    ▼
                        ┌───────────────────────┐        ┌──────────────┐
   client ──link───────▶│  /p/<token> page      │        │   SQLite     │
                        │  QR · EIP-681 URI     │◀──────▶│  orders,     │
                        └───────────────────────┘        │  payments    │
                                                         └──────────────┘
```

## Features

- **Payment links as buttons.** Chain → amount → expiry → client label, all inline keyboards.
  No typing commands after `/start` (except the amount and the label).
- **Live USD conversion.** Amounts are always entered in dollars; the page shows the token
  amount and encodes it into the QR.
- **A page that survives real customers.** Amount and address QR modes, `EIP-681` and Solana
  Pay URIs, wallet deep links, WalletConnect, and an injected-wallet flow that checks the
  network and balance before it asks the wallet to sign.
- **Money that cannot double-count.** Every credit is keyed on `txid`; provider-reported
  running totals are credited as deltas.
- **Nothing silently unpaid.** A five-minute reconciler re-reads unpaid orders from the
  providers, so a dropped webhook is a delay rather than a lost sale.
- **Terse operator reporting.** `/orders`, `/find`, `/export`, `/ping`, `/stats` in the bot.

## Chains

| Chain | Provider | Asset | Minimum |
|---|---|---|---|
| BNB Smart Chain | CryptAPI | USDT / USDC / BNB | $1 |
| Polygon | CryptAPI | USDT / USDC / POL | $0.50 |
| Solana | CryptAPI | USDT / USDC / SOL | $1 |
| Ethereum | NOWPayments | USDT / USDC / ETH | $5 |
| Arbitrum | NOWPayments | USDT / USDC / ETH / ARB | $1 |
| Base | NOWPayments | USDC / ETH / DAI | $1 |

The routing is a lookup table in `app/pricing.py`; adding a chain is a dataclass and, if it
is a new provider, one adapter. Tron is deliberately absent: at $4.12 of network fee on a $4
ticket it loses money for both sides.

## Quickstart

```sh
git clone https://github.com/<you>/cryptopay-bot.git
cd cryptopay-bot
cp .env.example .env
```

Fill in three things to be running in a minute:

```ini
BOT_TOKEN=123456:ABC...        # @BotFather
OWNER_ID=123456789             # @userinfobot
PUBLIC_BASE=https://pay.example.com
```

Then:

```sh
docker compose up -d --build
```

Send `/start` to the bot. You are the owner. `/new` creates the first order.

The page needs a public HTTPS name; the webhook needs the same. Without NOWPayments
credentials only the CryptAPI chains appear, and that is a complete product on its own.

Full setup — provider accounts, domain verification, TLS, backups — is in
[DEPLOY.md](DEPLOY.md).

## How money is counted

| Situation | Result |
|---|---|
| received ≥ 99% of the quote **and** ≤ $0.50 short | `paid` |
| between 99% and the floor | `partial`, credited, still open for a top-up |
| more than the quote | `overpaid`, credited, flagged |
| arrives after expiry, within 10 minutes | `paid` |
| arrives after expiry, past the grace window | `late_paid`, flagged for manual review |
| below the chain minimum | not credited by the provider at all |
| wrong coin or wrong network | `wrongasset`, manual recovery only |

Both conditions in the first row matter. A flat 99% would accept a $100 loss on a $10,000
invoice.

## Bot commands

| Command | What it does |
|---|---|
| `/start` | main menu with today / 7-day / all-time totals |
| `/new` | create a payment link |
| `/orders` | list, filter by status, owner can see everyone's |
| `/find <text>` | search by label, invoice id, amount or txid |
| `/export [today\|7d\|all]` | CSV of orders to the chat |
| `/quote <chain> <usd>` | current conversion and the chain minimum, without creating anything |
| `/ping` | bot, database, CryptAPI, NOWPayments — with latency |
| `/label <id> <text>` | fix a client label after the fact |
| `/cancel <id>` | stop chasing a pending order |
| `/team`, `/add`, `/remove` | membership, owner only |
| `/help` | command list |

## Configuration

Everything is environment. The important ones:

| Variable | Default | Notes |
|---|---|---|
| `BOT_TOKEN` | — | required |
| `OWNER_ID` | — | required, numeric Telegram id |
| `PUBLIC_BASE` | — | required, no trailing slash |
| `NOWPAYMENTS_KEY` / `NOWPAYMENTS_IPN_SECRET` | empty | empty disables ETH/ARB/Base |
| `MIN_USD` | `4` | global floor, per-chain floors still apply |
| `MAX_USD` | `10000` | above this the bot asks for a second confirmation |
| `TOLERANCE_PCT` / `TOLERANCE_ABS` | `0.99` / `0.50` | both must pass |
| `GRACE_MINUTES` | `10` | late-payment window |
| `BRAND_NAME` / `BRAND_LOGO` | `PAY` / `icons/logo.svg` | bot and page |
| `BRAND_ACCENT` / `BRAND_ACCENT2` | `#c8102e` / `#ff2b3d` | buttons, stripes, timer |
| `BRAND_BG` / `BRAND_TEXT` | `#000000` / `#e8e5df` | page colours |
| `DB_PATH` | `/data/payram.db` | volume this |
| `TZ` | `Asia/Kolkata` | "today" in the bot and the 09:00 summary |

## Layout

```
app/
  config.py      env loading and validation
  db.py          sqlite schema, idempotent writes
  pricing.py     chains, floors, expiry rules, payment URIs
  providers.py   CryptAPI and NOWPayments adapters
  orders.py      create, credit, classify, expire, reconcile
  bot.py         telegram UI
  web.py         /p/<token>, /cb/*, /healthz
  scheduler.py   expiry sweep, reconcile, daily summary, backup
  main.py        wiring
web/
  pay.html       the checkout page (single file, no build)
  qrcode.js      vendored QR generator, works offline
  icons/         chain marks, token marks, wallet marks, default logo
tests/
  test_rules.py  the money rules
  test_web.py    page and webhook surface
  test_flow.py   the /new conversation
```

No frontend build step. `pay.html` is opened directly by tests and served untouched except
for two injections.

## Security model

- The bot is allowlisted by Telegram id. Unknown users get one message and nothing else.
- `/p/<token>` is unauthenticated by design; the 128-bit token is the credential. Orders
  expire, and an expired link renders no address.
- The page never broadcasts without `?live=1&addr=<real>`, so a placeholder order cannot
  move funds.
- CryptAPI callbacks are unauthenticated, so the body is treated as a hint: the order is
  credited only after `/logs/` agrees.
- NOWPayments IPNs must carry a valid HMAC-SHA512 over the raw body.
- Secrets live in `.env` only, `chmod 600`, never in the image or the repo.

Read [SECURITY.md](SECURITY.md) before exposing it, and note what it says about running
this for strangers — the threat model here is "a handful of trusted operators", not
"an exchange".

## Development

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

The page can be previewed without the backend:

```sh
python3 -m http.server 8123 --directory web
# http://127.0.0.1:8123/pay.html?chain=bsc&usd=40&t=900&total=1800
```

`web/README.md` documents every query parameter and every page state.

## Contributing

Issues and pull requests are welcome. Please run `pytest` and `ruff check .` before opening
one, and keep the money rules in `app/orders.py` covered by a test — those are the parts
where a regression costs real money.

## License

MIT. See [LICENSE](LICENSE).

The wallet and chain marks in `web/icons/` belong to their respective owners and are used
only to identify those wallets and networks.
