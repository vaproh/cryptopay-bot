from dataclasses import dataclass


@dataclass(frozen=True)
class Chain:
    key: str
    name: str
    suffix: str
    asset: str
    provider: str
    minimum: float
    decimals: int | None
    chain_id: int | None
    ticker: str = ""          # cryptapi ticker
    pay_currency: str = ""    # nowpayments currency code
    token: str = ""           # erc20/spl contract for the payment URI


CHAINS: dict[str, Chain] = {
    "bsc": Chain("bsc", "BNB Smart Chain", "BEP-20", "USDT", "cryptapi", 1.0, 18, 56,
                 ticker="bep20/usdt", token="0x55d398326f99059fF775485246999027B3197955"),
    "polygon": Chain("polygon", "Polygon", "PoS", "USDT", "cryptapi", 0.5, 6, 137,
                     ticker="polygon/usdt", token="0xc2132D05D31c914a87C6611C10748AEb04B58e8F"),
    "solana": Chain("solana", "Solana", "SPL", "USDT", "cryptapi", 1.0, 6, None,
                    ticker="sol/usdt", token="Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"),
    "ethereum": Chain("ethereum", "Ethereum", "ERC-20", "USDT", "nowpayments", 5.0, 6, 1,
                      pay_currency="usdterc20", token="0xdAC17F958D2ee523a2206206994597C13D831ec7"),
    "arbitrum": Chain("arbitrum", "Arbitrum One", "Nitro", "USDT", "nowpayments", 1.0, 6, 42161,
                      pay_currency="usdtarb", token="0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"),
    "base": Chain("base", "Base", "OP Stack", "USDC", "nowpayments", 1.0, 6, 8453,
                  pay_currency="usdcbase", token="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
}

ORDER = ["bsc", "polygon", "solana", "ethereum", "arbitrum", "base"]

EXPIRY = [(30, "30 MIN"), (120, "2 HOURS"), (1440, "24 HOURS")]


def floor_for(chain: Chain, global_min: float) -> float:
    return max(chain.minimum, global_min)


def expiry_options(chain: Chain) -> list[tuple[int, str]]:
    opts = list(EXPIRY)
    # an address that never dies can honestly claim a week; a hosted gateway cannot
    if chain.provider == "cryptapi":
        opts.append((10080, "7 DAYS"))
    return opts


def pay_uri(chain: Chain, address: str, usd: float, invoice: str) -> str:
    """EIP-681 / Solana Pay request, identical to what the page builds."""
    if chain.chain_id is None:
        amount = f"{round(usd, 2):.2f}"
        return (f"solana:{address}?amount={amount}&spl-token={chain.token}"
                f"&label=Anomly&message={invoice}")
    units = int(round(usd * 100)) * 10 ** (chain.decimals - 2)
    return (f"ethereum:{chain.token}@{chain.chain_id}/transfer"
            f"?address={address}&uint256={units}")
