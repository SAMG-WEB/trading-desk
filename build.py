#!/usr/bin/env python3
"""
The Trading Desk — daily market e-paper builder.

Fetches indices / forex / commodities via yfinance (free, unofficial Yahoo
Finance data) and top market headlines via RSS, then renders a static
index.html into docs/ for GitHub Pages to serve.

No API keys required. Designed to run once a day via GitHub Actions,
but you can also run it manually any time:  python build.py
"""

import datetime as dt
import html
import sys

import feedparser
import pytz
import yfinance as yf

IST = pytz.timezone("Asia/Kolkata")

# ---------------------------------------------------------------------------
# 1. WHAT TO FETCH
# ---------------------------------------------------------------------------

INDIAN_INDICES = [
    ("Nifty 50", "^NSEI"),
    ("Sensex", "^BSESN"),
    ("Bank Nifty", "^NSEBANK"),
    ("Nifty IT", "^CNXIT"),
]

US_INDICES = [
    ("S&P 500", "^GSPC"),
    ("Dow Jones", "^DJI"),
    ("Nasdaq Composite", "^IXIC"),
]

ASIAN_INDICES = [
    ("Nikkei 225 (Japan)", "^N225"),
    ("Hang Seng (Hong Kong)", "^HSI"),
    ("Shanghai Composite", "000001.SS"),
    ("Kospi (South Korea)", "^KS11"),
]

COMMODITIES_FX = [
    ("USD / INR", "INR=X", "₹", ""),
    ("Crude Oil (Brent)", "BZ=F", "$", "/bbl"),
    ("Crude Oil (WTI)", "CL=F", "$", "/bbl"),
    ("Gold (Comex)", "GC=F", "$", "/oz"),
    ("Silver (Comex)", "SI=F", "$", "/oz"),
]

# NSE sectoral indices. Yahoo's coverage of these is inconsistent — the
# script silently skips any ticker that fails to fetch.
SECTORS = [
    ("Auto", "^CNXAUTO"), ("IT", "^CNXIT"), ("Metal", "^CNXMETAL"),
    ("Bank", "^NSEBANK"), ("Financial Services", "^CNXFIN"),
    ("Pharma", "^CNXPHARMA"), ("FMCG", "^CNXFMCG"),
    ("Realty", "^CNXREALTY"), ("PSU Bank", "^CNXPSUBANK"),
    ("Energy", "^CNXENERGY"), ("Media", "^CNXMEDIA"),
    ("Private Bank", "^NIFTYPVTBANK"),
]

# RSS feeds for market-moving Indian news. Feel free to add/remove sources.
NEWS_FEEDS = [
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.business-standard.com/rss/markets-106.rss",
]

# Keywords used to keep the news list relevant to Indian markets specifically.
NEWS_KEYWORDS = [
    "nifty", "sensex", "rbi", "sebi", "rupee", "fii", "dii", "q1", "q2",
    "earnings", "results", "bank nifty", "crude", "psu", "ipo", "india",
    "gst", "budget", "inflation", "repo rate", "monsoon session", "nse", "bse",
]

MAX_NEWS_ITEMS = 16
IMPACT_HIGH = ["rbi","sebi","repo rate","rate cut","rate hike","tariff","crude","oil","hormuz","iran","israel","war","inflation","gdp","fii","fpi","nifty","sensex","bank nifty","earnings","results","guidance"]
IMPACT_MEDIUM = ["ipo","order","capex","dividend","merger","acquisition","promoter","production","export","import","rupee","fed","jobs"]

# ---------------------------------------------------------------------------
# 2. MANUAL OVERRIDES — edit this by hand whenever you want curated
#    "who's leading this sector" detail instead of just the index number.
#    Leave a sector out of this dict and the page will just show its % move.
# ---------------------------------------------------------------------------

HOT_SECTOR_NOTES = {
    "Auto": "Broad-based buying across the auto pack.",
    "IT": "Watch for follow-through after last week's rebound.",
    "Metal": "Tracking global commodity prices.",
    "PSU Bank": "Momentum has been the standout theme this year.",
}

SECTOR_STOCKS = {
    "Auto": ["M&M.NS","MARUTI.NS","TATAMOTORS.NS","TVSMOTOR.NS","EICHERMOT.NS","BAJAJ-AUTO.NS"],
    "Bank": ["HDFCBANK.NS","ICICIBANK.NS","AXISBANK.NS","KOTAKBANK.NS","SBIN.NS","INDUSINDBK.NS"],
    "Financial Services": ["BAJFINANCE.NS","BAJAJFINSV.NS","SHRIRAMFIN.NS","CHOLAFIN.NS","SBILIFE.NS"],
    "IT": ["TCS.NS","INFY.NS","HCLTECH.NS","WIPRO.NS","TECHM.NS","LTIM.NS"],
    "Metal": ["TATASTEEL.NS","HINDALCO.NS","JSWSTEEL.NS","JINDALSTEL.NS","SAIL.NS","NMDC.NS"],
    "Pharma": ["SUNPHARMA.NS","CIPLA.NS","DRREDDY.NS","DIVISLAB.NS","LUPIN.NS"],
    "FMCG": ["HINDUNILVR.NS","ITC.NS","NESTLEIND.NS","BRITANNIA.NS","TATACONSUM.NS","DABUR.NS"],
    "Realty": ["DLF.NS","LODHA.NS","GODREJPROP.NS","OBEROIRLTY.NS","PRESTIGE.NS"],
    "PSU Bank": ["SBIN.NS","BANKBARODA.NS","PNB.NS","CANBK.NS","UNIONBANK.NS","INDIANB.NS"],
    "Energy": ["RELIANCE.NS","ONGC.NS","COALINDIA.NS","NTPC.NS","POWERGRID.NS","BPCL.NS"],
    "Media": ["ZEEL.NS","SUNTV.NS","PVRINOX.NS","NETWORK18.NS"],
    "Private Bank": ["HDFCBANK.NS","ICICIBANK.NS","AXISBANK.NS","KOTAKBANK.NS","FEDERALBNK.NS"],
}


# ---------------------------------------------------------------------------
# 3. FETCH HELPERS
# ---------------------------------------------------------------------------

def fetch_quote(ticker: str):
    """Return (last_price, change, pct_change) for a ticker, or None on failure."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d")
        if len(hist) < 2:
            return None
        last = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2]
        change = last - prev
        pct = (change / prev) * 100
        return (last, change, pct)
    except Exception as exc:  # noqa: BLE001 — we want the page to build regardless
        print(f"  ! failed to fetch {ticker}: {exc}", file=sys.stderr)
        return None


def fetch_stock_metrics(ticker):
    try:
        h=yf.Ticker(ticker).history(period="1mo")
        h=h.dropna(subset=["Close"])
        if len(h)<6: return None
        c=h["Close"]; last=float(c.iloc[-1]); prev=float(c.iloc[-2]); week=float(c.iloc[-6])
        vr=None
        if "Volume" in h.columns and len(h)>=21:
            avg=h["Volume"].iloc[:-1].tail(20).mean()
            if avg and avg>0: vr=float(h["Volume"].iloc[-1]/avg)
        return {"ticker":ticker,"pct1":(last/prev-1)*100,"pct5":(last/week-1)*100,"vr":vr}
    except Exception: return None

def sector_leader_card(sec):
    ms=[m for t in SECTOR_STOCKS.get(sec["label"],[]) if (m:=fetch_stock_metrics(t))]
    if not ms: return f'<div class="hot-card"><div class="hname">{html.escape(sec["label"])} <span class="hmomentum">{sec["pct"]:+.2f}%</span></div><div class="hstocks">Leader data unavailable.</div></div>'
    for m in ms: m["score"]=m["pct1"]*.45+m["pct5"]*.4+max(0,(m["vr"] or 1)-1)*1.5
    ms.sort(key=lambda x:x["score"],reverse=True); leaders=ms[:3]
    breadth=sum(m["pct1"]>0 for m in ms)
    txt=" · ".join(f'{m["ticker"].replace(".NS","")} {m["pct1"]:+.2f}% / 5D {m["pct5"]:+.2f}%' for m in leaders)
    return f'<div class="hot-card"><div class="hname">{html.escape(sec["label"])} <span class="hmomentum">{sec["pct"]:+.2f}%</span></div><div class="hstocks"><strong>Leaders:</strong> {html.escape(txt)}<br>Breadth: {breadth}/{len(ms)} positive</div></div>'

def fmt_num(x, decimals=2):
    return f"{x:,.{decimals}f}"


def fetch_group(items):
    """items: list of (label, ticker) -> list of dicts with quote data."""
    out = []
    for label, ticker in items:
        q = fetch_quote(ticker)
        if q is None:
            out.append({"label": label, "ok": False})
            continue
        last, change, pct = q
        out.append({
            "label": label,
            "ok": True,
            "last": last,
            "change": change,
            "pct": pct,
            "up": change >= 0,
        })
    return out


def fetch_news():
    seen_titles = set()
    items = []
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! failed to fetch feed {url}: {exc}", file=sys.stderr)
            continue
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            if not title or title in seen_titles:
                continue
            lower = title.lower()
            if not any(k in lower for k in NEWS_KEYWORDS):
                continue
            seen_titles.add(title)
            blob = f"{title} {entry.get('summary','')}".lower()
            impact = "HIGH" if any(k in blob for k in IMPACT_HIGH) else ("MEDIUM" if any(k in blob for k in IMPACT_MEDIUM) else "LOW")
            items.append({"title":title,"link":entry.get("link","#"),"summary":(entry.get("summary","") or "")[:220],"impact":impact})
    rank={"HIGH":3,"MEDIUM":2,"LOW":1}
    items.sort(key=lambda x:rank[x["impact"]],reverse=True)
    return items[:MAX_NEWS_ITEMS]


# ---------------------------------------------------------------------------
# 4. RENDER
# ---------------------------------------------------------------------------

def idx_row(item):
    if not item["ok"]:
        return f"""
      <div class="idx-row">
        <div class="idx-name">{html.escape(item['label'])}</div>
        <div class="idx-vals">data unavailable</div>
      </div>"""
    arrow = "▲" if item["up"] else "▼"
    cls = "up" if item["up"] else "down"
    return f"""
      <div class="idx-row">
        <div class="idx-name">{html.escape(item['label'])}</div>
        <div class="idx-vals">{fmt_num(item['last'])} <span class="{cls} badge badge-{cls}">{arrow} {fmt_num(item['change'])} ({item['pct']:+.2f}%)</span></div>
      </div>"""


def comm_card(item, symbol, suffix):
    if not item["ok"]:
        return f"""
      <div class="comm-card">
        <div><div class="comm-name">{html.escape(item['label'])}</div></div>
        <div class="comm-val">data unavailable</div>
      </div>"""
    cls = "up" if item["up"] else "down"
    arrow = "▲" if item["up"] else "▼"
    return f"""
      <div class="comm-card">
        <div><div class="comm-name">{html.escape(item['label'])}</div></div>
        <div class="comm-val">{symbol}{fmt_num(item['last'])}{suffix} <span class="{cls}">{arrow} {item['pct']:+.2f}%</span></div>
      </div>"""


def sector_tile(item):
    if not item["ok"]:
        return ""
    cls = "tile-up" if item["up"] else "tile-down"
    note = HOT_SECTOR_NOTES.get(item["label"], "")
    note_html = f'<div style="font-size:9.5px;color:var(--ink-soft);margin-top:3px;">{html.escape(note)}</div>' if note else ""
    return f"""
      <div class="sector-tile {cls}">
        <div class="sname">{html.escape(item['label'])}</div>
        <div class="schg">{item['pct']:+.2f}%</div>
        {note_html}
      </div>"""


def news_item(item, tag="India"):
    return f"""
    <div class="news-item">
      <h3><span class="news-tag impact-{item.get("impact","LOW").lower()}">{html.escape(item.get("impact","LOW"))}</span>{html.escape(item["title"])}</h3>
      <p><a href="{html.escape(item['link'])}" target="_blank" rel="noopener">Read full story →</a></p>
    </div>"""


def ticker_span(item, symbol="", suffix=""):
    if not item["ok"]:
        return ""
    cls = "up" if item["up"] else "down"
    arrow = "▲" if item["up"] else "▼"
    return f'<span>{html.escape(item["label"])} <span class="{cls}">{symbol}{fmt_num(item["last"])}{suffix} {arrow} {item["pct"]:+.2f}%</span></span>'


def build():
    now_ist = dt.datetime.now(IST)
    today_str = now_ist.strftime("%A, %d %B %Y").upper()

    print("Fetching Indian indices...")
    indian = fetch_group(INDIAN_INDICES)
    print("Fetching US indices...")
    us = fetch_group(US_INDICES)
    print("Fetching Asian indices...")
    asian = fetch_group(ASIAN_INDICES)
    print("Fetching commodities & FX...")
    comm = fetch_group([(l, t) for l, t, _, _ in COMMODITIES_FX])
    print("Fetching sectors...")
    sectors = fetch_group(SECTORS)
    print("Fetching news...")
    news = fetch_news()

    ok_sectors = [s for s in sectors if s["ok"]]
    nifty_pct = next((x["pct"] for x in indian if x["label"]=="Nifty 50" and x["ok"]), 0)
    for s in ok_sectors:
        s["relative"] = s["pct"] - nifty_pct
        s["rank_score"] = s["pct"]*.7 + s["relative"]*.3
    top_sectors = sorted(ok_sectors, key=lambda s:s["rank_score"], reverse=True)[:4]

    ticker_parts = []
    for item in indian + us:
        span = ticker_span(item)
        if span:
            ticker_parts.append(span)
    ticker_html = "\n      ".join(ticker_parts * 2)  # duplicate for seamless scroll

    indian_rows = "".join(idx_row(i) for i in indian)
    us_rows = "".join(idx_row(i) for i in us)
    asian_rows = "".join(idx_row(i) for i in asian)

    comm_cards = ""
    for item, (_, _, symbol, suffix) in zip(comm, COMMODITIES_FX):
        comm_cards += comm_card(item, symbol, suffix)

    sector_tiles = "".join(sector_tile(s) for s in sectors if s["ok"])

    hot_cards = "".join(sector_leader_card(x) for x in top_sectors)

    news_html = "".join(news_item(n) for n in news) if news else \
        '<p style="font-family:Inter,sans-serif;font-size:13px;color:var(--ink-soft);">No matching headlines found this run — check back after the next update.</p>'

    html_out = HTML_TEMPLATE.format(
        today_str=today_str,
        ticker_html=ticker_html,
        indian_rows=indian_rows,
        us_rows=us_rows,
        asian_rows=asian_rows,
        comm_cards=comm_cards,
        sector_tiles=sector_tiles,
        hot_cards=hot_cards,
        news_html=news_html,
        generated_at=now_ist.strftime("%d %b %Y, %H:%M IST"),
    )

    import os
    os.makedirs("docs", exist_ok=True)

    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_out)

    print("Wrote docs/index.html")


# ---------------------------------------------------------------------------
# 5. TEMPLATE — same visual design as the original artifact
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>The Trading Desk — Daily Market Brief</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap');
:root{{
  --paper:#f6f1e6; --paper-dim:#efe8d8; --ink:#1c1b17; --ink-soft:#5c574a;
  --rule:#c9bd9e; --navy:#1f2b45; --gain:#1c6e42; --gain-bg:#e3efe3;
  --loss:#a53523; --loss-bg:#f4e3de; --gold:#9c6b1f; --gold-bg:#f3e8cf;
}}
*{{box-sizing:border-box;}}
body{{margin:0;background:#d8d0ba;font-family:'Source Serif 4',serif;color:var(--ink);padding:18px 0 60px;}}
.sheet{{max-width:1180px;margin:0 auto;background:var(--paper);box-shadow:0 6px 30px rgba(0,0,0,0.25);border:1px solid var(--rule);}}
.masthead{{padding:26px 36px 16px;border-bottom:4px double var(--ink);text-align:center;}}
.masthead .eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:3px;color:var(--ink-soft);text-transform:uppercase;}}
.masthead h1{{font-family:'Fraunces',serif;font-weight:700;font-size:56px;margin:6px 0 4px;letter-spacing:-0.5px;}}
.masthead .tagline{{font-style:italic;color:var(--ink-soft);font-size:15px;}}
.masthead .meta-row{{display:flex;justify-content:space-between;font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:var(--ink-soft);margin-top:14px;padding-top:10px;border-top:1px solid var(--rule);flex-wrap:wrap;gap:6px;}}
.ticker-wrap{{background:var(--navy);color:#f1ead8;overflow:hidden;white-space:nowrap;border-bottom:1px solid var(--ink);}}
.ticker{{display:inline-block;padding:9px 0;font-family:'IBM Plex Mono',monospace;font-size:12.5px;animation:scroll 42s linear infinite;}}
.ticker span{{margin:0 26px;}}
.ticker .up{{color:#8fd6a6;}} .ticker .down{{color:#f2a394;}}
@keyframes scroll{{0%{{transform:translateX(0%);}}100%{{transform:translateX(-50%);}}}}
.grid{{display:grid;grid-template-columns:1.55fr 1fr;gap:0;border-bottom:1px solid var(--rule);}}
.col-left{{padding:22px 24px;border-right:1px solid var(--rule);}}
.col-right{{padding:22px 24px;background:var(--paper-dim);}}
.section-label{{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:2.5px;text-transform:uppercase;color:var(--navy);border-bottom:2px solid var(--ink);padding-bottom:6px;margin-bottom:12px;}}
.subgroup-label{{font-family:'Inter',sans-serif;font-weight:600;font-size:12.5px;color:var(--ink-soft);margin:16px 0 8px;text-transform:uppercase;letter-spacing:1px;}}
.idx-row{{display:flex;justify-content:space-between;align-items:baseline;padding:8px 0;border-bottom:1px dashed var(--rule);}}
.idx-name{{font-family:'Inter',sans-serif;font-weight:600;font-size:14px;}}
.idx-vals{{font-family:'IBM Plex Mono',monospace;text-align:right;font-size:13px;}}
.up{{color:var(--gain);font-weight:600;}} .down{{color:var(--loss);font-weight:600;}}
.badge-up{{background:var(--gain-bg);color:var(--gain);}} .badge-down{{background:var(--loss-bg);color:var(--loss);}}
.badge{{display:inline-block;padding:1px 7px;border-radius:3px;font-size:12px;font-weight:600;}}
.comm-card{{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;margin-bottom:8px;background:var(--paper);border:1px solid var(--rule);}}
.comm-name{{font-family:'Inter',sans-serif;font-weight:600;font-size:13.5px;}}
.comm-val{{font-family:'IBM Plex Mono',monospace;text-align:right;font-size:13.5px;}}
.sector-section{{padding:22px 24px;border-bottom:1px solid var(--rule);}}
.sector-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:6px;}}
.sector-tile{{padding:12px 10px;border:1px solid var(--rule);text-align:center;}}
.sector-tile .sname{{font-family:'Inter',sans-serif;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:0.4px;}}
.sector-tile .schg{{font-family:'IBM Plex Mono',monospace;font-size:16px;font-weight:600;margin-top:4px;}}
.tile-up{{background:var(--gain-bg);}} .tile-up .schg{{color:var(--gain);}}
.tile-down{{background:var(--loss-bg);}} .tile-down .schg{{color:var(--loss);}}
.hot-section{{padding:22px 24px;border-bottom:1px solid var(--rule);background:var(--gold-bg);}}
.hot-header{{display:flex;align-items:baseline;gap:10px;margin-bottom:14px;border-bottom:2px solid var(--gold);padding-bottom:6px;}}
.hot-header h2{{font-family:'Fraunces',serif;font-size:22px;margin:0;}}
.hot-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;}}
.hot-card{{background:var(--paper);border:1px solid var(--rule);padding:14px 16px;}}
.hot-card .hname{{font-family:'Inter',sans-serif;font-weight:700;font-size:14.5px;display:flex;justify-content:space-between;align-items:center;}}
.hot-card .hmomentum{{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--gain);font-weight:600;}}
.hot-card .hstocks{{font-family:'Inter',sans-serif;font-size:12.5px;color:var(--ink-soft);margin-top:6px;line-height:1.5;}}
.news-section{{padding:22px 24px 28px;}}
.news-item{{padding:12px 0;border-bottom:1px solid var(--rule);}}
.news-item h3{{font-family:'Fraunces',serif;font-size:16px;margin:0 0 4px;font-weight:600;}}
.news-item p{{margin:0;font-size:13px;}}
.news-item a{{color:var(--navy);}}
.news-tag{{font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--navy);background:#e4e1d3;padding:2px 7px;margin-right:8px;}}
.footer{{padding:18px 24px 26px;font-family:'Inter',sans-serif;font-size:11px;color:var(--ink-soft);line-height:1.6;background:var(--paper-dim);}}
@media (max-width:800px){{.grid{{grid-template-columns:1fr;}} .col-left{{border-right:none;border-bottom:1px solid var(--rule);}} .sector-grid{{grid-template-columns:repeat(2,1fr);}} .hot-grid{{grid-template-columns:1fr;}} .masthead h1{{font-size:38px;}}}}
 .impact-high{{background:var(--loss-bg);color:var(--loss);}} .impact-medium{{background:var(--gold-bg);color:var(--gold);}} .impact-low{{background:#e4e1d3;color:var(--ink-soft);}}</style>
</head>
<body>
<div class="sheet">
  <div class="masthead">
    <div class="eyebrow">Personal Trading Desk · Auto-Updated Daily</div>
    <h1>THE MARKET BRIEF</h1>
    <div class="tagline">Indices · Sectors · Money Flow · News — before the opening bell</div>
    <div class="meta-row">
      <span>{today_str}</span>
      <span>LAST BUILT: {generated_at}</span>
    </div>
  </div>

  <div class="ticker-wrap">
    <div class="ticker">
      {ticker_html}
    </div>
  </div>

  <div class="grid">
    <div class="col-left">
      <div class="section-label">World Indices</div>
      <div class="subgroup-label">🇮🇳 Indian Indices</div>
      {indian_rows}
      <div class="subgroup-label">🇺🇸 US Indices</div>
      {us_rows}
      <div class="subgroup-label">🌏 Asian Indices</div>
      {asian_rows}
    </div>
    <div class="col-right">
      <div class="section-label">Currency &amp; Commodities</div>
      {comm_cards}
    </div>
  </div>

  <div class="sector-section">
    <div class="section-label">Indian Sectors — Today's Move</div>
    <div class="sector-grid">
      {sector_tiles}
    </div>
  </div>

  <div class="hot-section">
    <div class="hot-header">
      <h2>🔥 Where the Money's Moving</h2>
      <div class="section-label">Relative strength + sector leaders</div>
    </div>
    <div class="hot-grid">
      {hot_cards}
    </div>
  </div>

  <div class="news-section">
    <div class="section-label">News That Could Move Indian Markets</div>
    {news_html}
  </div>

  <div class="footer">
    <strong>How this page works:</strong> Rebuilt automatically once a day by a GitHub Actions workflow, using free Yahoo Finance data (via yfinance) and public market-news RSS feeds. This is informational only, not investment advice — verify live prices with your broker/terminal before trading. Data can lag or occasionally fail to load for a given symbol (shown as "data unavailable").
  </div>
</div>
</body>
</html>"""


if __name__ == "__main__":
    build()
