from __future__ import annotations

import argparse
import json

from yfinance_mcp.service import OptionsService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", nargs="?", default="NVDA")
    parser.add_argument("--expiry")
    args = parser.parse_args()

    service = OptionsService()
    expirations = service.option_expirations(args.symbol)
    values = expirations["expirations"]
    if not values:
        raise RuntimeError(f"No option expirations returned for {args.symbol}")

    expiry = args.expiry or values[0]
    chain = service.option_chain(
        args.symbol,
        expiry,
        option_type="both",
        limit_per_side=3,
    )
    summary = service.option_positioning_summary(
        args.symbol,
        expiry,
        top_n=3,
    )

    if not chain.get("calls") or not chain.get("puts"):
        raise RuntimeError("Expected both call and put contracts in the smoke-test chain")

    sample_call = chain["calls"][0]
    required = {
        "contractSymbol",
        "strike",
        "bid",
        "ask",
        "volume",
        "openInterest",
        "impliedVolatility",
    }
    missing = sorted(required.difference(sample_call))
    if missing:
        raise RuntimeError(f"Option contract is missing expected fields: {missing}")

    print(
        json.dumps(
            {
                "status": "ok",
                "source": chain["source"],
                "symbol": chain["symbol"],
                "expiry": expiry,
                "expiration_count": expirations["count"],
                "retrieved_at": chain["retrieved_at"],
                "sample_call": {key: sample_call.get(key) for key in sorted(required)},
                "summary": {
                    "call_contracts": summary["calls"]["contracts"],
                    "put_contracts": summary["puts"]["contracts"],
                    "call_total_volume": summary["calls"]["total_volume"],
                    "call_total_open_interest": summary["calls"]["total_open_interest"],
                    "put_total_volume": summary["puts"]["total_volume"],
                    "put_total_open_interest": summary["puts"]["total_open_interest"],
                    "put_call_volume_ratio": summary["put_call"]["volume_ratio"],
                    "put_call_open_interest_ratio": summary["put_call"]["open_interest_ratio"],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
