# Roadmap

## Done
- Component-decomposition valuation: recognize parts, price each from a local
  tracker (seed then learned median), sum into a resale value. See
  `techflip/pricing/`.
- Distance-tiered decisions around Lille (EASY/MEDIUM/HARD), logistics cost
  (drive vs ship), risk-aware. See `techflip/geo.py`, `techflip/decision.py`.
- Feeder/hunt search split; LLM/photo pass gated to far/uncertain deals.

## Next
- Grow `config/pricebook.yaml`: more GPUs/CPUs so full towers stop being
  under-valued (case/PSU/mobo/cooler are still uncounted).
- Seller-trust line in alerts (`scoring/seller.py` + `LeboncoinSource.fetch_seller`
  are ready, not yet wired into the alert).
- Validate the LLM whole-item resale estimate against real sales (laptops/phones
  currently trust the model at 0.5 confidence).
- Per-component recency weighting and outlier trimming in the tracker.
- Optional hard radius on hunt searches via the Leboncoin `locations` URL param.
- systemd service to run the loop at boot.

## Ideas
- Learn from realized resale prices (gone listings) rather than asking prices.
- Second source (La Centrale-style) behind the `sources/` interface.
- Web dashboard (autoscan has one to port).
