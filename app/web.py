import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import db, orders
from .config import Config
from .providers import NowPayments

_tasks: set[asyncio.Task] = set()

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
PAGE = (WEB_DIR / "pay.html").read_text(encoding="utf-8")


async def _reconcile_quietly(cfg: Config, order) -> None:
    try:
        await orders.reconcile(cfg, order)
    except Exception:
        pass


HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _colour(value: str, fallback: str) -> str:
    return value if HEX.match(value or "") else fallback


def brand_vars(cfg: Config) -> str:
    """Inline on <html> so it beats the page's own :root block."""
    accent = _colour(cfg.brand_accent, "#c8102e")
    accent2 = _colour(cfg.brand_accent2, "#ff2b3d")
    bg = _colour(cfg.brand_bg, "#000000")
    text = _colour(cfg.brand_text, "#e8e5df")
    return (f"--red:{accent};--red-hot:{accent2};--accent:{accent};"
            f"--bg:{bg};--text:{text}")


def brand_script(cfg: Config) -> str:
    logo = cfg.brand_logo if re.match(r"^[\w./-]+$", cfg.brand_logo or "") else "icons/logo.svg"
    payload = json.dumps({"name": cfg.brand_name[:32], "logo": logo}).replace("</", "<\\/")
    return f'<script>window.__BRAND={payload}</script>' 


def build(cfg: Config) -> FastAPI:
    app = FastAPI(title="cryptopay bot", docs_url=None, redoc_url=None)

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok"

    @app.get("/p/{token}", response_class=HTMLResponse)
    async def pay_page(token: str) -> HTMLResponse:
        order = db.order_by_token(token)
        if not order:
            state, chain, usd, t, total, inv, label, addr, provider = (
                "notfound", "bsc", 0.0, 0, 0, "", "", "", "cryptapi")
        else:
            state, t, total = orders.page_state(cfg, order)
            chain = order["chain"]
            usd = float(order["usd"])
            inv = order["inv"] or ""
            label = order["label"] or ""
            addr = order["address"] or ""
            provider = order["provider"]

        qs = urlencode({
            "state": state, "chain": chain, "usd": f"{usd:.2f}", "t": t, "total": total,
            "inv": inv, "label": label, "addr": addr, "provider": provider,
            "got": f"{float(order['received']):.6f}" if order else "0",
            **({"live": "1"} if addr else {}),
        })
        inject = ('<base href="/">' + brand_script(cfg) +
                  '<script>history.replaceState(null,"",'
                  f'location.pathname+"?{qs}")</script>')
        html = PAGE.replace("<head>", "<head>" + inject, 1)
        html = html.replace('<html lang="en"', f'<html style="{brand_vars(cfg)}" lang="en"', 1)
        return HTMLResponse(html, headers={
            "Cache-Control": "no-store, private",
            "Referrer-Policy": "no-referrer",
        })

    @app.api_route("/cb/cryptapi", methods=["GET", "POST"])
    async def cb_cryptapi(request: Request) -> JSONResponse:
        token = request.query_params.get("o", "")
        order = db.order_by_token(token)
        if not order:
            return JSONResponse({"ok": False}, status_code=404)
        # the body is unauthenticated: never credit from it, ask /logs/ instead.
        # do it off-request so a slow gateway never blocks or times out the webhook.
        task = asyncio.create_task(_reconcile_quietly(cfg, order))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return JSONResponse({"ok": True})

    @app.post("/cb/nowpayments")
    async def cb_nowpayments(request: Request) -> JSONResponse:
        raw = await request.body()
        sig = request.headers.get("x-nowpayments-sig")
        api = NowPayments(cfg.nowpayments_api, cfg.nowpayments_key)
        if not api.verify_ipn(raw, sig, cfg.nowpayments_ipn_secret):
            return JSONResponse({"ok": False, "error": "bad signature"}, status_code=401)
        try:
            payload = json.loads(raw)
        except ValueError:
            return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)

        order = db.order_by_token(str(payload.get("order_id", "")))
        if not order:
            ref = str(payload.get("payment_id", ""))
            order = db.q1("SELECT * FROM orders WHERE provider_ref=?", (ref,))
        if not order:
            return JSONResponse({"ok": True}, status_code=200)

        await orders.apply_provider_status(cfg, order, payload)
        return JSONResponse({"ok": True})

    # static last so /p and /cb win
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app
