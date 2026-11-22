# PRD — cryptopay-bot

Version 1.0 · Status: shipped

## Problem

A small team sells work over Telegram and gets paid in USDT. The existing options are wrong
for the size of the business:

- **Hosted checkouts** (NOWPayments invoices alone) work, but every link has to be created
  by hand in a dashboard and the fee is 1–1.5% with a $5 floor on Ethereum.
- **Self-hosted processors** (BTCPay, PayRam) are built for merchants with a store, a
  dashboard and a server per chain. Heavy for four people and one chat.
- **Doing nothing** means asking clients to send to a personal wallet and then checking a
  block explorer by hand, which loses track of who paid for what.

What is missing is the middle: a link generator a non-technical teammate can operate from
the app they already have open, that produces a page good enough to send a client, and that
tells the right person the moment money arrives.

## Users

| Who | Need |
|---|---|
| **Owner** | add/remove teammates, see all orders, know the bot and both gateways are alive |
| **Team member** | create a link in under 20 seconds, from a phone, without learning a dashboard |
| **Client** | a page that opens fast, shows one amount, one address, and how long they have |

Non-user: the client never talks to the bot. They receive a URL and nothing else.

## Scope of v1

In scope:

- one payment link per order, one chain per link
- USD-denominated amounts, converted at creation
- six chains across two providers
- a public payment page with QR, address, wallets, countdown, and nine payment states
- payment detection by webhook **and** reconciliation
- notifications to the creating teammate
- owner-only membership management
- CSV export, search, daily summary, nightly backup

Explicitly out of scope for v1:

- customer accounts or a shop with a cart
- recurring invoices and subscriptions
- refunds (neither provider exposes one)
- multi-currency pricing (USD only)
- a web dashboard
- multiple owners or granular roles

## Core flow

1. Teammate sends `/new`.
2. Bot asks for the chain. Presets that cannot meet the floor for the amount are hidden.
3. Bot asks for the amount in USD. Free text; the per-chain floor is validated server-side.
4. Bot asks how long the link lives: 30 minutes, 2 hours, 24 hours, and 7 days on CryptAPI.
5. Bot asks for an optional client label, e.g. an invoice number.
6. Bot shows a summary and a create button.
7. On create: the provider is called, an order row is written, and the bot replies with the
   link.
8. Teammate sends the link to the client.
9. Client pays. Webhook or reconciler credits the order; the creator is notified once.

## Requirements

### Functional

| # | Requirement |
|---|---|
| F1 | A link must never be created below the chain minimum |
| F2 | The amount is entered in USD and converted once, at creation |
| F3 | Each order gets a unique, unguessable token and a sequential invoice number |
| F4 | Expiry is enforced server-side; an expired link renders no address |
| F5 | Payments credit once per txid |
| F6 | Underpayment is `paid` only at ≥99% and ≤$0.50 short |
| F7 | Multiple partial payments accumulate toward one order |
| F8 | A payment after expiry within the grace window is `paid`; after it, `late_paid` |
| F9 | Every status change notifies the order's creator exactly once |
| F10 | If the creator blocked the bot, the alert goes to `ALERT_CHAT_ID` |
| F11 | Unpaid orders are reconciled against the provider every five minutes |
| F12 | Only the owner can add or remove members |
| F13 | The page shows the real received amount, not a placeholder |

### Non-functional

| # | Requirement |
|---|---|
| N1 | The checkout page fits one screen at 360×640 without scrolling |
| N2 | The page works with JavaScript partially blocked: address and QR still render |
| N3 | A QR must decode with a standard scanner at every chain and both QR modes |
| N4 | The bot must answer `/ping` in under two seconds on a slow link |
| N5 | No secret appears in the image, the repo, or Telegram messages |
| N6 | The database survives a hard kill: WAL, single writer, idempotent inserts |
| N7 | A dropped webhook costs at most five minutes of delay |
| N8 | Restarting the process loses no order state; in-progress drafts may be lost |

## Payment states

```
pending ──▶ partial ──▶ paid
   │            │
   │            └────▶ overpaid
   ├──▶ expired ──▶ late_paid
   ├──▶ cancelled
   ├──▶ underpaid        (below the chain minimum)
   ├──▶ wrongasset       (wrong coin or network)
   └──▶ failed           (provider rejected the create call)
```

`confirming` is transient: seen on-chain, not yet at the confirmation threshold.

## Acceptance criteria

v1 is accepted when, on a fresh host:

1. `/new` for each of the six chains produces a link whose page opens over HTTPS and shows
   the right chain, asset and amount.
2. Paying a BSC order in full flips the page to `PAID` and sends one notification.
3. Sending 60% of a Polygon order produces `PART PAID` with the exact remainder, and a
   second transfer that completes it produces `PAID`, not `OVERPAID`.
4. Killing the web process for two minutes during a payment still results in `PAID` after
   the reconciler runs.
5. A link opened after expiry shows `LINK DEAD` and no address.
6. `/export 7d` returns a CSV that opens in a spreadsheet.
7. `pytest` passes on a clean checkout, and the container starts with only `BOT_TOKEN`,
   `OWNER_ID` and `PUBLIC_BASE` set.

## Success measures

- median time from `/new` to link delivered: under 30 seconds
- orders stuck in `pending` past expiry with no operator action: near zero
- unreconciled payments (money in, order not credited): zero
- duplicated credits: zero

## Risks

| Risk | Mitigation |
|---|---|
| Provider drops a webhook | five-minute reconciler |
| CryptAPI address stays payable after expiry | grace window, `late_paid` state, alert |
| NOWPayments custody holds funds | payout address documented in DEPLOY |
| Underpayment on a large invoice | absolute cap on the tolerance, not a flat percentage |
| Wrong-chain transfer | QR carries the chain and asset; page names the network; `wrongasset` state |
| Operator error (typo in amount) | summary screen before create, max amount confirmation |

## v1.1 candidates

Recurring invoices, a shared team chat as a second notification target, per-chain fee
display, refund tracking as a label rather than an action.
