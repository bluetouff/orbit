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
    "galaxy_score",
    "sentiment",
    "social_dominance",
)
PCT_NUMS = (
    "price_change_percentage_1h_in_currency",
    "price_change_percentage_24h_in_currency",
    "price_change_percentage_7d_in_currency",
    "price_change_percentage_30d_in_currency",
)


def is_num(v):
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)


def in_range(v, lo, hi):
    return is_num(v) and lo <= v <= hi


def clean_text(v, max_len):
    return isinstance(v, str) and v.strip() and len(v) <= max_len and not any(ord(ch) < 32 or ord(ch) == 127 for ch in v)


def fail(msg):
    print("snapshot invalid: " + msg, file=sys.stderr)
    return 1


def validate_global(g):
    if g is None:
        return None
    if not isinstance(g, dict):
        return "global is not an object"
    cap = ((g.get("total_market_cap") or {}).get("usd"))
    if cap is not None and (not is_num(cap) or cap < 0):
        return "global total_market_cap.usd is invalid"
    pct = g.get("market_cap_percentage") or {}
    for key in ("btc", "eth"):
        if pct.get(key) is not None and not in_range(pct[key], 0, 100):
            return f"global market_cap_percentage.{key} is invalid"
    chg = g.get("market_cap_change_percentage_24h_usd")
    if chg is not None and not in_range(chg, -100, 100):
        return "global market_cap_change_percentage_24h_usd is invalid"
    return None


def validate_macro(m):
    if m is None:
        return None
    if not isinstance(m, dict):
        return "macro is not an object"
    for key in ("us10y", "usd"):
        item = m.get(key)
        if item is None:
            continue
        if not isinstance(item, dict):
            return f"macro {key} is not an object"
        if not in_range(item.get("value"), -100000, 100000):
            return f"macro {key}.value is invalid"
        if item.get("change") is not None and not in_range(item["change"], -100000, 100000):
            return f"macro {key}.change is invalid"
        if item.get("date") is not None and not clean_text(item["date"], 16):
            return f"macro {key}.date is invalid"
    return None


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
    if not isinstance(coins, list) or not coins or len(coins) > 1250:
        return fail("coins must be a non-empty list")
    if d.get("count") != len(coins):
        return fail("count does not match coins length")
    err = validate_global(d.get("global"))
    if err:
        return fail(err)
    err = validate_macro(d.get("macro"))
    if err:
        return fail(err)
    seen = set()
    for i, c in enumerate(coins):
        if not isinstance(c, dict):
            return fail(f"coin #{i} is not an object")
        cid, sym, name = c.get("id"), c.get("symbol"), c.get("name")
        if not isinstance(cid, str) or not COIN_ID_RE.fullmatch(cid):
            return fail(f"coin #{i} has invalid id")
        if cid in seen:
            return fail(f"duplicate coin id {cid}")
        seen.add(cid)
        if not isinstance(sym, str) or not SYMBOL_RE.fullmatch(sym):
            return fail(f"{cid} has invalid symbol")
        if not clean_text(name, 96):
            return fail(f"{cid} has invalid name")
        if c.get("asset_type", "crypto") not in ("crypto", "xstock"):
            return fail(f"{cid} has invalid asset_type")
        if c.get("last_updated") is not None:
            observed = c["last_updated"]
            if not clean_text(observed, 40):
                return fail(f"{cid} has invalid last_updated")
            try:
                stamp = datetime.fromisoformat(observed.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    return fail(f"{cid} last_updated needs a timezone")
            except ValueError:
                return fail(f"{cid} has invalid last_updated")
        if c.get('price_source') == 'kraken':
            if c.get('asset_type') != 'xstock' or not re.fullmatch(r'[A-Z0-9.]{1,18}xUSD', str(c.get('market_pair', ''))):
                return fail(f'{cid} has invalid Kraken identity')
            try:
                observed = datetime.fromisoformat(c['last_updated'].replace('Z', '+00:00'))
                checked = datetime.fromisoformat(c['fetched_at'].replace('Z', '+00:00'))
                if observed.tzinfo is None or checked.tzinfo is None or observed.timestamp() <= 0 or observed.timestamp() > checked.timestamp() + 60:
                    return fail(f'{cid} has invalid Kraken dates')
            except (KeyError, TypeError, AttributeError, ValueError):
                return fail(f'{cid} has invalid Kraken dates')
            if any(c.get(k) is not None for k in (*PCT_NUMS, *OPTIONAL_NUMS, 'market_cap', 'total_volume', 'market_cap_rank', 'spark')):
                return fail(f'{cid} mixes unavailable Kraken metrics')
            if not is_num(c.get('current_price')) or c['current_price'] <= 0:
                return fail(f'{cid} has invalid Kraken trade price')
        for k in REQUIRED_NUMS:
            if c.get("asset_type") == "xstock" and k != "current_price" and c.get(k) is None:
                continue
            if not is_num(c.get(k)) or c[k] < 0:
                return fail(f"{cid} has invalid {k}")
        for k in OPTIONAL_NUMS:
            if c.get(k) is not None and not is_num(c.get(k)):
                return fail(f"{cid} has invalid {k}")
        for k in PCT_NUMS:
            if c.get(k) is not None and not in_range(c.get(k), -100, 100000):
                return fail(f"{cid} has invalid {k}")
        if c.get("galaxy_score") is not None and not in_range(c["galaxy_score"], 0, 100):
            return fail(f"{cid} has invalid galaxy_score")
        if c.get("sentiment") is not None and not in_range(c["sentiment"], -100, 100):
            return fail(f"{cid} has invalid sentiment")
        if c.get("social_dominance") is not None and not in_range(c["social_dominance"], 0, 100):
            return fail(f"{cid} has invalid social_dominance")
        rank = c.get("market_cap_rank")
        if rank is not None and (not isinstance(rank, int) or rank < 1):
            return fail(f"{cid} has invalid market_cap_rank")
        if c.get("has_logo") is not None and not isinstance(c.get("has_logo"), bool):
            return fail(f"{cid} has invalid has_logo")
        spark = c.get("spark")
        if spark is not None:
            if not isinstance(spark, list) or not 2 <= len(spark) <= 240 or any((not is_num(x) or x < 0) for x in spark):
                return fail(f"{cid} has invalid spark")
    print(f"snapshot ok: {len(coins)} coins")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: validate_snapshot.py PATH", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
