# PRD: cryptopay-bot

Version 1.0. Shipped.

## Problem

A small team sells work over Telegram and gets paid in USDT.

Hosted checkouts work, but every link has to be created in a dashboard by hand, and the fee
is 1 to 1.5 percent with a $5 floor on Ethereum. Self-hosted processors such as BTCPay and
PayRam assume a store, a dashboard and a server per chain. Both are more than four people
and one chat need. Sending clients a personal wallet address instead loses track of which
payment belongs to which job.

What is needed: a link a teammate can create from the app they already have open, a page
good enough to send a client, and a message to the right person when the money arrives.

## Users

| User | Needs |
|---|---|
| Owner | add and remove teammates, see every order, know both gateways are up |
| Teammate | create a link in under 20 seconds, from a phone |
| Client | one amount, one address, a clear deadline |

The client never talks to the bot. They receive a URL.

## Scope of v1

In scope:

- one link per order, one chain per link
- amounts in USD, converted once at creation
- six chains across two providers
- a checkout page with QR, address, wallet options, countdown and eleven states
- payment detection by webhook and by reconciliation
- notification to the teammate who created the order
- owner-only membership management
- CSV export, search, daily summary, nightly backup

Out of scope:

- customer accounts or a cart
- recurring invoices and subscriptions
- refunds; neither provider exposes one
- currencies other than USD
- a web dashboard
- multiple owners or extra roles

## Flow

1. Teammate sends `/new`.
2. Bot asks for the chain.
3. Bot asks for the amount in USD. Free text, validated against the chain floor.
4. Bot asks for a lifetime: 30 minutes, 2 hours, 24 hours, or 7 days on CryptAPI.
5. Bot asks for an optional client label, such as an invoice number.
6. Bot shows a summary and a create button.
7. On create: provider called, order written, link returned.
8. Teammate sends the link to the client.
9. Client pays. Webhook or reconciler credits the order. Creator is notified once.

## Requirements

### Functional

| # | Requirement |
|---|---|
| F1 | A link is never created below the chain minimum |
| F2 | Amount is entered in USD and converted once |
| F3 | Every order gets a random token and a sequential invoice number |
| F4 | Expiry is enforced on the server; an expired link renders no address |
| F5 | A payment credits an order once per txid |
| F6 | Underpayment counts as paid only at 99% or more and at most $0.50 short |
| F7 | Several partial payments accumulate toward one order |
| F8 | A payment after expiry inside the grace window is paid; after it, late_paid |
| F9 | Every status change notifies the creator once |
| F10 | If the creator blocked the bot, the alert goes to ALERT_CHAT_ID |
| F11 | Unpaid orders are reconciled against the provider every five minutes |
| F12 | Only the owner can add or remove members |
| F13 | The page shows the amount actually received |

### Non-functional

| # | Requirement |
|---|---|
| N1 | The page fits 360x640 without scrolling |
| N2 | Address and QR render without JavaScript |
| N3 | Every QR decodes with a standard scanner |
| N4 | `/ping` answers within two seconds on a slow link |
| N5 | No secret in the image, the repository or Telegram messages |
| N6 | The database survives a hard kill: WAL, single writer, idempotent inserts |
| N7 | A dropped webhook costs at most five minutes |
| N8 | A restart loses no order state; an unfinished draft may be lost |

## States

```
pending --> partial --> paid
   |           |
   |           +--> overpaid
   +--> expired --> late_paid
   +--> cancelled
   +--> underpaid      below the chain minimum
   +--> wrongasset     wrong coin or network
   +--> failed         provider rejected the create call
```

`confirming` is transient: seen on chain, not yet at the confirmation threshold.

## Acceptance criteria

On a fresh host:

1. `/new` on each of the six chains produces a link that opens over HTTPS with the expected
   chain, asset and amount.
2. A full payment on BSC flips the page to PAID and sends one notification.
3. Paying 60% of a Polygon order yields PART PAID with the exact remainder; the second
   transfer yields PAID, not OVERPAID.
4. Stopping the web process for two minutes during a payment still ends in PAID after the
   reconciler runs.
5. A link opened after expiry shows LINK DEAD and no address.
6. `/export 7d` returns a CSV a spreadsheet can open.
7. `pytest` passes on a clean checkout, and the container starts with only BOT_TOKEN,
   OWNER_ID and PUBLIC_BASE set.

## Measures

- time from `/new` to link delivered under 30 seconds
- no order left pending past expiry without operator action
- no payment received but uncredited
- no duplicated credits

## Risks

| Risk | Mitigation |
|---|---|
| provider drops a webhook | five-minute reconciler |
| CryptAPI address stays payable after expiry | grace window, late_paid state, alert |
| NOWPayments holds funds in custody | payout address documented in DEPLOY |
| underpayment on a large invoice | absolute cap on the tolerance |
| wrong-chain transfer | QR carries chain and asset; page names the network; wrongasset state |
| operator enters the wrong amount | summary before create; confirmation above MAX_USD |

## Later

Recurring invoices, a team chat as a second notification target, fee display per chain,
refund tracking as a label rather than an action.
