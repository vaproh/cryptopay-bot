# cryptopay-bot

A small crypto checkout driven from Telegram. One teammate types an amount, picks a chain,
and gets a payment link to send the client. When money arrives, the person who made the link
gets a message.

There is no customer login, no dashboard and no shop. One container, one SQLite file, two
payment providers.

```
team member  --/new-->  bot  -->  order
                                   |
              CryptAPI (BSC, Polygon, Solana)   NOWPayments (ETH, Arbitrum, Base)
                                   |
client  --link-->  /p/<token>  -->  page with QR and address
                                   |
                       webhook or 5-minute reconcile  -->  SQLite  -->  notification
```

## Chains

| Chain | Provider | Asset | Minimum |
|---|---|---|---|
| BNB Smart Chain | CryptAPI | USDT, USDC, BNB | $1 |
| Polygon | CryptAPI | USDT, USDC, POL | $0.50 |
| Solana | CryptAPI | USDT, USDC, SOL | $1 |
| Ethereum | NOWPayments | USDT, USDC, ETH | $5 |
| Arbitrum | NOWPayments | USDT, USDC, ETH, ARB | $1 |
| Base | NOWPayments | USDC, ETH, DAI | $1 |

Routing lives in `app/pricing.py`. Adding a chain is one dataclass entry, plus an adapter if
it uses a new provider. Tron is not included: $4.12 of network fee on a $4 payment loses
money on both sides.

## Quickstart

```sh
git clone https://github.com/vaproh/cryptopay-bot.git
cd cryptopay-bot
cp .env.example .env
```

Three values are required:

```ini
BOT_TOKEN=123456:ABC...        # @BotFather
OWNER_ID=123456789             # @userinfobot
PUBLIC_BASE=https://pay.example.com
```

```sh
docker compose up -d --build
```

Send `/start` to the bot. You are the owner. `/new` makes the first link.

The page and the webhooks need a public HTTPS hostname. Without NOWPayments credentials the
bot still runs on the three CryptAPI chains.

Provider setup, TLS and backups: [DEPLOY.md](DEPLOY.md).

## How payments are counted

| Situation | Result |
|---|---|
| received at least 99% of the quote and no more than $0.50 short | `paid` |
| short by more than that | `partial`, credited, link stays open |
| more than the quote | `overpaid`, credited, flagged |
| arrives after expiry within 10 minutes | `paid` |
| arrives later than the grace window | `late_paid`, flagged for review |
| below the chain minimum | provider ignores it |
| wrong coin or wrong network | `wrongasset`, manual recovery |

Both conditions in the first row are required. A flat 99% would accept a $100 loss on a
$10,000 invoice.

## Commands

| Command | Effect |
|---|---|
| `/start` | menu with today, 7-day and all-time totals |
| `/new` | create a link |
| `/orders` | list orders, filter by status |
| `/find <text>` | search label, invoice, amount or txid |
| `/export [today\|7d\|all]` | CSV to the chat |
| `/quote <chain> <usd>` | current conversion and the chain minimum |
| `/ping` | bot, database, CryptAPI, NOWPayments, with latency |
| `/label <id> <text>` | change a client label |
| `/cancel <id>` | stop chasing a pending order |
| `/team`, `/add`, `/remove` | membership, owner only |
| `/help` | command list |

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `BOT_TOKEN` | | required |
| `OWNER_ID` | | required |
| `PUBLIC_BASE` | | required, no trailing slash |
| `NOWPAYMENTS_KEY`, `NOWPAYMENTS_IPN_SECRET` | empty | empty disables ETH, ARB and Base |
| `MIN_USD` | `4` | global floor; chain floors still apply |
| `MAX_USD` | `10000` | above this the bot asks again |
| `TOLERANCE_PCT`, `TOLERANCE_ABS` | `0.99`, `0.50` | both must pass |
| `GRACE_MINUTES` | `10` | late payment window |
| `BRAND_NAME`, `BRAND_LOGO` | `PAY`, `icons/logo.svg` | bot and page |
| `BRAND_ACCENT`, `BRAND_ACCENT2` | `#c8102e`, `#ff2b3d` | buttons, timer |
| `BRAND_BG`, `BRAND_TEXT` | `#000000`, `#e8e5df` | page colours |
| `DB_PATH` | `/data/cryptopay.db` | put a volume here |
| `TZ` | `Asia/Kolkata` | decides what "today" means |

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
  pay.html       checkout page, single file, no build
  qrcode.js      vendored QR generator
  icons/         chain, token and wallet marks
tests/
  test_rules.py  money rules
  test_web.py    page and webhook surface
  test_flow.py   the /new conversation
```

## Security

- The bot answers only to Telegram ids in the users table. Anyone else gets one message.
- `/p/<token>` has no login. The 128-bit token is the credential, and orders expire.
- The page cannot broadcast without `?live=1&addr=<real address>`.
- CryptAPI callbacks are unsigned, so the body is treated as a hint and the order is credited
  only after `/logs/` agrees.
- NOWPayments callbacks must carry a valid HMAC-SHA512.
- Secrets live in `.env` only.

Read [SECURITY.md](SECURITY.md) before exposing this to real money. It is built for a small
team, not for anonymous customers.

## Development

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

Preview the page without the backend:

```sh
python3 -m http.server 8123 --directory web
# http://127.0.0.1:8123/pay.html?chain=bsc&usd=40&t=900&total=1800
```

`web/README.md` lists every query parameter and page state.

## Contributing

Run `pytest` and `ruff check .` before opening a pull request. Changes to `app/orders.py`
need a test: that file decides whether money is credited.

## License

MIT, see [LICENSE](LICENSE). The wallet and chain marks in `web/icons/` belong to their
owners and identify those wallets and networks.
