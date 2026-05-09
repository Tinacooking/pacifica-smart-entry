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

Once you see seven intentions instead of one verb, the work changes. Whether you're trading by hand or wiring a bot, you stop asking *"which order do I place?"* and start asking *"what am I actually trying to do?"*

The order falls out of the answer.

---

## How I vibe-coded it

Before any strategy, I wanted an environment where I could break things without losing money. Pacifica makes this easy: two endpoints, identical in every way except the data behind them.

```
testnet   https://test-api.pacifica.fi/api/v1
mainnet   https://api.pacifica.fi/api/v1
```

Same SDK. Same auth. Same order endpoints. Same SDK calls. The only thing that changes between "fake money" and "real money" is one string in your config.

So I wrote the whole agent against the testnet first. Broke it. Fixed it. Ran a few thousand orders to make sure nothing surprised me. Only then flipped the URL.

The agent does three things, in order:

1. **Looks at the order book** to understand the current market.
2. **Chooses an order type** based on what it sees and how confident the strategy is.
3. **Opens the position and attaches a stop loss in the same call** — never *I'll add the stop later.*

Here's the shape — three functions. The full file is ~150 lines and lives next to this article: [`pacifica_smart_entry.py`](./pacifica_smart_entry.py).

```python
def read_market():
    """Mid price + top-of-book depth."""
    ...

def choose_order(side, size_in_usd, conviction, market):
    """The brain — three branches, three intentions."""
    if conviction > 0.8 and size_fits_book:
        return market_order()                # punch through
    if conviction > 0.5:
        return limit(tif="TOB")              # Pacifica exclusive
    return limit(tif="GTC")                  # patient

def safe_open(side, size_in_usd, conviction, stop_pct=2.0):
    """Open the position AND attach a stop, in one call."""
    market = read_market()
    order  = choose_order(side, size_in_usd, conviction, market)
    entry  = place_entry(order)
    if entry.filled:
        place_stop_market(reduce_only=True)  # never optional
    return entry
```

Three functions. Three branches in the brain. One safety rule: **every entry gets a stop, atomically.** That's the whole agent.

Same intention, different order type, meaningfully different outcomes. The next four sections explain *why* the agent picks what it picks.

---

## The 4 order types

Every order on Pacifica is one of four types. Knowing when to reach for each is the difference between a trader who reacts and a trader who executes on purpose.

### 4.1 Market order

Executes immediately against whatever's sitting in the book. You don't pick a price — you take the price the book offers right now. On Pacifica, market orders pass through a randomized 50–100ms delay (more on that below).

**Reach for it when:**

- A breakout already happened — waiting for a limit fill means missing the move
- You need out *now* — the position is going against you fast
- A major event is coming (FOMC, earnings, liquidation risk) and certainty of exit beats price quality
- Conviction is high and the trade is worth more than a few ticks of slippage

**The risks** are slippage in thin or volatile books, and market impact when your size is meaningful versus top-of-book depth. Glance at the book before market-buying real size — that one habit saves more money than most strategy upgrades.

> **In the demo:** branch 1 of `choose_order` — high conviction *and* the size fits the book. The size check is the slippage guard.

### 4.2 Limit order

Executes at your price or better, never worse. Buy limit at $64,800 fills at $64,800 or below; sell limit at $65,200 fills at $65,200 or above. If price never reaches your level, the order rests on the book — how it rests is controlled by its TIF setting (next section).

**Reach for it when:**

- You've identified a level and want to buy *there*, not chase price higher
- You're scaling into a position over time
- You want maker fees instead of taker fees — over volume, this is real P&L
- The market is range-bound and you're picking off the edges

**The risks** are partial fills, never filling at all (price wicks past without enough volume on your level), and opportunity cost from being too patient.

The biggest Pacifica-specific upside on limit orders is the **TIF layer** — particularly **TOB**, which solves the post-only cancellation problem most DEXs ship with. See section 5.4.

> **In the demo:** branches 2 and 3 of `choose_order`. TOB at medium conviction, GTC at low conviction. Same primitive, different levels of patience.

### 4.3 Stop Market

A trigger plus a market order. You set a stop price; when the market hits it, a market order fires automatically. Two directions, two use cases:

- **Below current price** → stop loss. Long at $65,000, stop at $63,500. If price drops there, market sell fires.
- **Above current price** → breakout entry. Buy stop at $65,600 above resistance — if price breaks out, you're long automatically.

**Reach for it when:**

- You have an open leveraged position. Always. Every leveraged position should have a stop.
- You want to enter a breakout on confirmation, not anticipation
- You need automation across time zones — BTC moves at 3am, you're asleep, the stop handles it

**The risks** are stop slippage (still a market order on trigger), whipsaws (stopped at the low, then reversal), and gap risk when liquidations cascade clean past your level.

> **In the demo:** the stop block of `safe_open`. Two things to notice — (1) the stop is placed in the *same call* as the entry, never *"I'll add it later"*, and (2) `reduce_only=True` so the stop can only close, never open a new naked position by accident.

### 4.4 Stop Limit

Same trigger as Stop Market, but it fires a *limit* order instead of a market. You set two prices:

- **Trigger** — when to activate
- **Limit** — the worst fill you'll accept

Trigger at $63,500, limit at $63,200 → when price touches $63,500, a sell limit is placed at $63,200. You fill anywhere between, but never below $63,200.

**Reach for it when:**

- You'd rather *not fill* than fill catastrophically — e.g., a gap-down clean past your level
- The asset is thin or volatile and Stop Market would slip too far
- You're entering a breakout but won't chase if it gaps too aggressively past your level

**The risk** is the tradeoff itself — price control costs you execution certainty. In a fast breakdown, price can gap clean through your limit and leave you holding a losing position with no stop filled. Don't treat Stop Limit as a guaranteed stop loss.

> **In the demo:** swap one line. Replace `place_stop_market(...)` with `place_stop_limit(..., limit_price=stop_price * 0.995)` and you've capped your exit fill. Use it on thin-book altcoins; keep Stop Market on BTC/ETH.

---

## How to control your limit order — TIF settings

Time-In-Force decides what happens when a limit order doesn't fill right away. Four options on Pacifica, each with a distinct use.

### 5.1 GTC — Good Till Cancelled

The default. Order rests on the book indefinitely — across sessions, across days — until it fills or you cancel it manually.

**Reach for it when:**

- You've found a weekly support level and want to buy there whenever price arrives, even if that's three days away
- You're resting an order at a significant technical level and willing to forget it
- You're building a position with no urgency

**The risk** is the 50–100ms randomized delay applies (along with market and IOC). Matters for HFT, irrelevant for swing trading.

> **In the demo:** branch 3 of `choose_order` — low conviction, GTC bid 0.5% below mid. The agent says *I'm not sure, but if price comes back to my level, I want to be there.*

### 5.2 IOC — Immediate or Cancel

Fills immediately at your price or better. Whatever can't fill right now is cancelled — not rested, not queued. The unfilled portion just disappears.

**Reach for it when:**

- You want a large order where a partial fill is fine — IOC takes what's there and walks away, no resting tail exposed
- You're running an algo and don't want to leave footprint on the book
- You want this price right now or not at all

GTC is patient. IOC is *now or nothing*.

> **In the demo:** not used by default — but a one-line swap from `tif="GTC"` to `tif="IOC"` switches the agent from patient to sweeping.

### 5.3 ALO — Add Liquidity Only (Post Only)

The order is placed only if it would NOT immediately match an existing order. If placing it would make you a taker, it's cancelled instead. You're always the maker, always adding liquidity.

**Reach for it when:**

- You want maker fees, not taker fees — over volume, this is real P&L
- You're running a market-making strategy where maker fees are the whole edge
- You want to enter without moving the price

**The pain on most platforms:** if the book moves into your ALO order — even by a single tick — it crosses and gets cancelled. You reprice. By the time you reprice, the level moved again. Place, cancel, place, cancel.

Pacifica fixes this with TOB.

### 5.4 TOB — Top of Book ✦ (Pacifica exclusive)

TOB is ALO with one critical upgrade: if the order would cross the book, instead of cancelling, it **automatically repositions** to the best available price on your side.

- Buy that would cross → moved to highest bid + 1 tick
- Sell that would cross → moved to lowest ask − 1 tick

You stay maker. You stay in the queue. No cancellation, no manual repricing, no missed entry.

> *[image — split panel: left "ALO on other DEXs" with a ghost order stamped CANCELLED. Right "TOB on Pacifica" with the order repositioned to best bid + 1.]*

> **In the demo:** branch 2 of `choose_order`. The single most important line in the file. Change `tif="TOB"` to `tif="ALO"` and ~30% of those orders get cancelled silently on a fast tape. With TOB, they reprice and stay maker. One flag, materially different fill rate.

If you only remember one Pacifica-specific feature from this whole article, remember this one.

---

## The 50–100ms delay — by design

Market orders, GTC, and IOC orders on Pacifica are subject to a randomized 50–100ms delay before execution. Most retail traders never notice it. Some HFT traders complain about it. Both groups are missing the point.

Picture this: you're quoting BTC at $65,000 on the bid. The real price moves to $65,100. For 50 milliseconds, your bid is stale — saying *"I'll buy at $65,000"* when the market just decided BTC is worth $100 more.

A bot watching another exchange spots the gap. Hits your bid. You just bought $100 below market. Multiply by 10,000 quotes a day.

This is **adverse selection**, and it's why most makers eventually quit. Spreads widen. Books thin out. Everyone loses.

Pacifica's randomized delay breaks this. By scrambling execution timing within a 50–100ms window, no bot can reliably beat your quote update — even with a faster connection. The race stops being worth running.

**What this means for you:**

- **Maker (ALO/TOB):** the delay protects your resting orders. You get deeper liquidity and tighter spreads as a direct result.
- **Taker (Market/GTC/IOC):** you eat 50ms of delay. You also benefit from the tighter spreads that protection creates. Net positive.
- **HFT latency arb:** the delay is intentional. Pacifica is not designed to be a latency arbitrage venue.

It's the kind of thing serious market-structure engineers build in deliberately — and that most retail traders never notice until they ask why spreads are tighter here than on other DEXs.

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

The script is a **dry-run**: it reads the live order book from Pacifica's public REST API, decides what order it would place, and prints the decision. No keypair, no signing, no orders go out. Stdlib only — no `pip install` required.

```bash
git clone https://github.com/Tinacooking/pacifica-smart-entry.git
cd pacifica-smart-entry

python pacifica_smart_entry.py                     # default: buy, $100, conviction 0.7
python pacifica_smart_entry.py --conviction 0.9    # high conviction → MARKET
python pacifica_smart_entry.py --conviction 0.3    # low conviction  → GTC limit
python pacifica_smart_entry.py --side sell --size 250 --conviction 0.6
```

Sample output at `--conviction 0.9` (high enough to trigger the market branch):

```
────────────────────────────────────────────────────────────
  Pacifica BTC-PERP — what the agent sees
  https://test-api.pacifica.fi/api/v1
────────────────────────────────────────────────────────────
  best bid:     $   80,315.00
  best ask:     $   80,346.00
  mid:          $   80,330.50
  top depth:    $      10,000

────────────────────────────────────────────────────────────
  Decision
────────────────────────────────────────────────────────────
  → MARKET BUY 0.001245 BTC
    max slippage:  0.3%

  Stop attached
  → STOP_MARKET SELL 0.001245 BTC
    trigger:       $78,739.08
    reduce_only:   True

  (dry-run — no orders were sent.)
```

Change `--conviction` and watch the order type flip. That's the whole point: same intention, different order, meaningfully different outcome.

To go live, swap the read-only HTTP layer for Ed25519-signed POSTs against `/create_market_order`, `/create_limit_order`, `/create_stop_order`. Use mainnet URL via `PACIFICA_BASE_URL=https://api.pacifica.fi/api/v1` only after testnet looks clean for at least a few hundred runs.

Code: [`pacifica_smart_entry.py`](./pacifica_smart_entry.py) · License: MIT
