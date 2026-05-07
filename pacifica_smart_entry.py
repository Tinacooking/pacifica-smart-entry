# pacifica_smart_entry.py
#
# A small agent that opens a BTC-PERP position on Pacifica using
# the RIGHT order type for the current market state.
#
# Run it against the testnet first. Only switch to mainnet after
# you have seen this script behave the way you want it to for at
# least a few hundred orders.

import os
from pacifica_sdk import PacificaClient


# ---------------------------------------------------------------
# Setup
# ---------------------------------------------------------------
# Two endpoints, one API. The default is testnet, so nothing
# scary can happen until you explicitly point this at mainnet.

TESTNET_URL = "https://test-api.pacifica.fi/api/v1"
MAINNET_URL = "https://api.pacifica.fi/api/v1"

base_url = os.environ.get("PACIFICA_BASE_URL", TESTNET_URL)
keypair  = os.environ["PACIFICA_KP"]

client = PacificaClient(base_url=base_url, keypair=keypair)

SYMBOL = "BTC-PERP"


# ---------------------------------------------------------------
# Step 1 — Look at the order book.
# ---------------------------------------------------------------
# Before deciding HOW to enter, the agent needs to know two
# things about the current market:
#
#   - the mid price (a fair reference point)
#   - how much size is available at the top of the book
#
# The depth check is what stops the agent from market-buying
# into a thin book and eating massive slippage later on.

def read_market():
    book = client.orderbook(SYMBOL, depth=5)

    best_bid = book.best_bid
    best_ask = book.best_ask
    mid_price = (best_bid + best_ask) / 2

    top_bid = book.bids[0]
    top_depth_in_usd = top_bid.size * top_bid.price

    return {
        "mid_price": mid_price,
        "top_depth_in_usd": top_depth_in_usd,
    }


# ---------------------------------------------------------------
# Step 2 — Choose the order type.
# ---------------------------------------------------------------
# This is the brain of the agent. There are three branches, and
# each one corresponds to a different intention:
#
#   Branch 1: High conviction AND the size fits the book.
#             -> MARKET ORDER. Punch through, take whatever's
#                there.
#
#   Branch 2: Confident, but want to be a maker (lower fees,
#             better fills) and stay in the queue.
#             -> LIMIT ORDER with TIF = "TOB".
#                TOB is Pacifica-exclusive. If the book moves
#                into your order, instead of cancelling, the
#                exchange repositions you to stay maker.
#
#   Branch 3: Patient. No urgency. Willing to wait at a level.
#             -> LIMIT ORDER with TIF = "GTC".
#                Sit on the book until the market comes to you.

def choose_order(side, size_in_usd, conviction, market):
    quantity = size_in_usd / market["mid_price"]

    # --- Branch 1: market order ---
    is_high_conviction = conviction > 0.8
    fits_in_book       = size_in_usd < market["top_depth_in_usd"] * 0.3

    if is_high_conviction and fits_in_book:
        return {
            "type": "market",
            "quantity": quantity,
            "max_slippage_percent": 0.3,
        }

    # --- Branch 2: limit + TOB (be a maker, stay in queue) ---
    if conviction > 0.5:
        if side == "buy":
            limit_price = market["mid_price"] * 0.999   # 0.1% below mid
        else:
            limit_price = market["mid_price"] * 1.001   # 0.1% above mid

        return {
            "type": "limit",
            "limit_price": limit_price,
            "quantity": quantity,
            "tif": "TOB",
        }

    # --- Branch 3: limit + GTC (patient, sit at level) ---
    if side == "buy":
        limit_price = market["mid_price"] * 0.995       # 0.5% below mid
    else:
        limit_price = market["mid_price"] * 1.005       # 0.5% above mid

    return {
        "type": "limit",
        "limit_price": limit_price,
        "quantity": quantity,
        "tif": "GTC",
    }


# ---------------------------------------------------------------
# Step 3 — Open the position AND attach a stop, in one call.
# ---------------------------------------------------------------
# This is the rule the agent never breaks: every position gets
# a stop attached the moment it's opened.
#
# Not "soon."  Not "after I check the chart."  Same function.
# Same call. If the entry fills, the stop goes on top of it.

def safe_open(side, size_in_usd, conviction, stop_distance_percent=2.0):
    market = read_market()
    order  = choose_order(side, size_in_usd, conviction, market)

    # --- place the entry ---
    if order["type"] == "market":
        entry = client.place_market(
            symbol=SYMBOL,
            side=side,
            amount=order["quantity"],
            slippage_percent=order["max_slippage_percent"],
        )
    else:
        entry = client.place_limit(
            symbol=SYMBOL,
            side=side,
            price=order["limit_price"],
            amount=order["quantity"],
            tif=order["tif"],
        )

    # If the limit is still resting on the book and nothing has
    # filled yet, there is no position to protect. Return early
    # and let the next tick decide what to do.
    filled_amount = entry.get("filled", 0)
    if filled_amount == 0:
        return entry

    # --- attach the stop ---
    fill_price = entry["avg_price"]
    stop_pct   = stop_distance_percent / 100

    if side == "buy":
        stop_price = fill_price * (1 - stop_pct)
        stop_side  = "sell"
    else:
        stop_price = fill_price * (1 + stop_pct)
        stop_side  = "buy"

    client.place_stop_market(
        symbol=SYMBOL,
        side=stop_side,
        trigger_price=stop_price,
        amount=filled_amount,
        reduce_only=True,   # only closes the position, never opens a new one
    )

    return entry


# ---------------------------------------------------------------
# Run it
# ---------------------------------------------------------------
if __name__ == "__main__":
    safe_open(
        side="buy",
        size_in_usd=100,
        conviction=0.7,
        stop_distance_percent=2.0,
    )
