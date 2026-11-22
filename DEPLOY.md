# Deploy

One container: Telegram polling + the payment page + both webhooks, on port 8090.

You need:

- a host with a public HTTPS name for the payment page (any reverse proxy will do)
- a Telegram bot token
- a NOWPayments account (for Ethereum / Arbitrum / Base)
- nothing for CryptAPI beyond verifying your domain

---

## 1. Telegram

1. @BotFather → `/newbot` → copy the token into `BOT_TOKEN`.
2. Your numeric id (from @userinfobot) → `OWNER_ID`.
3. Start the bot, send `/start`. It must answer with the menu. If it says *not on the team*,
   `OWNER_ID` is wrong.
4. `/add <id>` for each team member, or reply to their message with `/add`.

Only the owner can add or remove people. Everyone else sees a single message with their id.

## 2. NOWPayments

1. Settings → API keys → create one → `NOWPAYMENTS_KEY`.
2. Settings → Payments → **IPN secret** → `NOWPAYMENTS_IPN_SECRET`.
3. Set the IPN URL to `https://<your-host>/cb/nowpayments`.
4. Leave underpaid deposits on **partially_paid**. Their dashboard can auto-mark every
   deposit `finished` regardless of the amount, which silently forgives underpayments.
5. Optionally set a payout address. Otherwise funds accumulate in their custody balance;
   `/ping` does not show it, so check the dashboard weekly.

If you skip NOWPayments entirely the bot still works for BSC, Polygon and Solana — those
use CryptAPI, which needs no account.

## 3. CryptAPI domain verification

CryptAPI refuses to issue an address until your callback domain is verified.

1. Open `cryptapi.io/verify_domain`, enter your apex domain, pick DNS TXT.
2. Add the TXT record it prints.
3. Wait for propagation, then verify. One verification covers every subdomain.

Without it `/new` fails with `Please verify your domain before using our service`.

## 4. Public entry and TLS

The app speaks plain HTTP on 8090 and trusts whatever proxy is in front of it. Put any
TLS-terminating proxy there — Caddy, nginx, Traefik, or a managed one.

```
pay.example.com  ->  127.0.0.1:8090
```

Two things the proxy must do:

- pass the original `Host` (the page builds absolute links from `PUBLIC_BASE`, but the
  webhook URL is registered with the provider, so it must match)
- **not** cache `/p/*`: the route already sends `Cache-Control: no-store`

Firewall 8090 so only the proxy can reach it. The app has no auth on `/p/<token>` — the
token *is* the auth — and no auth at all on `/healthz`.

## 5. Branding

Everything visible is env, no rebuild:

| var | effect |
|---|---|
| `BRAND_NAME` | bot menus and the page header |
| `BRAND_LOGO` | path under `web/` for the mark (SVG or JPG) |
| `BRAND_ACCENT` | buttons, stripes, active states |
| `BRAND_ACCENT2` | hover and the urgent timer |
| `BRAND_BG`, `BRAND_TEXT` | page background and body text |

Values are validated: anything that isn't a hex colour falls back to the default, so a typo
cannot render the page black-on-black. Restart the container after changing them.

To use your own mark, drop a file into `web/icons/` and point `BRAND_LOGO` at it. Square
images work best; the header crops to 26 px.

## 6. Run

```sh
cp .env.example .env
chmod 600 .env
docker compose up -d --build
docker compose logs -f
```

Checks:

```sh
curl -s https://pay.example.com/healthz     # ok
# in Telegram: /ping                        # every line green
```

`/ping` calls CryptAPI's converter and NOWPayments' status endpoint, so a red line tells you
which gateway is down before a customer complains.

## 7. First money test

`/new` → BSC → $4 → 30 min → CREATE. Open the link, scan the QR from a phone, pay.

Expect: the page flips to `PAID` and the creator gets exactly one notification.

If nothing arrives within a minute: `/orders` → the order → `REFRESH`. That calls the
provider's own API. If the provider sees the payment and the page does not, the webhook is
misconfigured — check the public URL and the HAProxy/proxy path.

## 8. Backups

A nightly `VACUUM INTO` lands in `./data/payram-YYYYMMDD.db`, seven kept. Restore:

```sh
docker compose stop pay
cp data/payram-20260101.db data/payram.db
rm -f data/payram.db-wal data/payram.db-shm
docker compose start pay
```

Losing `data/` means losing every order that has not been reconciled yet. Copy it off the
host.

## Rules the code enforces

| Rule | Where |
|---|---|
| minimum $4, Ethereum $5, Polygon $0.50 | `pricing.floor_for` |
| paid at **≥99% and ≤$0.50 short** | `orders._tolerance_ok` |
| one txid credits once | `payments.txid` primary key |
| CryptAPI callbacks are unauthenticated, so credit only after `/logs/` agrees | `web.cb_cryptapi` |
| NOWPayments IPN must carry a valid HMAC-SHA512 | `web.cb_nowpayments` |
| 10 minute grace after expiry | `orders.apply` |
| a link past expiry renders no address | `orders.page_state` |
| seven-day links only on CryptAPI | `pricing.expiry_options` |
