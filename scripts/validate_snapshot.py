#!/usr/bin/env python3
import json
import math
import re
import sys
from datetime import datetime

COIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$", re.I)
SYMBOL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,19}$", re.I)
REQUIRED_NUMS = ("current_price", "market_cap", "total_volume")
OPTIONAL_NUMS = (
    "ath",
    "circulating_supply",
    "price_change_percentage_1h_in_currency",
    "price_change_percentage_24h_in_currency",
    "price_change_percentage_7d_in_currency",
    "price_change_percentage_30d_in_currency",
    "galaxy_score",
    "sentiment",
    "social_dominance",
)


def is_num(v):
    return isinstance(v, (int, float)) and math.isfinite(v)


def fail(msg):
    print("snapshot invalid: " + msg, file=sys.stderr)
    return 1


def main(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        return fail("root is not an object")
    if not isinstance(d.get("snapshot"), str):
        return fail("missing snapshot timestamp")
    try:
        datetime.strptime(d["snapshot"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return fail("snapshot timestamp must be UTC ISO-8601")
    coins = d.get("coins")
    if not isinstance(coins, list) or not coins:
        return fail("coins must be a non-empty list")
    if d.get("count") != len(coins):
        return fail("count does not match coins length")
    seen = set()
    for i, c in enumerate(coins):
        if not isinstance(c, dict):
            return fail(f"coin #{i} is not an object")
        cid, sym, name = c.get("id"), c.get("symbol"), c.get("name")
        if not isinstance(cid, str) or not COIN_ID_RE.match(cid):
            return fail(f"coin #{i} has invalid id")
        if cid in seen:
            return fail(f"duplicate coin id {cid}")
        seen.add(cid)
        if not isinstance(sym, str) or not SYMBOL_RE.match(sym):
            return fail(f"{cid} has invalid symbol")
        if not isinstance(name, str) or not name.strip() or len(name) > 96:
            return fail(f"{cid} has invalid name")
        for k in REQUIRED_NUMS:
            if not is_num(c.get(k)) or c[k] < 0:
                return fail(f"{cid} has invalid {k}")
        for k in OPTIONAL_NUMS:
            if c.get(k) is not None and not is_num(c.get(k)):
                return fail(f"{cid} has invalid {k}")
        rank = c.get("market_cap_rank")
        if rank is not None and (not isinstance(rank, int) or rank < 1):
            return fail(f"{cid} has invalid market_cap_rank")
        if c.get("has_logo") is not None and not isinstance(c.get("has_logo"), bool):
            return fail(f"{cid} has invalid has_logo")
        spark = c.get("spark")
        if spark is not None:
            if not isinstance(spark, list) or len(spark) < 2 or any((not is_num(x) or x < 0) for x in spark):
                return fail(f"{cid} has invalid spark")
    print(f"snapshot ok: {len(coins)} coins")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: validate_snapshot.py PATH", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
