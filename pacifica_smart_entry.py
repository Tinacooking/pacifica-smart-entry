"""
pacifica_smart_entry.py — dry-run agent for Pacifica BTC perpetual.

Reads the live order book from Pacifica's REST API (public, no auth) and
prints the order the agent WOULD place given the current market state and
a conviction score. Stops at the decision boundary on purpose: real order
placement requires Ed25519-signed POSTs which depend on your own keypair.

No external dependencies — stdlib only.

Run it:
    python pacifica_smart_entry.py
    python pacifica_smart_entry.py --conviction 0.9
    python pacifica_smart_entry.py --side sell --size 250 --conviction 0.4
    PACIFICA_BASE_URL=https://api.pacifica.fi/api/v1 python pacifica_smart_entry.py
"""

import argparse
import json
import os
from urllib import parse, request

# ---------------------------------------------------------------
# Setup
# ---------------------------------------------------------------
# Two endpoints, one API. Default is testnet, so nothing scary can
# happen until you explicitly point this at mainnet.

TESTNET_URL = "https://test-api.pacifica.fi/api/v1"
MAINNET_URL = "https://api.pacifica.fi/api/v1"

BASE_URL = os.environ.get("PACIFICA_BASE_URL", TESTNET_URL)
SYMBOL   = "BTC"   # Pacifica perpetual symbol — case-sensitive. Spot is "BTC-USDC".


def http_get(path, **params):
    url = BASE_URL + path
    if params:
        url += "?" + parse.urlencode(params)
    with request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------
# Step 1 — Look at the order book.
# ---------------------------------------------------------------
# Two numbers drive every decision the agent makes:
#   - the mid price (a fair reference)
#   - the size sitting at the top of the book in USD
#
# The depth check stops the agent from market-buying into a thin
# book and eating massive slippage.

def read_market():
    resp = http_get("/book", symbol=SYMBOL)
    if not resp.get("success"):
        raise RuntimeError(f"book fetch failed: {resp}")

    bids, asks = resp["data"]["l"]
    best_bid = float(bids[0]["p"])
    best_ask = float(asks[0]["p"])
    bid_size = float(bids[0]["a"])

    return {
        "best_bid":         best_bid,
        "best_ask":         best_ask,
        "mid_price":        (best_bid + best_ask) / 2,
        "top_depth_in_usd": bid_size * best_bid,
    }


# ---------------------------------------------------------------
# Step 2 — Choose the order type.
# ---------------------------------------------------------------
# The brain of the agent. Three branches, three intentions:
#
#   Branch 1: High conviction AND the size fits the book.
#             -> MARKET ORDER. Punch through, take whatever's there.
#
#   Branch 2: Confident, but want to be a maker (lower fees) and
#             stay in the queue.
#             -> LIMIT ORDER with TIF = "TOB" (Pacifica-exclusive).
#
#   Branch 3: Patient. No urgency. Willing to wait at a level.
#             -> LIMIT ORDER with TIF = "GTC".

def choose_order(side, size_in_usd, conviction, market):
    quantity = size_in_usd / market["mid_price"]

    # --- Branch 1: market order ---
    is_high_conviction = conviction > 0.8
    fits_in_book       = size_in_usd < market["top_depth_in_usd"] * 0.3

    if is_high_conviction and fits_in_book:
        return {
            "type":                 "market",
            "side":                 side,
            "quantity":             quantity,
            "max_slippage_percent": 0.3,
        }

    # --- Branch 2: limit + TOB (be a maker, stay in queue) ---
    if conviction > 0.5:
        if side == "buy":
            limit_price = market["mid_price"] * 0.999   # 0.1% below mid
        else:
            limit_price = market["mid_price"] * 1.001   # 0.1% above mid
        return {
            "type":        "limit",
            "side":        side,
            "limit_price": limit_price,
            "quantity":    quantity,
            "tif":         "TOB",
        }

    # --- Branch 3: limit + GTC (patient, sit at level) ---
    if side == "buy":
        limit_price = market["mid_price"] * 0.995       # 0.5% below mid
    else:
        limit_price = market["mid_price"] * 1.005       # 0.5% above mid
    return {
        "type":        "limit",
        "side":        side,
        "limit_price": limit_price,
        "quantity":    quantity,
        "tif":         "GTC",
    }


# ---------------------------------------------------------------
# Step 3 — Compose entry + stop, atomically.
# ---------------------------------------------------------------
# The rule the agent never breaks: every position gets a stop the
# moment it's opened. Same function. Same call.
#
# This dry-run version computes the stop side, trigger price, and
# `reduce_only` flag without actually sending the orders. To go
# live, swap http_get for an Ed25519-signed http_post against
# /create_market_order, /create_limit_order, /create_stop_order.

def safe_open(side, size_in_usd, conviction, stop_distance_percent=2.0,
              stop_style="market"):
    market = read_market()
    order  = choose_order(side, size_in_usd, conviction, market)

    # Project the entry fill so we can attach a sane stop level.
    if order["type"] == "market":
        projected_fill = market["best_ask"] if side == "buy" else market["best_bid"]
    else:
        projected_fill = order["limit_price"]

    stop_pct = stop_distance_percent / 100
    if side == "buy":
        stop_price = projected_fill * (1 - stop_pct)
        stop_side  = "sell"
    else:
        stop_price = projected_fill * (1 + stop_pct)
        stop_side  = "buy"

    stop = {
        "side":          stop_side,
        "trigger_price": stop_price,
        "amount":        order["quantity"],
        "reduce_only":   True,
    }

    if stop_style == "limit":
        # Cap the worst fill 0.5% past the trigger. In a freefall, the
        # exit will not fill below this — at the cost of execution
        # certainty (you can be left holding the position if the book
        # gaps clean through the limit).
        limit_buffer = 0.005
        if side == "buy":
            stop["limit_price"] = stop_price * (1 - limit_buffer)
        else:
            stop["limit_price"] = stop_price * (1 + limit_buffer)
        stop["type"] = "stop_limit"
    else:
        stop["type"] = "stop_market"

    return {"market": market, "entry": order, "stop": stop}


# ---------------------------------------------------------------
# Pretty-print a decision for the terminal.
# ---------------------------------------------------------------

def render(decision):
    market = decision["market"]
    entry  = decision["entry"]
    stop   = decision["stop"]
    line   = "─" * 60

    print()
    print(line)
    print(f"  Pacifica {SYMBOL}-PERP — what the agent sees")
    print(f"  {BASE_URL}")
    print(line)
    print(f"  best bid:     ${market['best_bid']:>12,.2f}")
    print(f"  best ask:     ${market['best_ask']:>12,.2f}")
    print(f"  mid:          ${market['mid_price']:>12,.2f}")
    print(f"  top depth:    ${market['top_depth_in_usd']:>12,.0f}")
    print()
    print(line)
    print(f"  Decision")
    print(line)
    if entry["type"] == "market":
        print(f"  → MARKET {entry['side'].upper()} {entry['quantity']:.6f} {SYMBOL}")
        print(f"    max slippage:  {entry['max_slippage_percent']}%")
    else:
        print(f"  → LIMIT {entry['side'].upper()} {entry['quantity']:.6f} {SYMBOL}")
        print(f"    price:         ${entry['limit_price']:,.2f}")
        print(f"    TIF:           {entry['tif']}")
    print()
    print(f"  Stop attached")
    if stop["type"] == "stop_limit":
        print(f"  → STOP_LIMIT {stop['side'].upper()} {stop['amount']:.6f} {SYMBOL}")
        print(f"    trigger:       ${stop['trigger_price']:,.2f}")
        print(f"    limit_price:   ${stop['limit_price']:,.2f}")
        print(f"    reduce_only:   {stop['reduce_only']}")
    else:
        print(f"  → STOP_MARKET {stop['side'].upper()} {stop['amount']:.6f} {SYMBOL}")
        print(f"    trigger:       ${stop['trigger_price']:,.2f}")
        print(f"    reduce_only:   {stop['reduce_only']}")
    print()
    print("  (dry-run — no orders were sent.)")
    print(line)
    print()


def main():
    p = argparse.ArgumentParser(
        description="Pacifica smart-entry dry-run — read the book, choose the order type, print the decision."
    )
    p.add_argument("--side", choices=["buy", "sell"], default="buy",
                   help="trade direction (default: buy)")
    p.add_argument("--size", type=float, default=100,
                   help="position size in USD (default: 100)")
    p.add_argument("--conviction", type=float, default=0.7,
                   help="strategy conviction 0.0–1.0 (default: 0.7)")
    p.add_argument("--stop-pct", type=float, default=2.0,
                   help="stop loss distance in percent (default: 2.0)")
    p.add_argument("--stop-style", choices=["market", "limit"], default="market",
                   help="stop order style: 'market' (default) or 'limit' to cap the exit fill")
    args = p.parse_args()

    decision = safe_open(
        side=args.side,
        size_in_usd=args.size,
        conviction=args.conviction,
        stop_distance_percent=args.stop_pct,
        stop_style=args.stop_style,
    )
    render(decision)


if __name__ == "__main__":
    main()
