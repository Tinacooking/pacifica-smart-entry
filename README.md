# Trade Smarter on Pacifica — Start With Your Order Type

> Order types aren't a UI dropdown. They're a vocabulary for *what you intend to do*. Pick the intention first, then place the order.

---

## You've been trading wrong — and it's not your fault

You hit market buy on a volatile candle. Slippage eats 0.8%. Position starts underwater before the trade even begins.

Or you place a post-only limit order, perfectly priced, and watch it get cancelled the moment it crosses the book. Entry missed. Price runs without you.

Or you're asleep when your level hits. No stop set. You wake up to a liquidated position.

None of this is bad luck. It's a **tooling problem**. Most traders use one or two order types by default and never touch the rest. On a platform like Pacifica — where the infrastructure is built to CEX standards — leaving those tools unused means leaving real edge on the table.

Here's the full toolkit, and how to use it.

> *[image — toddler trader at a desk with one giant red BUY button]*

---

## What is Pacifica?

Pacifica is a decentralized exchange for perpetual and spot trading, built on Solana. The short version: **it trades like a CEX, settles like a DEX.**

- Sub-10ms round-trip API latency
- Non-custodial — your keys, your assets, always
- 35+ perpetual markets live, alongside a growing USDC-quoted spot market
- Up to 50x leverage depending on the pair

Founded January 2025. Mainnet launched June 2025. By September 2025 — three months later — Pacifica had reached #1 for perpetual DEX volume on Solana. Zero external funding. No VCs. No token unlock cliff hanging over the community. Every dollar of value created goes directly to users.

---

## Why order types are *actions*, not parameters

Most "AI trader" tutorials treat order placement as a single tool:

```python
place_order(symbol, side, size)
```

That's the toddler design. One verb. One button.

The real shape of the problem looks more like this:

| Intention | Order shape |
|-----------|-------------|
| Punch through, take whatever's there | Market |
| Rest at a level, be patient | Limit + GTC |
| Snipe right now or not at all | Limit + IOC |
| Only-maker, lower fees | Limit + ALO |
| Only-maker, *and* don't get ghosted | Limit + TOB |
| Wake me up if price crosses X | Stop Market |
| Wake me up, but cap the slippage | Stop Limit |

Once you see them as **seven distinct intentions** instead of one verb with seven flags, the whole game changes. Whether you're trading by hand or wiring an agent, the work is the same: pick the intention first, then place the order.

The model — or your gut — is good at picking *intentions*. Both are bad at picking parameters in a vacuum. Design the action space yourself; let the model choose among them. That single rule is most of what *vibe-coding an AI trader safely* means.

---

## How I vibe-coded it

Before I touched any strategy, I needed an environment where I could break things without losing money. Pacifica makes that easy because it runs two endpoints with the **exact same API surface**:

```
testnet   https://test-api.pacifica.fi/api/v1
mainnet   https://api.pacifica.fi/api/v1
```

Same SDK. Same Ed25519 signing on every POST. Same order endpoints. The only thing that changes when you go from "fake money" to "real money" is one string in your config.

So I wrote my entire agent against the testnet first, ran it for a few thousand orders, watched it behave, broke it, fixed it — and only then flipped the URL.

The agent does three things, in order:

1. **Looks at the order book** to understand the current market.
2. **Chooses an order type** based on what it sees and how confident the strategy is.
3. **Opens the position and attaches a stop loss in the same call** — never *I'll add the stop later.*

Here is the full file:

```python
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
```

If you want to run it yourself, set two environment variables in your shell and run the script:

```bash
export PACIFICA_KP=your_solana_keypair
export PACIFICA_BASE_URL=https://test-api.pacifica.fi/api/v1   # testnet first

python pacifica_smart_entry.py
```

The script will open a small long on BTC-PERP, attach a 2% stop loss, and exit. Watch the logs. Inspect what it placed. Try changing `conviction=0.7` to `0.9` and notice that the order type changes — the same script now sends a **market** order instead of a TOB limit, because the agent decided you're confident enough to take the spread.

That is the entire idea of this article in one experiment: **the same intention, expressed through different order types, produces meaningfully different outcomes.**

Once this script has run a few hundred times on the testnet without surprising you, you can change a single environment variable to point at mainnet, and the same code becomes a live trader.

The next four sections explain *why* this script chooses what it chooses. We'll start with the four order types it can produce.

---

## The 4 order types

Every order on Pacifica falls into one of four types. Understanding when to use each one — and why — is the difference between a trader who reacts and a trader who executes with intention.

### 4.1 Market order

**How it works:** A market order executes immediately against the best available orders sitting in the orderbook. You're not specifying a price — you're taking whatever the book offers right now.

On Pacifica, market orders are subject to a randomized 50–100ms delay before execution. More on why that's actually a good thing in section 6.

**When to use it:**

- **Breakout entries** — price just broke a key level and you need to be in before it runs. Waiting for a limit fill means missing the move entirely.
- **Emergency exits** — position going against you fast, you need out *now*, regardless of price.
- **High-conviction momentum plays** — you've made the decision; execution speed matters more than saving a few ticks.
- **Closing a position before a major event** — earnings, Fed announcement, liquidation risk. Getting out matters more than getting out at a perfect price.

**What to watch out for:**

- **Slippage** — the difference between the price you saw and the price you got. In thin markets or during high volatility, this can be significant. On Pacifica, check the orderbook depth before hitting market on a large size.
- **Market impact** — large market orders eat through multiple price levels. If your size is meaningful relative to the book, you're moving the price against yourself as you fill.

**How other exchanges handle it:** most CEX and DEX platforms offer market orders as standard. The difference is execution quality. On slower DEXs running on-chain matching (dYdX v3, early GMX), a *market order* could mean fills hundreds of milliseconds later at a significantly different price. Pacifica's off-chain matching engine means your market order hits the book at CEX-comparable speed.

> **In the demo:** the first branch of `choose_order` — `is_high_conviction AND fits_in_book`. The size check is the slippage guard; the agent refuses to market-buy when its order would eat more than ~30% of the top of the book.

### 4.2 Limit order

**How it works:** A limit order only executes at your specified price or better. Buy limit at $64,800 means you'll fill at $64,800 or lower, never higher. Sell limit at $65,200 means you'll fill at $65,200 or higher, never lower.

If the market never reaches your price, the order sits on the book and waits — based on your TIF setting (covered in section 5).

**When to use it:**

- **Entering at a specific level** — you've identified support at $64,500 and want to buy *there*, not chase price higher. Set your limit and let the market come to you.
- **Building a position over time** — dollar-cost averaging into a level, scaling in without chasing. Each limit order fills only when price reaches it.
- **Reducing fees** — on Pacifica, limit orders that rest on the book fill as **maker** orders, which carry lower fees than taker. For active traders, this adds up significantly over time.
- **Tight range markets** — when price is consolidating, limit orders let you buy the bottom and sell the top of the range without constantly watching screens.

**What to watch out for:**

- **Partial fills** — your order might fill in pieces as sellers hit your level. Depending on your TIF setting, the remainder either stays on the book or gets cancelled.
- **Never filling** — if price touches your level but doesn't have enough volume to fill your full size, you might get a partial or nothing. Especially relevant in fast moves where price wicks to your level and reverses.
- **Opportunity cost** — being too aggressive with limit placement means missing moves. Price runs to $66,000 while your buy limit sits unfilled at $64,500.

**How other exchanges handle it:** standard across all exchanges. The meaningful difference on Pacifica is the TIF layer — particularly **TOB**, which solves the biggest frustration with limit orders on other DEXs: post-only orders getting cancelled when the book moves. More on this in section 5.4.

> **In the demo:** branches 2 and 3 of `choose_order`. Two limit branches with different intentions — TOB when conviction is medium (be a maker, stay in the queue), GTC when conviction is low (sit at a level and wait). Same primitive, different patience.

### 4.3 Stop Market

**How it works:** a Stop Market is a two-step order — first a trigger condition, then a market order. You set a stop price; when the market hits that level, a market order fires automatically.

Two directions, two use cases:

- **Stop below current price (stop loss):** you're long BTC at $65,000, stop set at $63,500. If price drops to $63,500, a market sell fires automatically. Limits your loss without requiring you to watch the screen.
- **Stop above current price (breakout entry):** price is consolidating at $64,000, resistance at $65,500. Set a buy stop at $65,600 — if price breaks out, you're in automatically without timing the entry manually.

**When to use it:**

- **Protecting open positions** — the core use case. Every leveraged position on Pacifica should have a stop. Period.
- **Automated breakout entries** — you've identified a level where you want to be long if price confirms. Stop Market above resistance gets you in on confirmation, not anticipation.
- **Take-profit automation** — lock in gains at a target level without watching screens. Set a sell stop above current price; go live your life.
- **Managing positions across time zones** — Pacifica runs 24/7. You're in Vietnam and BTC is making moves at 3am. Stop orders handle your risk while you sleep.

**What to watch out for:**

- **Slippage on trigger** — once triggered, it's a market order. In fast markets or during news events, the actual fill can be significantly worse than your stop price. This is *stop slippage* and it's a real risk on every venue.
- **Whipsaws** — price hits your stop, triggers the market sell, then immediately reverses higher. Painful, but unavoidable if you're using stops correctly. The alternative is holding through a real breakdown.
- **Gap risk** — if price gaps past your stop level (common during liquidation cascades or major news), your stop triggers into a market with no liquidity. Fill could be far worse than stop price.

**How other exchanges handle it:** available on all major CEX and most DEX platforms. On-chain DEXs like GMX handle stops differently — they're oracle-based and settle at oracle price rather than orderbook price, which changes the slippage dynamic. Pacifica's off-chain matching means Stop Market orders behave closer to CEX — trigger fires and hits a live orderbook.

> **In the demo:** the last block of `safe_open`. Notice two things: (1) the stop is placed in the **same function** as the entry — never `safe_open()` then *I'll add a stop later.* Same call. (2) `reduce_only=True`. Forget that flag once and your stop fires after you've manually closed, opening a fresh opposite naked position you didn't ask for.

### 4.4 Stop Limit

**How it works:** same trigger mechanic as Stop Market, but instead of firing a *market* order, it fires a *limit* order. You set two prices:

- **Trigger price** — when the market hits this, the limit order activates
- **Limit price** — the worst price you'll accept for the fill

Example: BTC at $65,000. You set a stop limit with trigger at $63,500 and limit at $63,200. When price hits $63,500, a sell limit at $63,200 is placed. You'll fill anywhere between $63,500 and $63,200 — but never below $63,200.

**When to use it:**

- **When you'd rather not fill than fill badly** — some traders prefer no fill to a catastrophic fill. Stop Limit gives you that control. If the market is in freefall and gaps past your limit, you stay in the position rather than selling at a terrible price.
- **Volatile assets with wide spreads** — on altcoin markets with thin liquidity, Stop Market can result in extreme slippage. Stop Limit caps your downside on the fill price.
- **Breakout entries with price control** — want to enter on a breakout but only if price doesn't run too far? Trigger at $65,500, limit at $65,800. You're in on the break but not chasing if it gaps up aggressively.
- **Precise risk management** — when your position sizing math depends on a specific entry price, Stop Limit ensures you don't fill at a price that breaks your risk/reward calculation.

**What to watch out for:**

- **The fundamental tradeoff** — Stop Limit gives you price control but removes the *guarantee of execution*. In a fast breakdown, price can gap through your limit entirely and leave you holding a losing position with no stop filled. This is the core risk and why many traders prefer Stop Market for actual stop losses.
- **Setting the limit too tight** — if your trigger and limit are very close together ($63,500 trigger, $63,490 limit), any normal spread will prevent your fill. Give the limit enough room to actually execute.
- **Not a guaranteed exit** — never treat Stop Limit as a guaranteed stop loss. For hard stops where execution certainty matters, Stop Market is safer.

**How other exchanges handle it:** standard on CEX. Less common on DEX — many DEX platforms only offer Stop Market. Pacifica offering both gives traders the full toolkit that CEX users take for granted.

> **In the demo:** swap one line. Replace `place_stop_market(...)` with `place_stop_limit(..., limit_price=stop_price * 0.995)` and the agent now caps its exit fill price. Use this on thin-book altcoins; keep Stop Market on BTC/ETH.

---

## How to control your limit order — TIF settings

Time-In-Force settings apply to limit orders and determine what happens when an order doesn't fill immediately. Four options on Pacifica, each with a distinct use case.

### 5.1 GTC — Good Till Cancelled

**How it works:** order stays on the book indefinitely — across sessions, across days — until it fills completely or you cancel it manually. The default setting.

**When to use it:**

- **Swing-trade entries** — you've identified a weekly support level and want to buy there whenever price arrives, even if that's three days from now.
- **Resting orders at key levels** — set your bid at a significant technical level and forget it. If price comes back, you're in.
- **Patient position building** — no urgency, willing to wait for your price.

**What to watch out for:** GTC orders on Pacifica (along with market and IOC) are subject to the 50–100ms randomized delay. This matters for high-frequency strategies but is irrelevant for swing traders.

> **In the demo:** the third branch of `choose_order` — low conviction, drop a GTC bid 0.5% below mid. The agent expresses *I'm not sure, but if price comes back to my level, I want to be there.*

### 5.2 IOC — Immediate or Cancel

**How it works:** attempts to fill immediately at your specified price or better. Any portion that can't fill right now is cancelled — not rested, not queued. The unfilled portion simply disappears.

**When to use it:**

- **Large orders where partial fill is acceptable** — you want to buy 10 BTC at $65,000. IOC fills whatever is available at that price right now and cancels the rest. You don't end up with a resting order sitting exposed.
- **Algorithmic strategies** — algo traders use IOC to avoid leaving footprint on the book. Each attempt fills what it can and leaves no trace.
- **Time-sensitive entries** — you want to enter at a specific price right now or not at all. If the level isn't there immediately, you don't want the order lingering.

**The difference from GTC:** GTC is patient. IOC is *immediate or nothing*.

> **In the demo:** not used by the default agent — but it's a one-line swap from `tif="GTC"` to `tif="IOC"` if you want sweeping behavior instead of resting behavior.

### 5.3 ALO — Add Liquidity Only (Post Only)

**How it works:** the order is only placed if it would NOT immediately match against an existing order. If placing it would result in an immediate fill (making you a taker), it's cancelled instead.

This guarantees you're always the maker — you're adding liquidity to the book, not taking it.

**When to use it:**

- **Reducing fees** — on Pacifica, makers pay lower fees than takers. For active traders running significant volume, consistently paying maker instead of taker fees is meaningful P&L.
- **Market-making strategies** — professional market makers live and die by maker fees. ALO is the standard tool.
- **Entering without market impact** — your order rests passively until someone fills against it.

**The frustration on most platforms:** if you place an ALO order and the market moves toward it before it rests — even by a single tick — it crosses the book and gets cancelled. You have to reprice manually and resubmit. In fast markets, by the time you reprice, the level has moved again. This is the core pain point of post-only trading on most DEXs.

Pacifica solves this with TOB.

### 5.4 TOB — Top of Book ✦ (Pacifica exclusive)

**How it works:** TOB is ALO with one critical upgrade: if the order would cross the book, instead of being cancelled, it automatically repositions to the best available price.

- If your buy order would cross → repositioned to highest bid in the book plus one tick
- If your sell order would cross → repositioned to lowest ask in the book minus one tick

You stay on the right side of the spread. You stay maker. **No cancellation, no manual repricing, no missed entry.**

> *[image — split panel: left "ALO on other DEXs" with a ghost order stamped CANCELLED. Right "TOB on Pacifica" with the order repositioned to best bid + 1.]*

> **In the demo:** the second branch of `choose_order`. This is the single most important line in the file. Change `tif="TOB"` to `tif="ALO"` and on a fast tape, ~30% of those orders get cancelled silently. With TOB, they reprice and stay maker. One flag, materially different fill rate.

If you only remember one Pacifica-specific feature from this whole article, remember this one.

---

## The 50–100ms delay — by design

Market orders, GTC, and IOC orders on Pacifica are subject to a randomized 50–100ms delay before execution.

Most retail traders never notice it. Some HFT traders complain about it. Both groups are missing the point.

**Why it exists:** in financial markets, there's a well-documented problem called **adverse selection**. Sophisticated actors with faster data connections — or any latency advantage — can identify when a market maker's resting orders are mispriced (because the real price has moved but the maker's quote hasn't updated yet) and fill those stale orders before the maker can react.

The result: makers consistently get picked off. They provide liquidity, but they systematically fill at bad prices because faster actors exploit the delay between price movement and quote update. Over time, this discourages market making, reduces liquidity depth, and widens spreads for everyone.

The 50–100ms randomized delay breaks this dynamic. By randomizing execution timing, Pacifica removes the advantage of being microseconds faster. **No actor can reliably exploit a speed advantage when execution time is randomized within that window.**

**What this means for you:**

- **Maker (using ALO/TOB):** the delay protects your resting orders from being systematically picked off by faster actors. Deeper liquidity benefits you directly through tighter spreads.
- **Taker (using Market/GTC/IOC):** you experience a slight delay, but you benefit from the tighter spreads that the liquidity protection creates. Net effect is positive.
- **HFT latency arb:** this delay is intentional. Pacifica is not designed to be a latency arbitrage venue.

The 50–100ms delay is one of the more sophisticated design decisions in Pacifica's architecture. It's the kind of thing serious market structure engineers build in deliberately — and that most retail traders never think about until they start asking why spreads are tighter here than on other DEXs.

---

## TL;DR — pick the intention first

| Intention | Order |
|-----------|-------|
| Punching through, decision is made | **Market** |
| Patient at a level | **Limit + GTC** |
| Now or never, no resting | **Limit + IOC** |
| Maker-only, and I want to actually fill | **Limit + TOB** ✦ |
| Wake me up if I'm wrong | **Stop Market** |
| Wake me up, but cap the slippage | **Stop Limit** |

Order types aren't a UI dropdown. They're a **vocabulary for what you intend to do**. Once you start using all of them on purpose, you stop being a trader who reacts — and start being one who executes with intention.

Pacifica gives you the full vocabulary. The script in this repo is how I taught my agent to speak it. Steal it, point it at testnet, and let the order types teach you what they taught me.

---

## Run it yourself

```bash
git clone https://github.com/Tinacooking/pacifica-smart-entry.git
cd pacifica-smart-entry
pip install pacifica-sdk

export PACIFICA_KP=your_solana_keypair
export PACIFICA_BASE_URL=https://test-api.pacifica.fi/api/v1   # testnet first

python pacifica_smart_entry.py
```

Code: [`pacifica_smart_entry.py`](./pacifica_smart_entry.py) · License: MIT
