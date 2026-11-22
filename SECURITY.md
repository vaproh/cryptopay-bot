# Security

## Reporting

Open a private security advisory on the repository, or email the maintainer listed there.
Please do not file a public issue for anything that could move funds or leak an address.

Include: what you did, what happened, and the smallest reproduction you have.

## Threat model

This is a tool for a small team, run on a host the team controls. It is **not** hardened for
accepting payments from strangers at scale, and it is not a custodial service.

Trusted:

- the operator and the teammates the owner added
- the host, its reverse proxy, and the providers (CryptAPI, NOWPayments)

Not trusted:

- anyone on the internet who finds `/p/<token>`
- callback bodies from CryptAPI (unsigned by design)
- anything in the client's browser

## What is protected, and how

| Asset | Control |
|---|---|
| Bot access | numeric-id allowlist; unknown users get one message |
| Order links | 128-bit random token; unguessable, expiring |
| Payment crediting | txid primary key; CryptAPI credited only after `/logs/` agrees |
| NOWPayments IPNs | HMAC-SHA512 over the raw body |
| Secrets | env only; `.env` is gitignored; never logged or echoed to Telegram |
| Client data | a free-text label the operator typed; no emails, no KYC, no customer accounts |
| Page caching | `Cache-Control: no-store` on `/p/*` |
| Referrer leakage | `referrer: no-referrer`, so the invoice URL is not sent to the WalletConnect CDN |

## Known limits

- **A CryptAPI address stays payable after the order expires.** There is no revoke call.
  Late money is detected, marked `late_paid`, and forwarded to your wallet by CryptAPI; it
  is not silently kept.
- **`/healthz` is unauthenticated.** It reveals uptime only.
- **No rate limiting** on `/p/<token>`. Tokens are unguessable, but a hostile client can
  still poll their own link.
- **No CSRF protection on the page** — it takes no actions, only renders.
- **WalletConnect loads its SDK from a CDN** when the tile is tapped. Bundle it for a public
  deployment if you do not want a third-party script on your checkout.
- **Telegram is the identity provider.** Compromise of a teammate's Telegram account is
  compromise of their ability to create links. There is no second factor.

## Hardening checklist for a public deployment

- [ ] `.env` is `chmod 600` and not readable by other users
- [ ] the app port binds to the proxy only, never `0.0.0.0` on a public interface
- [ ] TLS terminates in front; the app never sees plain HTTP from the internet
- [ ] `data/` is backed up off-host and not served by any web server
- [ ] dashboard access at the providers has 2FA
- [ ] `ALERT_CHAT_ID` points at a channel you actually read
- [ ] `/ping` is part of the team's routine, not just the first setup

## Out of scope

Reports about the theoretical ability to pay an expired address, the absence of refunds, or
the fees charged by the providers are known behaviour, documented in `DEPLOY.md` and
`web/README.md`.
