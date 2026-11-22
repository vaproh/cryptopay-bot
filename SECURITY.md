# Security

## Reporting

Open a private security advisory on the repository. Do not file a public issue for anything
that could move funds or leak an address.

Include what you did, what happened, and the smallest reproduction you have.

## Threat model

This is a small team's tool on a host the team controls. It is not hardened for anonymous
customers at scale and it is not a custodial service.

Trusted:

- the operator and the teammates the owner added
- the host, its reverse proxy, and the two providers

Not trusted:

- anyone who finds `/p/<token>`
- CryptAPI callback bodies, which are unsigned by design
- the client's browser

## Controls

| Asset | Control |
|---|---|
| Bot access | numeric-id allowlist; unknown users get one message |
| Order links | 128-bit random token, expiring |
| Crediting | txid primary key; CryptAPI credited only after `/logs/` agrees |
| NOWPayments callbacks | HMAC-SHA512 over the raw body |
| Secrets | env only, `.env` gitignored, never logged or sent to Telegram |
| Client data | a free-text label the operator typed; no emails, no KYC, no accounts |
| Page caching | `Cache-Control: no-store` on `/p/*` |
| Referrer leak | `referrer: no-referrer`, so the invoice URL stays out of third-party requests |

## Known limits

- **A CryptAPI address stays payable after the order expires.** There is no revoke call.
  Late money is detected, marked `late_paid`, and forwarded to your wallet by CryptAPI.
- **`/healthz` is unauthenticated.** It returns uptime only.
- **No rate limiting on `/p/<token>`.** Tokens are unguessable, but a client can poll their
  own link.
- **WalletConnect loads its SDK from a CDN** when that tile is tapped. Bundle it if you do not
  want third-party JavaScript on a checkout page.
- **Telegram is the identity provider.** Anyone who controls a teammate's Telegram account
  can create links. There is no second factor.
- **The page has no CSRF surface** because it performs no actions, only rendering.

## Before going live

- [ ] `.env` is `chmod 600`
- [ ] the app port accepts traffic from the proxy only
- [ ] TLS terminates in front; the app never receives plain HTTP from the internet
- [ ] `data/` is backed up off-host and not served by any web server
- [ ] provider dashboards have 2FA
- [ ] `ALERT_CHAT_ID` points at a channel someone reads
- [ ] `/ping` is checked routinely, not only at setup

## Out of scope

Reports about paying an expired address, the absence of refunds, or provider fees describe
known behaviour documented in `DEPLOY.md` and `web/README.md`.
