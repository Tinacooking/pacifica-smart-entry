# pacifica-smart-entry

A small agent that opens BTC-PERP positions on Pacifica using the **right order type** for the current market state.

> Article + full demo coming soon.

## What it is

A ~100-line Python script that:

1. Reads the BTC-PERP order book on Pacifica
2. Picks an order type (market / limit + TOB / limit + GTC) based on conviction and book depth
3. Opens the position and attaches a `reduce_only` stop loss in the same call

Built to teach myself the Pacifica order types by actually using them.

## Setup

```bash
git clone https://github.com/Tinacooking/pacifica-smart-entry.git
cd pacifica-smart-entry
pip install pacifica-sdk

export PACIFICA_KP=your_solana_keypair
export PACIFICA_BASE_URL=https://test-api.pacifica.fi/api/v1   # testnet first

python pacifica_smart_entry.py
```

## Endpoints

- testnet — `https://test-api.pacifica.fi/api/v1`
- mainnet — `https://api.pacifica.fi/api/v1`

Test on testnet for at least a few hundred orders before flipping to mainnet.

## License

MIT
