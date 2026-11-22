# Payment page (dummy)

Static preview of `/p/<token>`. No backend, no build step — open `pay.html` or serve the folder:

```sh
python3 -m http.server 8123 --directory web
# http://127.0.0.1:8123/pay.html
```

## Query params

| Param | Default | Values |
|---|---|---|
| `state` | `live` | `live` · `partial` · `confirming` · `paid` · `overpaid` · `late` · `expired` · `cancelled` · `underpaid` · `wrongasset` · `notfound` |
| `chain` | `bsc` | `bsc` · `polygon` · `solana` · `ethereum` · `arbitrum` · `base` |
| `usd` | `10` | any number |
| `t` | `1800` | seconds remaining on the timer |
| `total` | value of `t` | full window in seconds — the denominator for the progress bar. Pass this to preview mid-life states, e.g. `?t=600&total=1800` |
| `inv` | `INV-0007` | invoice reference |
| `label` | `Acme invoice 2291` | client label |
| `addr` + `live` | – | `?live=1&addr=<real>` is the only way the page will broadcast |
| `got` | `0` | asset units actually received, so partial/paid panels show real numbers |
| `provider` | `cryptapi` | `cryptapi` · `nowpayments` — a partial is top-up-able on CryptAPI, terminal on NOWPayments |
| `qr` | amount | `addr` encodes the bare address instead of the payment URI |
| `wc` | – | Reown project ID for WalletConnect |

Examples:

- `?state=partial&chain=ethereum&usd=250&label=DeFi%20retainer`
- `?state=paid&chain=solana&usd=25`
- `?state=expired&chain=polygon&usd=7`

## Wallets

- Brand mark and favicon use `icons/logo.svg` by default. The header crops it with `object-fit:cover` + `scale(1.5)` so the mark fills a 26 px tile; swap the file (square, dark background) or set `BRAND_LOGO` and nothing else needs to change.
- Icon-only tiles (`icons/*.svg`, official wallet marks from `@web3icons/core` 4.0.59, MIT).
- EVM chains → MetaMask, Trust, Coinbase, Rainbow, each deep-linking into the wallet's in-app browser on the current page.
- Solana → Phantom, Solflare.
- Deep-link hosts verified against vendor docs (Nov 2026): MetaMask `link.metamask.io/dapp/<url>` (the old `metamask.app.link` host is superseded), Phantom `phantom.com/ul/browse/<url>` (`phantom.app` is the legacy host), Solflare `solflare.com/ul/v1/browse/<url>`, Trust `link.trustwallet.com/open_url?coin_id=60&url=`.
- WalletConnect (EVM) opens our own QR sheet: set `const WC_PROJECT_ID` in the page or pass `?wc=<reown-project-id>`. SDK is `@walletconnect/ethereum-provider` 2.26.0, imported lazily from esm.sh; `optionalChains` is used because `chains` is deprecated in 2.x. If no pairing URI appears within 15 s the sheet says the relay is unreachable instead of spinning forever, and `connect()` is capped at 2 min. Production should bundle the SDK rather than import it from a CDN.
- If the page is opened **inside** a wallet (`window.ethereum` present) a green "Pay … from this wallet" button appears, with a confirm sheet that shows amount, network and recipient before signing.
- Sending is gated: it only broadcasts with `?live=1&addr=<real address>`. Without both, the sheet says the demo never broadcasts — placeholder addresses are not payable.

## Branding

`/p/<token>` is served with two injections from the server: a `style` attribute on `<html>`
carrying `--red`, `--red-hot`, `--bg`, `--text`, and a `window.__BRAND` object with the name
and logo path. The page has no hardcoded brand beyond the fallbacks, so a rebrand is an env
change, not an edit. Inline on `<html>` is deliberate: a `<style>` block would lose to the
page's own `:root` rules.

## Backend contract

Decided from the gateway research (CoinPayments, NOWPayments, BTCPay, Confirmo, CryptAPI docs). The page assumes a backend that does all of this:

| Requirement | Why |
|---|---|
| `multi_token=1` on CryptAPI create | one EVM address valid on every EVM chain and asset — kills the "sent USDC instead of USDT" loss class |
| `convert=1` on CryptAPI create | callback carries `value_coin_convert`; credit by USD, never by asset units |
| `pending=1` on CryptAPI create | gives real 0-conf webhooks, which is what `confirming` renders |
| value by `coin` + `value_coin_convert` | 1000 TRX is not 1000 USDT even though both report `value_coin=1000` |
| underpayment rule: **≥99% AND ≤$0.50 short** | a flat 99% accepts a $100 loss on a $10k invoice |
| credit only at N confirmations | reorgs and replaced transactions must not flip an order to paid early |
| idempotency on `(order, txid)`, RBF-aware | a fee-bump produces a second txid for the same intent |
| payout wallet holds keys, never an exchange deposit address | exchanges credit only the asset/network you selected |
| NOWPayments dashboard: leave underpaid deposits as `partially_paid` | their setting can auto-mark every deposit `finished` regardless of amount — that silently forgives underpayments |
| treat NOWPayments `wrong asset confirmed` as terminal | funds can only be moved manually from the dashboard |

## Behaviour

- The QR encodes a **payment URI**, not a bare address: EIP-681 (`ethereum:<token>@<chainId>/transfer?address=<recip>&uint256=<units>`) on EVM, `solana:<addr>?amount=&spl-token=` on Solana. Scanning prefills asset, network and amount, which is the biggest single cause of underpayment. `?qr=addr` (or the ADDRESS button) drops to the bare address.
- QR is **light only**: dark modules on a white plate. Inverted codes failed to decode in testing, so the option was removed rather than shipped.
- No mark inside the QR: a centred logo punches a hole in the pattern and costs modules. The token icon sits inline in the amount line instead (`40.00 Ⓣ USDT on BNB Smart Chain`), so the code stays clean at error correction L. Verified with `zbarimg` on BSC, Base (USDC) and Solana.
- Two segmented controls under the QR: `AMOUNT | ADDRESS` and `DARK | LIGHT`. They re-render in place; production would pin both from the backend and hide the controls.
- When `live=1&addr=…` is set, the QR, the copied address and the transfer target all use the real address; placeholders are never payable.
- Timer counts down and flips the page to `expired` at zero; the address block disappears and is never re-rendered.
- Time remaining is shown twice: a 3 px bar along the card's top edge and a countdown line under the amount. Four steps: **bone ≥75%** → **dim bone ≥50%** → **blood red ≥25%** → **hot red <25%**. Below 50% the countdown gains a red box; below 25% it reads `left — pay now` and blinks.
- Theme is deliberate: pure black, bone text, blood red, zero border-radius, zero gradients, no shadows or glows. Every surface is a hard-edged rectangle. Chain identity comes from the uppercase label, not colour.
- Motion (all disabled under `prefers-reduced-motion`): card wipes in with a hard `clip-path` step animation, sections rise in a 60 ms stagger, the QR gets one red scan sweep, and `paid` adds a drawn check, a bounding ring, and a stamp that slams in rotated before the card border flashes white twice.
- Progress bar is 8 px with milestone notches at 25/50/75 % and a white leading edge, so it reads as a gauge rather than a hairline.
- `expired` deliberately hides the address — a closed link must not keep showing a payable address.

## States

| State | Shown to the customer |
|---|---|
| `live` | amount, QR, address, wallets, countdown |
| `partial` | the above **plus** "16.83 of 19.99 arrived · send 3.16 more" — QR stays so they can top up |
| `confirming` | "Payment detected — 1 of 3 confirmations", spinner, no QR |
| `paid` | "Payment received · confirmed" + txid |
| `overpaid` | amount received and the excess |
| `late` | "arrived after the link closed — will be verified and credited manually" |
| `expired` | "This link has closed", address never rendered |
| `cancelled` | merchant withdrew the invoice |
| `underpaid` | below the chain minimum, not credited |
| `wrongasset` | wrong coin or network — not credited automatically, recovered manually |
| `notfound` | invalid or deleted token |

## Wallet error handling

Every path below was exercised against a mocked provider:

| Situation | Message |
|---|---|
| user rejects in wallet (`4001`) | You cancelled in your wallet. |
| request already open (`-32002`) | Your wallet already has a request open — switch to it and confirm. |
| chain missing (`4902`) | prompts `wallet_addEthereumChain`, waits, then re-checks `eth_chainId` |
| still on wrong chain after switching | aborts — **never sends on the wrong network** |
| token balance below invoice | "This wallet holds 0.00 USDT — the invoice needs 40.00." |
| zero native balance | "This wallet has no BNB for the network fee." |
| no browser wallet at all | hint under the tiles: use WalletConnect or copy the address |

The balance check is advisory: if `eth_call` or `eth_getBalance` is unavailable the page skips it rather than blocking a valid payment.
