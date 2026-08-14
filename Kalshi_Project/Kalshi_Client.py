"""One client for everything this project does with Kalshi.

  python Kalshi_Client.py check-auth              is my key working?
  python Kalshi_Client.py markets                 list open markets
  python Kalshi_Client.py sports                  NBA/NFL game + tournament bets
  python Kalshi_Client.py order --ticker ...      place a limit order
  python Kalshi_Client.py cancel                  list / cancel resting orders

Every command takes --env demo|prod. Demo is mock money and is the default
everywhere except `sports`, which reads production market data because demo's
books are nearly empty.

Nothing here can place an order unless you say so: see SAFETY SWITCHES below.

Setup:
  1. Create an API key at demo.kalshi.co (a separate account from kalshi.com).
  2. Save the private key outside this repo, e.g. ~/.kalshi/demo-private-key.pem
  3. Put the key id and that path in Kalshi-API.env
  4. pip install requests cryptography python-dotenv
"""

import argparse
import base64
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# These are the hostnames Kalshi's docs recommend. The older
# demo-api.kalshi.co / api.elections.kalshi.com names still work and serve
# identical data. Credentials are NOT shared between environments: a demo key
# only works against demo, a production key only against production.
HOSTS = {
    # demo — mock money, safe to hit
    "demo": "https://external-api.demo.kalshi.co",
    "prod": "https://external-api.kalshi.com",
}

# Every Kalshi REST path starts with this, and the signature covers it too.
API_PREFIX = "/trade-api/v2"

ENV_FILE = "Kalshi-API.env"

# The API caps a single page at 1000 markets, so we page through with a cursor.
PAGE_SIZE = 100

# Orders are created and cancelled under the events path. The symmetric-looking
# /portfolio/orders/{id} is a deprecated v1 route that answers 410.
ORDERS_PATH = f"{API_PREFIX}/portfolio/events/orders"
# Listing orders, however, really is /portfolio/orders.
ORDERS_LIST_PATH = f"{API_PREFIX}/portfolio/orders"

# ---------------------------------------------------------------------------
# SAFETY SWITCHES
#
# Two INDEPENDENT settings, both defaulting to the safe end. Mixing them up is
# how people lose real money:
#
#   KALSHI_ENV   demo | prod   Which account. demo is mock money.
#   DRY_RUN      true | false  Whether orders are sent, or only printed.
#
#   DRY_RUN=true,  KALSHI_ENV=demo   <- the default. Nothing is ever sent.
#   DRY_RUN=false, KALSHI_ENV=demo   <- real orders, mock money. Stay here a while.
#   DRY_RUN=false, KALSHI_ENV=prod   <- real money. Also needs the ack below.
# ---------------------------------------------------------------------------

REAL_MONEY_ACK = "KALSHI_I_UNDERSTAND_REAL_MONEY"

# A backstop against fat-fingering an order size. Worst-case cost of a single
# order may not exceed this many dollars. Raise deliberately via
# MAX_ORDER_COST_DOLLARS once you trust your own code.
DEFAULT_MAX_ORDER_COST = 10.00

TRUE_VALUES = {"1", "true", "yes", "on", "y"}
FALSE_VALUES = {"0", "false", "no", "off", "n"}


def as_bool(raw, default, name):
    """Read a true/false setting, defaulting to the SAFE value when unclear.

    A typo like DRY_RUN=flase must never be read as "go ahead and trade", so
    anything unrecognised warns and falls back to the default.
    """
    if raw is None or raw.strip() == "":
        return default

    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False

    print(
        f"Warning: {name}={raw!r} is not a true/false value. "
        f"Using the safe default ({default}).",
        file=sys.stderr,
    )
    return default


def dry_run():
    """True when orders should be printed instead of sent. Defaults to True."""
    return as_bool(os.getenv("DRY_RUN"), default=True, name="DRY_RUN")


def max_order_cost():
    """Largest worst-case cost, in dollars, any single order may risk."""
    raw = os.getenv("MAX_ORDER_COST_DOLLARS")
    if raw is None or raw.strip() == "":
        return DEFAULT_MAX_ORDER_COST
    try:
        value = float(raw)
    except ValueError:
        print(
            f"Warning: MAX_ORDER_COST_DOLLARS={raw!r} is not a number. "
            f"Using the safe default (${DEFAULT_MAX_ORDER_COST:.2f}).",
            file=sys.stderr,
        )
        return DEFAULT_MAX_ORDER_COST

    if value <= 0:
        sys.exit("MAX_ORDER_COST_DOLLARS must be greater than 0.")
    return value


def describe_mode(env, dry):
    """One-line banner so the current mode is never a surprise."""
    money = "mock money" if env == "demo" else "REAL MONEY"
    orders = "dry run, nothing sent" if dry else "orders WILL be sent"
    return f"[{env} · {money}] [{orders}]"


def orders_allowed(env, dry, description):
    """Decide whether an order may actually be sent, and say what's happening.

    Returns True only when the order should really go to Kalshi. Called
    immediately before sending; never send one without it.
    """
    if dry:
        print(f"[DRY RUN] would place: {description}")
        print("          (set DRY_RUN=false to send orders for real)")
        return False

    if env == "prod" and not as_bool(
        os.getenv(REAL_MONEY_ACK), default=False, name=REAL_MONEY_ACK
    ):
        sys.exit(
            "Refusing to place a REAL MONEY order.\n"
            f"  DRY_RUN is off and KALSHI_ENV=prod, but {REAL_MONEY_ACK} is not set.\n"
            f"  If that is genuinely what you want, set {REAL_MONEY_ACK}=yes.\n"
            "  Consider running against demo first."
        )

    print(f"[LIVE · {env}] placing: {description}")
    return True


# ---------------------------------------------------------------------------
# Authentication
#
# Kalshi signs each request rather than using a token: build a message from
# timestamp + method + path, sign it with your RSA key, send the signature in
# a header. The server checks it against the public key it kept.
# ---------------------------------------------------------------------------


def load_env():
    """Read Kalshi-API.env into the environment.

    Call this before anything reads os.getenv - notably before argparse builds
    defaults, since argparse evaluates them as the arguments are defined. The
    file is looked up next to this script, not in the current directory.
    """
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ENV_FILE))


def load_private_key(path):
    """Read the RSA private key Kalshi gave you when you created the API key."""
    try:
        with open(path, "rb") as key_file:
            key = serialization.load_pem_private_key(key_file.read(), password=None)
    except FileNotFoundError:
        sys.exit(f"Private key file not found: {path}")
    except TypeError:
        sys.exit(f"Private key at {path} is passphrase-protected; this script expects an unencrypted key.")
    except (ValueError, UnsupportedAlgorithm):
        sys.exit(f"Could not read {path} as a PEM private key. Re-download it from Kalshi.")

    if not isinstance(key, rsa.RSAPrivateKey):
        sys.exit(f"Expected an RSA private key, got {type(key).__name__}.")
    return key


def load_credentials():
    """Return (key_id, private_key), or exit with advice if they're not set up."""
    key_id = os.getenv("KALSHI_API_KEY_ID")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    if not key_id or not key_path:
        sys.exit(
            f"Missing credentials. Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH in {ENV_FILE}."
        )
    return key_id, load_private_key(os.path.expanduser(key_path))


def sign(private_key, message):
    """Sign the message with RSA-PSS + SHA256, which is what Kalshi verifies against."""
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            # Kalshi expects the salt to be the same length as the hash digest.
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    # Headers are text, so the raw signature bytes get base64-encoded.
    return base64.b64encode(signature).decode("utf-8")


def auth_headers(key_id, private_key, method, path):
    """Build the headers every authenticated Kalshi request needs.

    The signed message is timestamp + method + path. The path includes the
    /trade-api/v2 prefix but NOT the query string, so a request for
    /markets?status=open still signs plain /trade-api/v2/markets. The request
    body is not part of the signature.
    """
    timestamp_ms = str(int(time.time() * 1000))
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-SIGNATURE": sign(private_key, timestamp_ms + method + path),
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "accept": "application/json",
        "content-type": "application/json",
    }


def public_get(host, path, params=None):
    """GET an endpoint that needs no credentials, e.g. market data.

    /markets, /events and /series are public: the server ignores auth headers
    on them entirely. Reading them without a key means browsing markets keeps
    working even if your credentials aren't set up yet.
    """
    try:
        return requests.get(host + path, params=params, timeout=15)
    except requests.exceptions.RequestException as exc:
        sys.exit(f"Could not reach {host}: {exc}")


def ensure_ok(response, host):
    """Exit with a readable message instead of a traceback on an HTTP error.

    Separates the two cases that get confused: a 5xx is Kalshi having a
    problem, and there is nothing to fix at your end. The demo environment in
    particular goes down for maintenance fairly often.
    """
    if response.status_code < 400:
        return response

    if response.status_code >= 500:
        sys.exit(
            f"Kalshi returned HTTP {response.status_code} for {host}.\n"
            "  That's a fault on their side, not yours. The demo environment\n"
            "  goes down for maintenance regularly - try again shortly.\n"
            "  Public market data still works with: sports --env prod"
        )

    sys.exit(f"HTTP {response.status_code} from {host}:\n  {response.text[:300]}")


def request(method, host, path, key_id, private_key, params=None, json_body=None):
    """Make one signed request and hand back the response.

    Connection failures exit with a clear message, so they can't be mistaken
    for the server rejecting your credentials - a 401 is an answer FROM
    Kalshi, which means the network was fine.
    """
    try:
        return requests.request(
            method,
            host + path,
            headers=auth_headers(key_id, private_key, method, path),
            params=params,
            json=json_body,
            timeout=10,
        )
    except requests.exceptions.RequestException as exc:
        sys.exit(f"Could not reach {host}: {exc}")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------


def price(market, side):
    """Read one side of the quote, e.g. price(market, "yes_bid").

    A contract pays out $1, so prices run from $0.00 to $1.00. The API sends
    them as dollar strings under names like "yes_bid_dollars" ("0.3000").
    Older examples show integer cents under a bare "yes_bid", so fall back to
    that. Returns cents as an int, or None when there's no quote.
    """
    dollars = market.get(f"{side}_dollars")
    if dollars is not None:
        return round(float(dollars) * 100)

    cents = market.get(side)
    return int(cents) if cents is not None else None


def show(cents):
    """Format a price for the table. A 0 price means nobody's quoting."""
    return f"{cents}c" if cents else "-"


def volume(market):
    """Contracts traded. Sent as a string like "1.00" under "volume_fp"."""
    raw = market.get("volume_fp", market.get("volume"))
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def market_rows(markets, indent=""):
    """Yield formatted lines for a list of markets, columns aligned."""
    # Tickers vary a lot in length, so size the column to the widest one
    # rather than guessing — otherwise long tickers push the columns crooked.
    width = max([len("TICKER")] + [len(m.get("ticker", "?")) for m in markets])

    header = (
        f"{indent}{'TICKER':<{width}} {'YES BID':>7} {'YES ASK':>7} "
        f"{'NO BID':>7} {'NO ASK':>7} {'VOLUME':>8}  TITLE"
    )
    yield header
    yield indent + "-" * (len(header) - len(indent))

    for market in markets:
        yield (
            f"{indent}{market.get('ticker', '?'):<{width}} "
            f"{show(price(market, 'yes_bid')):>7} "
            f"{show(price(market, 'yes_ask')):>7} "
            f"{show(price(market, 'no_bid')):>7} "
            f"{show(price(market, 'no_ask')):>7} "
            f"{volume(market):>8,}  "
            f"{market.get('title', '')}"
        )


def print_markets(markets):
    """Print one line per market: ticker, yes/no prices, volume, title."""
    if not markets:
        print("No open markets returned.")
        return

    for line in market_rows(markets):
        print(line)

    print(f"\n{len(markets)} open market(s).")


# ---------------------------------------------------------------------------
# check-auth
# ---------------------------------------------------------------------------


def cmd_check_auth(args, host, key_id, private_key):
    """Prove the key actually works, by calling an endpoint that requires it.

    Worth understanding: /markets is public. It returns data even with a
    garbage key, because the server never looks at the auth headers. So
    listing markets tells you nothing about whether your key is good.
    /portfolio/balance does require auth, which makes it a real test.
    """
    path = f"{API_PREFIX}/portfolio/balance"
    response = request("GET", host, path, key_id, private_key)

    if response.status_code == 401:
        # A 401 is Kalshi answering, so the network is fine. The usual cause is
        # a key made in the other environment: demo and production are separate
        # accounts with separate keys. Check that before blaming the signature.
        for name, other_host in HOSTS.items():
            if other_host == host:
                continue
            other = request("GET", other_host, path, key_id, private_key)
            if other.status_code >= 500:
                # Can't tell whether the key works there if that host is down.
                print(f"  (couldn't check {name}: it returned HTTP "
                      f"{other.status_code})", file=sys.stderr)
                continue
            if other.status_code == 200:
                sys.exit(
                    f"Credentials rejected by {host}, but they WORK against {name} "
                    f"({other_host}).\n"
                    f"  This key belongs to the {name} environment.\n"
                    f"  Either run with --env {name}, or create a key in the "
                    "environment you meant to use.\n"
                    "  Demo and production are separate accounts; keys are not shared."
                )

        sys.exit(
            "Credentials rejected (401), and they don't work in the other "
            "environment either.\n"
            "  - Is KALSHI_API_KEY_ID the ID Kalshi showed when you made the key?\n"
            "  - Does the private key file match that same key?\n"
            "  - Has the key been revoked?\n"
            "  Note: a 401 comes from Kalshi's server, so your connection is fine."
        )
    ensure_ok(response, host)

    print(f"Credentials OK for {host}.")
    print(f"  balance: {response.json()}")


# ---------------------------------------------------------------------------
# markets
# ---------------------------------------------------------------------------


def get_open_markets(host, key_id, private_key, limit):
    """Fetch up to `limit` open markets, following the cursor across pages."""
    path = f"{API_PREFIX}/markets"
    markets = []
    cursor = None

    while len(markets) < limit:
        # The filter value is "open", but each market reports its own status
        # as "active" — that's expected, not a mismatch.
        params = {"status": "open", "limit": min(PAGE_SIZE, limit - len(markets))}
        if cursor:
            params["cursor"] = cursor

        # Each request is signed separately: the timestamp is part of the signature.
        response = request("GET", host, path, key_id, private_key, params=params)

        if response.status_code == 401:
            sys.exit(
                "401 Unauthorized. Check that the key ID matches the private key, "
                f"and that both belong to the environment you're calling ({host})."
            )
        ensure_ok(response, host)

        payload = response.json()
        page = payload.get("markets", [])
        markets.extend(page)

        # No cursor (or an empty page) means there is nothing left to fetch.
        cursor = payload.get("cursor")
        if not cursor or not page:
            break

    return markets[:limit]


def cmd_markets(args, host, key_id, private_key):
    if args.limit < 1:
        sys.exit("--limit must be at least 1.")

    print(f"\nFetching open markets from {args.env} ({host}{API_PREFIX})...\n")
    print_markets(get_open_markets(host, key_id, private_key, args.limit))


# ---------------------------------------------------------------------------
# sports
#
# Why the series are listed out by hand rather than searched for:
#   - Kalshi has 20,000+ open markets, nearly all multi-game parlays. Paging
#     through them never reaches the NBA/NFL ones.
#   - Filters the API doesn't recognise (category=, tags=) are SILENTLY
#     IGNORED and return unfiltered results, which looks like success.
#   - Matching series by keyword is unreliable both ways: "Pro Football Wins"
#     is season win totals, not a game outcome, while the Super Bowl series is
#     KXSB and contains no "NFL" anywhere in its ticker.
# If a market type is missing, add its series below.
# ---------------------------------------------------------------------------

SERIES = {
    "nfl": {
        "game": [
            ("KXNFLGAME", "Game winner"),
        ],
        "tournament": [
            ("KXSB", "Super Bowl champion"),
            ("KXNFLAFCCHAMP", "AFC champion"),
            ("KXNFLNFCCHAMP", "NFC champion"),
        ],
    },
    "nba": {
        "game": [
            ("KXNBAGAME", "Game winner"),
        ],
        "tournament": [
            ("KXNBA", "Champion"),
            ("KXNBAEAST", "Eastern Conference champion"),
            ("KXNBAWEST", "Western Conference champion"),
            ("KXNBACUP", "Cup champion"),
        ],
    },
}


def series_markets(host, series_ticker):
    """Every open market in one series. Public data, so no signing needed."""
    response = public_get(
        host, f"{API_PREFIX}/markets",
        params={"series_ticker": series_ticker, "status": "open", "limit": 1000},
    )
    if response.status_code != 200:
        return []
    return response.json().get("markets", [])


def cmd_sports(args, host, key_id, private_key):
    leagues = ["nfl", "nba"] if args.league == "both" else [args.league]
    kinds = ["game", "tournament"] if args.kind == "both" else [args.kind]

    rows = [
        (league, ticker, label)
        for league in leagues
        for kind in kinds
        for ticker, label in SERIES[league][kind]
    ]
    print(f"\nReading {len(rows)} series from {args.env} ({host})...\n")

    # Almost all the time here is spent waiting on the network, so fetch the
    # series concurrently rather than one after another.
    with ThreadPoolExecutor(max_workers=8) as pool:
        fetched = list(pool.map(lambda row: series_markets(host, row[1]), rows))

    total = 0
    empty = []
    for (league, ticker, label), markets in zip(rows, fetched):
        if args.min_volume:
            markets = [m for m in markets if volume(m) >= args.min_volume]
        if not markets:
            empty.append(f"{league.upper()} {label.lower()}")
            continue

        # Busiest first, so the tradeable ones are at the top.
        markets.sort(key=volume, reverse=True)
        trimmed = markets[:args.per_series]
        total += len(trimmed)

        print(f"{league.upper()} — {label}  [{ticker}]  {len(markets)} open")
        for line in market_rows(trimmed, indent="  "):
            print(line)
        if len(markets) > len(trimmed):
            print(f"  ... {len(markets) - len(trimmed)} more (raise --per-series)")
        print()

    print(f"{total} market(s) shown.")
    if empty:
        # Out-of-season markets simply have nothing open; say so rather than
        # leaving a silent gap in the output.
        print(f"Nothing open right now for: {', '.join(empty)}.")
    if not total:
        sys.exit("No open markets matched. Try --min-volume 0, or check the season.")


# ---------------------------------------------------------------------------
# order
# ---------------------------------------------------------------------------


def look_up_market(host, key_id, private_key, ticker):
    """Fetch one market so we can reject typo'd tickers before ordering."""
    response = request("GET", host, f"{API_PREFIX}/markets/{ticker}", key_id, private_key)

    if response.status_code == 404:
        sys.exit(
            f"No market with ticker {ticker!r} in this environment.\n"
            "  Run the `sports` or `markets` command to see valid tickers, and "
            "check you're on the right environment."
        )
    ensure_ok(response, host)

    # A single-market lookup wraps the market in a "market" key.
    return response.json().get("market", {})


def worst_case_cost(side, count, price_cents):
    """Most you can lose on this order, in dollars.

    Buying YES risks what you pay: count x price. Selling YES risks the rest
    of the dollar, because the contract settles at $1.00 and you'd owe the
    difference: count x (100 - price).
    """
    risk_cents = price_cents if side == "bid" else 100 - price_cents
    return count * risk_cents / 100


def build_order(ticker, side, count, price_cents, time_in_force):
    """Build the request body.

    Counts and prices go over the wire as fixed-point decimal STRINGS, not
    numbers - "1.00" and "0.3000", never 1 and 0.3.
    """
    return {
        "ticker": ticker,
        # A unique id per order. If a reply gets lost and you retry, Kalshi can
        # tell it's the same order rather than placing a second one.
        "client_order_id": str(uuid.uuid4()),
        "side": side,
        "count": f"{count}.00",
        "price": f"{price_cents / 100:.4f}",
        "time_in_force": time_in_force,
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
    }


def describe_order(order, market, cost):
    """A human sentence for the order, so you can check it before it goes."""
    verb = "BUY YES" if order["side"] == "bid" else "SELL YES"
    title = market.get("title", "")
    lines = [
        f"{verb} {order['count']} contract(s) of {order['ticker']}",
        f"    at ${order['price']} each, {order['time_in_force']}",
        f"    worst-case cost: ${cost:.2f}",
    ]
    if title:
        lines.append(f"    market: {title}")
    if market.get("yes_bid_dollars") is not None:
        lines.append(
            f"    current book: yes bid ${market.get('yes_bid_dollars')} / "
            f"yes ask ${market.get('yes_ask_dollars')}"
        )
    return "\n".join(lines)


def cmd_order(args, host, key_id, private_key):
    if args.count < 1:
        sys.exit("--count must be at least 1.")
    if not 1 <= args.price_cents <= 99:
        sys.exit("--price-cents must be between 1 and 99 (a contract settles at 100c).")

    # Check the ticker exists before doing anything else - a typo here is the
    # easiest way to send an order you didn't mean.
    market = look_up_market(host, key_id, private_key, args.ticker)
    if market.get("status") != "active":
        sys.exit(f"Market {args.ticker} is not active (status: {market.get('status')}).")

    cost = worst_case_cost(args.side, args.count, args.price_cents)
    cap = max_order_cost()
    if cost > cap:
        sys.exit(
            f"Refusing: worst-case cost ${cost:.2f} exceeds the ${cap:.2f} limit.\n"
            "  Lower --count or --price-cents, or raise MAX_ORDER_COST_DOLLARS "
            "deliberately."
        )

    order = build_order(args.ticker, args.side, args.count, args.price_cents,
                        args.time_in_force)
    print()
    print(describe_order(order, market, cost))
    print()

    # The single gate that decides whether this is real. Everything above is
    # preparation; nothing has been sent yet.
    if not orders_allowed(args.env, args.is_dry_run,
                          f"{args.side} {args.count} @ {args.price_cents}c"):
        print("\nRequest body that WOULD have been sent:")
        print(json.dumps(order, indent=2))
        return

    response = request("POST", host, ORDERS_PATH, key_id, private_key, json_body=order)
    if response.status_code >= 400:
        sys.exit(f"Order rejected (HTTP {response.status_code}):\n  {response.text[:500]}")

    placed = response.json().get("order", response.json())
    print("\nOrder accepted.")
    print(f"  order_id: {placed.get('order_id')}")
    print(f"  status:   {placed.get('status')}")
    print(f"  filled:   {placed.get('fill_count_fp')} of {placed.get('initial_count_fp')}")


# ---------------------------------------------------------------------------
# cancel
#
# A deliberate difference from `order`: cancelling is NOT gated behind DRY_RUN.
# That switch exists to stop you taking on exposure you didn't intend, and a
# cancel does the opposite - it removes exposure. A safety setting that
# prevented you from cancelling would be actively dangerous. Pass --dry-run
# explicitly if you only want to look.
# ---------------------------------------------------------------------------


def list_orders(host, key_id, private_key, status="resting"):
    """Fetch your orders, as the API returns them."""
    response = request("GET", host, ORDERS_LIST_PATH, key_id, private_key,
                       params={"status": status})
    if response.status_code == 401:
        sys.exit(
            f"Credentials rejected by {host}.\n"
            "  Run `check-auth` to work out which environment your key belongs to."
        )
    ensure_ok(response, host)
    return response.json().get("orders", [])


def print_orders(orders):
    """One line per order, columns aligned."""
    if not orders:
        print("No resting orders.")
        return

    width = max([len("ORDER ID")] + [len(o.get("order_id", "")) for o in orders])
    header = (f"{'ORDER ID':<{width}} {'SIDE':<4} {'YES PRICE':>9} "
              f"{'REMAINING':>9}  TICKER")
    print(header)
    print("-" * len(header))

    for order in orders:
        # outcome_side is yes/no; book_side is the bid/ask wording.
        side = order.get("outcome_side") or order.get("book_side") or "?"
        print(
            f"{order.get('order_id', '?'):<{width}} "
            f"{side:<4} "
            f"{'$' + str(order.get('yes_price_dollars', '?')):>9} "
            f"{order.get('remaining_count_fp', '?'):>9}  "
            f"{order.get('ticker', '?')}"
        )
    print(f"\n{len(orders)} resting order(s).")


def cancel_one(host, key_id, private_key, order_id):
    """Cancel one order. Returns True if it's now gone."""
    response = request("DELETE", host, f"{ORDERS_PATH}/{order_id}", key_id, private_key)

    if response.status_code == 404:
        # Already filled, already cancelled, or simply not yours.
        print(f"  {order_id}: not found (already filled or cancelled?)")
        return False
    if response.status_code >= 400:
        print(f"  {order_id}: failed (HTTP {response.status_code}) {response.text[:120]}")
        return False

    body = response.json()
    print(f"  {order_id}: cancelled, {body.get('reduced_by', '?')} contract(s) removed")
    return True


def cmd_cancel(args, host, key_id, private_key):
    if args.order_id and args.all:
        sys.exit("Use either --order-id or --all, not both.")

    # No cancel requested: just show what's resting.
    if not args.order_id and not args.all:
        print()
        print_orders(list_orders(host, key_id, private_key))
        print("\nTo cancel: --order-id <ID>, or --all")
        return

    if args.order_id:
        targets = [args.order_id]
    else:
        orders = list_orders(host, key_id, private_key)
        if not orders:
            print("\nNo resting orders to cancel.")
            return
        print()
        print_orders(orders)
        targets = [o["order_id"] for o in orders]

    print()
    if args.preview:
        print(f"[DRY RUN] would cancel {len(targets)} order(s):")
        for order_id in targets:
            print(f"  {order_id}")
        return

    print(f"Cancelling {len(targets)} order(s) on {args.env}:")
    cancelled = sum(cancel_one(host, key_id, private_key, oid) for oid in targets)
    print(f"\n{cancelled} of {len(targets)} cancelled.")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="Kalshi client: browse markets, place and cancel orders.")
    subs = parser.add_subparsers(dest="command", required=True)

    def add_env(sub, default="demo"):
        sub.add_argument("--env", choices=sorted(HOSTS),
                         default=os.getenv("KALSHI_ENV", default),
                         help=f"which Kalshi environment (default {default})")

    check = subs.add_parser("check-auth", help="verify your API key works")
    add_env(check)
    check.set_defaults(func=cmd_check_auth, needs_auth=True)

    markets = subs.add_parser("markets", help="list open markets")
    markets.add_argument("--limit", type=int, default=25,
                         help="how many markets to show (default 25)")
    add_env(markets)
    markets.set_defaults(func=cmd_markets, needs_auth=True)

    sports = subs.add_parser("sports", help="NBA/NFL game and tournament markets")
    sports.add_argument("--league", choices=["nba", "nfl", "both"], default="both")
    sports.add_argument("--kind", choices=["game", "tournament", "both"], default="both",
                        help="single-game winners, championships, or both")
    sports.add_argument("--min-volume", type=int, default=0, dest="min_volume",
                        help="hide markets below this traded volume")
    sports.add_argument("--per-series", type=int, default=12, dest="per_series",
                        help="max markets shown per series (default 12)")
    # Market data is public, so this reads production by default: demo's sports
    # books are nearly empty.
    sports.add_argument("--env", choices=sorted(HOSTS), default="prod",
                        help="whose market data to read (default prod)")
    sports.set_defaults(func=cmd_sports, needs_auth=False)

    order = subs.add_parser("order", help="place one limit order")
    order.add_argument("--ticker", required=True, help="market ticker")
    order.add_argument("--side", required=True, choices=["bid", "ask"],
                       help="bid = buy YES, ask = sell YES (economically, buy NO)")
    order.add_argument("--count", required=True, type=int, help="number of contracts")
    order.add_argument("--price-cents", required=True, type=int, dest="price_cents",
                       help="limit price per contract, in cents (1-99)")
    order.add_argument("--time-in-force", default="good_till_canceled",
                       dest="time_in_force",
                       choices=["good_till_canceled", "immediate_or_cancel", "fill_or_kill"],
                       help="how long the order rests (default good_till_canceled)")
    add_env(order)
    # A command-line flag beats the .env, so you can force safety for one run.
    mode = order.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=None,
                      help="print the order without sending it (the default)")
    mode.add_argument("--live", dest="dry_run", action="store_false",
                      help="actually send the order")
    order.set_defaults(func=cmd_order, needs_auth=True)

    cancel = subs.add_parser("cancel", help="list or cancel resting orders")
    cancel.add_argument("--order-id", dest="order_id", help="cancel this one order")
    cancel.add_argument("--all", action="store_true", help="cancel every resting order")
    cancel.add_argument("--dry-run", action="store_true", dest="preview",
                        help="show what would be cancelled, without cancelling")
    add_env(cancel)
    cancel.set_defaults(func=cmd_cancel, needs_auth=True)

    return parser


def main():
    # Load the .env FIRST. Argparse evaluates its defaults as the arguments are
    # defined, so anything read from the environment has to already be in place
    # — otherwise KALSHI_ENV and DRY_RUN in the .env would be ignored.
    load_env()

    args = build_parser().parse_args()
    host = HOSTS[args.env]

    # Only `order` acts on the dry-run switch; the others can't send anything.
    args.is_dry_run = dry_run() if getattr(args, "dry_run", None) is None else args.dry_run
    if args.command != "sports":
        print(describe_mode(args.env, args.is_dry_run))

    key_id = private_key = None
    if args.needs_auth:
        key_id, private_key = load_credentials()

    args.func(args, host, key_id, private_key)


if __name__ == "__main__":
    main()
