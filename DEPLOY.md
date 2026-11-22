# Deploy

One container runs Telegram polling, the payment page and both webhooks on port 8090.

You need:

- a host with a public HTTPS name for the page (any reverse proxy)
- a Telegram bot token
- a NOWPayments account for Ethereum, Arbitrum and Base
- nothing for CryptAPI beyond a DNS record

## 1. Telegram

1. @BotFather, `/newbot`, copy the token into `BOT_TOKEN`.
2. Get your numeric id from @userinfobot and put it in `OWNER_ID`.
3. Start the bot and send `/start`. It answers with the menu. If it says *not on the team*,
   `OWNER_ID` is wrong.
4. Add teammates with `/add <id>`, or by replying to their message with `/add`.

Only the owner can add or remove people. Anyone else gets one message containing their id.

## 2. NOWPayments

1. Settings, API keys, create one, put it in `NOWPAYMENTS_KEY`.
2. Settings, Payments, IPN secret, put it in `NOWPAYMENTS_IPN_SECRET`.
3. Set the IPN URL to `https://<your-host>/cb/nowpayments`.
4. Leave underpaid deposits on `partially_paid`. Their dashboard can mark every deposit
   `finished` regardless of amount, which forgives underpayments without telling you.
5. Optionally set a payout address. Without one, funds sit in their custody balance. Check it
   weekly; `/ping` does not report it.

Skip NOWPayments entirely and the bot still works on BSC, Polygon and Solana, which run
through CryptAPI and need no account.

## 3. CryptAPI domain verification

CryptAPI will not issue an address until your callback domain is verified.

1. Open `cryptapi.io/verify_domain`, enter your apex domain, choose DNS TXT.
2. Add the TXT record it shows.
3. Wait for propagation, then verify. One verification covers every subdomain.

Without it `/new` fails with `Please verify your domain before using our service`.

## 4. Public entry and TLS

The app speaks plain HTTP on 8090 and trusts the proxy in front of it. Caddy, nginx, Traefik
or a managed load balancer all work.

```
pay.example.com  ->  127.0.0.1:8090
```

Two requirements:

- forward the original `Host` header; the webhook URL registered with the provider must match
- do not cache `/p/*`; the route already sends `Cache-Control: no-store`

Firewall 8090 so only the proxy reaches it. `/p/<token>` has no login because the token is
the credential, and `/healthz` is open by design.

## 5. Branding

Everything visible comes from env. No rebuild needed, just restart.

| Variable | Effect |
|---|---|
| `BRAND_NAME` | bot menus and the page header |
| `BRAND_LOGO` | path under `web/` for the mark |
| `BRAND_ACCENT` | buttons, stripes, active states |
| `BRAND_ACCENT2` | hover and the urgent timer |
| `BRAND_BG`, `BRAND_TEXT` | page background and body text |

Colours are validated. A non-hex value falls back to the default, so a typo cannot produce a
black-on-black page.

For your own mark, put a square image in `web/icons/` and point `BRAND_LOGO` at it. The
header crops to 26 px.

## 6. Run

```sh
cp .env.example .env
chmod 600 .env
docker compose up -d --build
docker compose logs -f
```

Checks:

```sh
curl -s https://pay.example.com/healthz
# in Telegram
/ping
```

`/ping` calls CryptAPI's converter and NOWPayments' status endpoint. A red line tells you
which gateway is failing before a client does.

## 7. First money test

`/new`, BSC, $4, 30 minutes, CREATE. Open the link on a phone, scan the QR, pay.

Expect the page to flip to PAID and the creator to receive one message.

If nothing arrives within a minute, open `/orders`, pick the order, press REFRESH. That asks
the provider directly. If the provider sees the payment and the page does not, the webhook is
misrouted; check the public URL and the proxy path.

## 8. Backups

A nightly `VACUUM INTO` writes `./data/cryptopay-YYYYMMDD.db` and keeps seven.

```sh
docker compose stop pay
cp data/cryptopay-20260101.db data/cryptopay.db
rm -f data/cryptopay.db-wal data/cryptopay.db-shm
docker compose start pay
```

`data/` holds every order that has not been reconciled yet. Copy it off the host.

## Rules the code enforces

| Rule | Where |
|---|---|
| minimum $4, Ethereum $5, Polygon $0.50 | `pricing.floor_for` |
| paid at 99 percent and no more than $0.50 short | `orders._tolerance_ok` |
| one txid credits one order | `payments.txid` primary key |
| CryptAPI credits only after `/logs/` agrees | `web.cb_cryptapi` |
| NOWPayments needs a valid HMAC-SHA512 | `web.cb_nowpayments` |
| ten minute grace after expiry | `orders.apply` |
| an expired link renders no address | `orders.page_state` |
| seven day links only on CryptAPI | `pricing.expiry_options` |
