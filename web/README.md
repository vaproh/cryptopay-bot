# Payment page

`pay.html` is the checkout page. One file, no build step. The server injects brand values and
a few URL parameters; everything else is static.

```sh
python3 -m http.server 8123 --directory web
# http://127.0.0.1:8123/pay.html
```

## Query parameters

| Parameter | Default | Meaning |
|---|---|---|
| `state` | `live` | `live`, `partial`, `confirming`, `paid`, `overpaid`, `late`, `expired`, `cancelled`, `underpaid`, `wrongasset`, `notfound` |
| `chain` | `bsc` | `bsc`, `polygon`, `solana`, `ethereum`, `arbitrum`, `base` |
| `usd` | `10` | amount due, in dollars |
| `t` | `1800` | seconds left on the timer |
| `total` | same as `t` | length of the window, used by the progress bar. Pass it to preview a half-spent link: `?t=600&total=1800` |
| `inv` | `INV-0007` | invoice reference |
| `label` | `Acme invoice 2291` | client label |
| `got` | `0` | asset units received, so partial and paid panels show real numbers |
| `provider` | `cryptapi` | `cryptapi` or `nowpayments`; decides whether a partial can be topped up |
| `qr` | amount | `addr` encodes the bare address instead of the payment URI |
| `addr` plus `live` | | `?live=1&addr=<real address>` is the only way the page will send a transaction |
| `wc` | | WalletConnect project id |

Examples:

- `?state=partial&chain=ethereum&usd=250&label=DeFi%20retainer`
- `?state=paid&chain=solana&usd=25`
- `?state=expired&chain=polygon&usd=7`

## Branding

The server sets two things when it serves `/p/<token>`:

- a `style` attribute on `<html>` with `--red`, `--red-hot`, `--accent`, `--bg`, `--text`
- `window.__BRAND` with the name and logo path

Inline on `<html>` is required. A `<style>` block would lose to the page's own `:root` rules.

The mark defaults to `icons/logo.svg`. The header crops it with `object-fit: cover` and
`scale(1.5)`, so a square image with a dark background works best.

## QR

The QR encodes a payment URI, not a bare address:

- EVM: `ethereum:<token>@<chainId>/transfer?address=<recipient>&uint256=<units>`
- Solana: `solana:<addr>?amount=<n>&spl-token=<mint>&label=&message=<inv>`

Scanning fills in asset, network and amount. The ADDRESS button, or `?qr=addr`, drops back
to the bare address.

Light plates only, dark modules on white. Inverted codes failed to decode in testing, so the
option was removed. There is no logo inside the code: a centred image punches a hole in the
pattern and forces more modules. The token icon sits in the amount line instead.

Verified with `zbarimg` on BSC, Base (USDC), Solana and the 140 px compact plate.

## Wallets

- EVM: MetaMask, Trust Wallet, Coinbase Wallet, Rainbow, plus WalletConnect.
- Solana: Phantom, Solflare.
- Deep-link hosts: MetaMask `link.metamask.io/dapp/<url>`, Phantom `phantom.com/ul/browse/<url>`,
  Solflare `solflare.com/ul/v1/browse/<url>`, Trust `link.trustwallet.com/open_url?coin_id=60&url=`.
  `metamask.app.link` and `phantom.app` are the older hosts.
- WalletConnect uses `@walletconnect/ethereum-provider` 2.26.0, imported from esm.sh only when
  the tile is tapped. `optionalChains` is used because `chains` is deprecated in 2.x. If no
  pairing URI appears within 15 seconds the sheet says the relay is unreachable.
- Inside a wallet (`window.ethereum` present) a red "Pay ... from this wallet" button appears.
  It opens a confirm sheet with amount, network and recipient.

The page sends nothing unless `live=1` and a real `addr` are present.

## Errors from the wallet

| Situation | What the sheet says |
|---|---|
| rejected in wallet (`4001`) | Cancelled. |
| request already pending (`-32002`) | Wallet has a request open. Confirm it there. |
| chain not added (`4902`) | adds the chain, then re-checks before sending |
| still on the wrong chain | stops, never signs |
| token balance too low | Wallet has 0.00 USDT. Need 40.00. |
| no native balance | No BNB for gas. |
| no wallet installed | hint under the tiles |

The balance check is advisory. If `eth_call` or `eth_getBalance` is unavailable the page
skips it rather than blocking a valid payment.

## States

| State | What the client sees |
|---|---|
| `live` | amount, QR, address, wallets, countdown |
| `partial` | the same, plus the amount received and the remainder; QR stays open |
| `confirming` | seen on chain, waiting for confirmations |
| `paid` | stamp, amount, transaction id |
| `overpaid` | amount received and the excess |
| `late` | paid after the link closed, under review |
| `expired` | link dead, no address |
| `cancelled` | merchant withdrew the invoice |
| `underpaid` | below the chain minimum, not credited |
| `wrongasset` | wrong coin or network, manual recovery |
| `notfound` | invalid or deleted token |

## Visual rules

- No border radius, no gradients, no shadows. Black, bone and blood red only.
- Time is shown twice: an 8 px bar at the top of the card with notches at 25, 50 and 75
  percent, and a countdown under the amount. Bone above 50 percent, red below, blinking under
  25.
- Motion, all disabled under `prefers-reduced-motion`: the card wipes in, sections rise in a
  stagger, the QR gets one scan sweep, and `paid` draws a check, slams a stamp and flashes the
  card border.

## What the page expects from the backend

| Requirement | Reason |
|---|---|
| `multi_token=1` on CryptAPI create | one EVM address accepts every EVM chain and asset |
| `convert=1` on CryptAPI create | the callback carries `value_coin_convert`; credit in dollars |
| `pending=1` on CryptAPI create | gives the 0-confirmation callbacks that `confirming` shows |
| credit by `coin` and `value_coin_convert` | 1000 TRX and 1000 USDT both report `value_coin=1000` |
| tolerance of 99 percent and $0.50 | a flat 99 percent accepts a $100 loss on $10,000 |
| credit only at N confirmations | reorgs and replaced transactions |
| idempotency on order and txid | a fee bump creates a second txid |
| underpaid stays `partially_paid` on NOWPayments | their dashboard can mark everything finished |
