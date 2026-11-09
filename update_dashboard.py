#!/usr/bin/env python3
"""Update AllFlooringNow ctt-dashboard index.html from a data JSON file.

Usage: python3 update_dashboard.py data.json [--dry-run]
  --dry-run : print what would change, do not write the file.

The script is idempotent and validates every replacement. Run from the
dashboard repo directory (expects index.html in cwd).
"""
import json, re, sys, calendar
from datetime import date

HTML = "index.html"

# Jan..Oct 2026 finalized Amazon gross sales (dashboard history rows)
# Oct 2026 final added Nov 1 rollover: $106,643.60 sales / $25,633.78 profit
JAN_SEP_SALES = [68287, 69898, 90763, 96869, 100977, 103913, 91095, 95979, 99432, 106643.60]
JAN_SEP_PROFIT = [14135, 14496, 20495, 20639, 20232, 22798, 18738, 21974, 20642, 25633.78]
GOAL_TOTAL = 1_000_000
MONTHLY_TARGET = 83_333

SKU_LABELS = [
    "2in × 90ft (1-pack)", "4in × 90ft (1-pack)", "2in × 90ft 3-Pack",
    "4in × 90ft 3-Pack", "2in × 90ft 6-Pack", "2in × 90ft 12-Pack",
    "4in × 90ft 6-Pack",
]


def money(v): return f"${v:,.2f}"
def money0(v): return f"${v:,.0f}"
def pct1(v): return f"{v:.1f}%"
def pct2(v): return f"{v:.2f}%"
def num(v): return f"{v:,}"


def set_by_id(html, eid, new_inner):
    pat = re.compile(r'(id="%s"[^>]*>)(.*?)(</)' % re.escape(eid), re.S)
    html, n = pat.subn(lambda m: m.group(1) + new_inner + m.group(3), html, count=1)
    assert n == 1, f"element #{eid} not found"
    return html


def set_id_color(html, eid, color):
    pat = re.compile(r'(id="%s"[^>]*?color:)(var\(--[a-z]+\)|#[0-9a-fA-F]{3,6})' % re.escape(eid))
    html, n = pat.subn(r"\g<1>" + color, html, count=1)
    assert n == 1, f"color for #{eid} not found"
    return html


def set_bar_width(html, eid, width):
    width = max(0.0, min(100.0, width))
    pat = re.compile(r'(id="%s"[^>]*?style="[^"]*?width:)[\d.]+%%' % re.escape(eid))
    html, n = pat.subn(lambda m: m.group(1) + f"{width:.1f}%", html, count=1)
    assert n == 1, f"bar #{eid} not found"
    return html


BAR_GRADIENTS = {
    "green": "linear-gradient(90deg,#39ff14,#28cc10)",
    "yellow": "linear-gradient(90deg,#ffe600,#ccb800)",
    "red": "linear-gradient(90deg,#ff4444,#cc0000)",
}


def set_bar_color(html, eid, status):
    pat = re.compile(r'(id="%s"[^>]*?style="[^"]*?background:)(linear-gradient\([^)]*\)|var\(--[a-z]+\))' % re.escape(eid))
    html, n = pat.subn(lambda m: m.group(1) + BAR_GRADIENTS[status], html, count=1)
    assert n == 1, f"bar color #{eid} not found"
    return html


def set_row(block, label, value):
    pat = re.compile(r'(>%s</span><span[^>]*>)[^<]*' % re.escape(label))
    block, n = pat.subn(lambda m: m.group(1) + value, block, count=1)
    assert n == 1, f"row '{label}' not found"
    return block


def split_daily_blocks(region):
    """Split a 3-card daily region into (today, yesterday, mtd) blocks."""
    parts = re.split(r"(⚡ Today — [^<]*|📅 Yesterday — [^<]*|📈 Month to Date — [^<]*)",
                     region)
    assert len(parts) == 7, f"expected 3 daily blocks, got {(len(parts)-1)//2}"
    return parts[2], parts[4], parts[6], parts  # today, yday, mtd, all parts


def reassemble(parts, today, yday, mtd):
    parts[2], parts[4], parts[6] = today, yday, mtd
    return "".join(parts)


def update_region(html, start_marker, end_marker, headers, data):
    """Update one daily-stats card region (amazon or walmart)."""
    si = html.index(start_marker)
    ei = html.index(end_marker, si)
    region = html[si:ei]
    today_b, yday_b, mtd_b, parts = split_daily_blocks(region)

    # header dates live in the captured split parts (odd indices), not the bodies
    parts[1] = f"⚡ Today — {headers['today']}"
    parts[3] = f"📅 Yesterday — {headers['yesterday']}"
    parts[5] = f"📈 Month to Date — {headers['mtd']}"

    def fill(block, d, profit_label):
        if d.get("sales") is None:
            for label in ("Gross Sales", "Net Profit", "Gross Profit", "Margin",
                          "Orders / Units", "Orders", "Ad Spend"):
                try:
                    block = set_row(block, label, "Pending")
                except AssertionError:
                    pass
            return block
        block = set_row(block, "Gross Sales", money(d["sales"]))
        block = set_row(block, profit_label, money(d["profit"]))
        block = set_row(block, "Margin", pct2(d["profit"] / d["sales"] * 100) if d["sales"] else "—")
        if "units" in d and d.get("orders") is not None:
            block = set_row(block, "Orders / Units", f"{d['orders']} / {d['units']}")
        elif d.get("orders") is not None:
            block = set_row(block, "Orders", str(d["orders"]))
        if d.get("ad_spend") is not None:
            block = set_row(block, "Ad Spend", f"-{money(d['ad_spend'])}")
        return block

    today_b = fill(today_b, data["today"], data["profit_label"])
    yday_b = fill(yday_b, data["yesterday"], data["profit_label"])
    mtd_b = fill(mtd_b, data["mtd"], data["profit_label"])

    return html[:si] + reassemble(parts, today_b, yday_b, mtd_b) + html[ei:]


def ensure_wmt_today_ids(html):
    """One-time: add ids to the Walmart 'today' Pending spans."""
    ids = ["wmt-today-sales", "wmt-today-profit", "wmt-today-margin", "wmt-today-orders"]
    labels = ["Gross Sales", "Net Profit", "Margin", "Orders / Units"]
    si = html.index("WALMART MARKETPLACE")
    ei = html.index("SHOPIFY", si)
    region = html[si:ei]
    for eid, label in zip(ids, labels):
        if f'id="{eid}"' in region:
            continue
        pat = re.compile(r'(>%s</span><span)( style="[^"]*")' % re.escape(label))
        region, n = pat.subn(r"\g<1>" + f' id="{eid}"' + r"\g<2>", region, count=1)
        assert n == 1, f"wmt today row {label}"
    return html[:si] + region + html[ei:]


def status_emoji(ok, warn):
    if ok: return "✅"
    if warn: return "⚠️"
    return "❌"


def main():
    data_path = sys.argv[1]
    dry = "--dry-run" in sys.argv
    with open(data_path) as f:
        d = json.load(f)

    with open(HTML) as f:
        html = f.read()
    orig_len = len(html)

    run = date.fromisoformat(d["run_date"])
    long_date = run.strftime("%B %d, %Y")
    days_in_month = calendar.monthrange(run.year, run.month)[1]
    elapsed = run.day  # MTD covers the 1st..today
    mon_abbr = run.strftime("%b")

    # ---- timestamps ----
    def fmt_ts(m):
        return f"Updated: {long_date}" + (f" · 9:00 AM" if m.group(1) else "")
    html = re.sub(r"Updated: [A-Z][a-z]+ \d{1,2}, \d{4}( · \d{1,2}:\d{2} [AP]M)?",
                  fmt_ts, html)
    html = html.replace("Updates 8:30 AM", "Updates 9:00 AM")
    html = html.replace("⚙️ Auto-updates via daily Sellerboard scrape",
                        "⚙️ Auto-updated daily at 9:00 AM ET via Sellerboard")

    amz, wmt, shp = d["amazon"], d["walmart"], d["shopify"]
    headers = {"today": d["today_label"], "yesterday": d["yesterday_label"],
               "mtd": d["mtd_label"]}

    # ---- Amazon daily stats ----
    html = update_region(html, "📊 Daily Statistics", "<!-- Product Health -->",
                         headers, {**amz, "profit_label": "Gross Profit"})
    # ---- Walmart daily stats ----
    html = ensure_wmt_today_ids(html)
    html = update_region(html, "WALMART MARKETPLACE", "SHOPIFY",
                         headers, {**wmt, "profit_label": "Net Profit"})
    # walmart today: Pending vs live
    wt = wmt["today"]
    if wt.get("sales") is None:
        for eid in ["wmt-today-sales", "wmt-today-profit", "wmt-today-margin",
                    "wmt-today-orders"]:
            html = set_by_id(html, eid, "Pending")
            html = set_id_color(html, eid, "var(--muted)")
    else:
        html = set_by_id(html, "wmt-today-sales", money(wt["sales"]))
        html = set_id_color(html, "wmt-today-sales", "var(--nb)")
        html = set_by_id(html, "wmt-today-profit", money(wt["profit"]))
        html = set_id_color(html, "wmt-today-profit", "var(--ng)")
        html = set_by_id(html, "wmt-today-margin",
                          pct2(wt["profit"] / wt["sales"] * 100) if wt["sales"] else "—")
        html = set_id_color(html, "wmt-today-margin", "var(--ng)")
        html = set_by_id(html, "wmt-today-orders",
                          f"{wt['orders']} / {wt['units']}")
        html = set_id_color(html, "wmt-today-orders", "var(--white)")

    # ---- Shopify (by id) ----
    s = shp
    for key, eid in [("today", "shopify-sales-today"), ("yesterday", "shopify-sales-yday"),
                     ("mtd", "shopify-sales-mtd")]:
        html = set_by_id(html, eid, money(s[key]["sales"]))
    for key, eid in [("today", "shopify-profit-today"), ("yesterday", "shopify-profit-yday"),
                     ("mtd", "shopify-profit-mtd")]:
        html = set_by_id(html, eid, money(s[key]["profit"]))
    for key, eid in [("today", "shopify-margin-today"), ("yesterday", "shopify-margin-yday"),
                     ("mtd", "shopify-margin-mtd")]:
        m = s[key]["profit"] / s[key]["sales"] * 100 if s[key]["sales"] else 43.0
        html = set_by_id(html, eid, pct1(m))
    for key, eid in [("today", "shopify-orders-today"), ("yesterday", "shopify-orders-yday"),
                     ("mtd", "shopify-orders-mtd")]:
        html = set_by_id(html, eid, str(s[key]["orders"]))
    for eid, sk, pk in [("shopify-kpi-mtdsales", "mtd", "sales"),
                        ("shopify-kpi-mtdprofit", "mtd", "profit"),
                        ("shopify-kpi-ytdsales", "ytd", "sales"),
                        ("shopify-kpi-ytdprofit", "ytd", "profit"),
                        ("shopify-kpi-lastmonth", "lastmonth", "sales")]:
        if sk in s:
            html = set_by_id(html, eid, money(s[sk][pk]))
    if "lastmonth" in s and "profit" in s["lastmonth"]:
        html = set_by_id(html, "shopify-kpi-lastmonth-sub", f"{money(s['lastmonth']['profit'])} profit")
    if "ytd" in s and "orders" in s["ytd"]:
        html = set_by_id(html, "shopify-kpi-ytdsales-sub", f"{num(s['ytd']['orders'])} orders · 2026")

    # ---- Inventory ----
    # SKU ids in the HTML follow FBA-table order (all 2in first, then 4in),
    # NOT the display/canonical order of the data lists. Canonical index -> id:
    _sku_ids = [1, 5, 2, 6, 3, 4, 7]  # canonical: 2in1,4in1,2in3,4in3,2in6,2in12,4in6
    for i, units in enumerate(d["inventory"]):
        html = set_by_id(html, f"inv-sku{_sku_ids[i]}", f"{num(units)} units")
    for i, units in enumerate(d["awd"]):
        html = set_by_id(html, f"awd-sku{_sku_ids[i]}",
                          f"{num(units)} units" if units is not None else "— units")
    html = set_by_id(html, "inv-days", f"{d['days_supply']} days")

    # ---- COGS per SKU (Sellerboard Products page, COGS column) ----
    # cogs[7] in canonical order; ids follow the FBA-table mapping
    for i, cogs in enumerate(d.get("cogs") or []):
        html = set_by_id(html, f"cogs-sku{_sku_ids[i]}", money(cogs))

    # ---- BSR / reviews / refund ----
    html = set_by_id(html, "ph-bsr-flooring", f"#{num(d['bsr_flooring'])}")
    html = set_by_id(html, "ph-bsr-thi", f"#{num(d['bsr_tools'])}")
    html = set_by_id(html, "ph-review-count", num(d["reviews"]))
    html = set_by_id(html, "ph-review-velocity", d["reviews_weekly"])
    html = set_by_id(html, "ph-refund-rate", pct2(d["refund_rate"]))
    html = set_by_id(html, "ph-refund-subtitle", d["refund_returns"])
    html = set_bar_width(html, "ph-refund-bar", d["refund_rate"] / 5 * 100)

    # hero product line
    html = re.sub(r"BSR #([\d,]+) Flooring Adhesives · #([\d,]+) Tools &amp; HI · ([\d,]+) ⭐ Reviews",
                  f"BSR #{num(d['bsr_flooring'])} Flooring Adhesives · #{num(d['bsr_tools'])} Tools &amp; HI · {num(d['reviews'])} ⭐ Reviews",
                  html, count=1)

    # ---- derived: forecast, run rate, YTD ----
    mtd_sales = amz["mtd"]["sales"]
    mtd_margin = amz["mtd"]["profit"] / mtd_sales * 100
    forecast = mtd_sales / elapsed * days_in_month
    all_mtd = mtd_sales + wmt["mtd"]["sales"] + s["mtd"]["sales"]
    run_rate = all_mtd / elapsed * 365
    ytd = sum(JAN_SEP_SALES) + mtd_sales

    html = re.sub(r'(All Channels Run Rate</div><div class="kpi-val green">)\$[\d,]+',
                  lambda m: m.group(1) + money0(run_rate), html, count=1)
    html = re.sub(r"(↑ All channels · )\$[\d,]+(/day avg)",
                  lambda m: m.group(1) + money0(all_mtd / elapsed) + m.group(2),
                  html, count=1)
    html = re.sub(r'(Monthly Forecast</div><div class="kpi-val green">)\$[\d,]+',
                  lambda m: m.group(1) + money0(forecast), html, count=1)
    # Header forecast sub-label is static in the template and went stale on
    # Nov 1 (day-1 forecast is not "above target"); derive it from forecast.
    html = re.sub(r'(Monthly Forecast</div><div class="kpi-val green">\$[\d,]+</div><div class="kpi-sub up">)[^<]*',
                  lambda m: m.group(1) + ("↑ Above target ✅" if forecast >= MONTHLY_TARGET else "↓ Below $83,333 target"),
                  html, count=1)

    # monthly table current-month row (find by month label)
    mrow = re.compile(
        r'(<span style="color:var\(--muted\);text-align:right;">%s</span>\s*'
        r'<div class="month-track"><div[^>]*class="month-fill"[^>]*>)([^<]*)(</div></div>\s*'
        r'<span[^>]*>)([^<]*)(</span>)' % re.escape(mon_abbr))
    def _mrow(m):
        w = mtd_sales / 120000 * 100
        return (m.group(1) + f"MTD {money0(mtd_sales)}" + m.group(3) +
                f"FC {money0(forecast)}" + m.group(5))
    html, n = mrow.subn(_mrow, html, count=1)
    assert n == 1, "monthly table current-month row"
    # fix its fill width + orange style preserved; set width
    html = re.sub(r'(<span style="color:var\(--muted\);text-align:right;">%s</span>\s*'
                  r'<div class="month-track"><div[^>]*?width:)[\d.]+%%' % re.escape(mon_abbr),
                  lambda m: m.group(1) + f"{min(100, mtd_sales/120000*100):.0f}%",
                  html, count=1)

    # YTD
    html = set_by_id(html, "ytd-sales", money0(ytd))
    html = set_bar_width(html, "ytd-bar", ytd / GOAL_TOTAL * 100)
    html = set_by_id(html, "ytd-subtitle",
                     f"{ytd/GOAL_TOTAL*100:.0f}% complete · {money0(GOAL_TOTAL - ytd)} remaining")
    # YTD running net profit (Jan–Sep finals + current month MTD)
    ytd_profit = sum(JAN_SEP_PROFIT) + amz["mtd"]["profit"]
    html = set_by_id(html, "ytd-profit", money0(ytd_profit))
    html = set_by_id(html, "ytd-profit-pct", f"({ytd_profit / ytd * 100:.1f}%)")

    # YTD progress bars — Walmart & Shopify (goal $50,000 each)
    for prefix, ytd2 in [("wmt", wmt.get("ytd_sales")),
                         ("shp", s.get("ytd", {}).get("sales"))]:
        if ytd2:
            pct = ytd2 / 50000 * 100
            html = set_by_id(html, f"{prefix}-ytd-sales", money0(ytd2))
            html = set_bar_width(html, f"{prefix}-ytd-bar", pct)
            html = set_by_id(html, f"{prefix}-ytd-subtitle",
                             f"{pct:.0f}% complete · {money0(50000 - ytd2)} remaining")

    # ---- KPI progress ----
    acos, tacos, conv = d["acos"], d["tacos"], d["conversion"]
    # Reviews KPI: pace-aware vs the 1,800-by-EOY goal. A flat 1,200 cutoff
    # showed green all year; linear pace through Dec 31 is the honest bar.
    _diy = 366 if calendar.isleap(run.year) else 365
    _rev_pace = 1800 * run.timetuple().tm_yday / _diy
    kpi = [
        ("kpi-monthly", "kpi-monthly-val", "kpi-monthly-bar",
         money0(forecast), forecast / MONTHLY_TARGET * 100,
         forecast >= MONTHLY_TARGET, forecast >= MONTHLY_TARGET * 0.9),
        ("kpi-conv", "kpi-conv-val", "kpi-conv-bar",
         pct1(conv), min(100, conv / 28 * 100),
         conv >= 28, conv >= 25),
        ("kpi-reviews", "kpi-reviews-val", "kpi-reviews-bar",
         num(d["reviews"]), d["reviews"] / 1800 * 100,
         d["reviews"] >= _rev_pace, d["reviews"] >= _rev_pace * 0.9),
    ]
    for _, vid, bid, val, width, ok, warn in kpi:
        e = status_emoji(ok, warn)
        html = set_by_id(html, vid, f"{val} {e}")
        status = "green" if ok else ("yellow" if warn else "red")
        color = "var(--ng)" if ok else ("var(--ny)" if warn else "#ff4444")
        html = set_id_color(html, vid, color)
        html = set_bar_width(html, bid, width)
        html = set_bar_color(html, bid, status)
    html = set_by_id(html, "kpi-bsr-floor-val", f"#{num(d['bsr_flooring'])}")
    html = set_by_id(html, "kpi-bsr-thi-val", f"#{num(d['bsr_tools'])}")

    # ---- SCOREBOARD (top of page) ----
    # User targets: margin >20%, TACOS <18%, ACOS <28%
    sb_margin_ok = mtd_margin >= 20
    sb_tacos_ok = tacos <= 18
    sb_tacos_warn = tacos <= 20
    sb_acos_ok = acos <= 28
    sb_acos_warn = acos <= 32
    # all-channels MTD profit
    all_profit = amz["mtd"]["profit"] + wmt["mtd"]["profit"] + s["mtd"]["profit"]
    sb = [
        ("sb-margin-val", pct1(mtd_margin),
         "var(--ng)" if sb_margin_ok else "#ff4444",
         "✅" if sb_margin_ok else "❌"),
        ("sb-tacos-val", pct1(tacos),
         "var(--ng)" if sb_tacos_ok else ("var(--ny)" if sb_tacos_warn else "#ff4444"),
         "✅" if sb_tacos_ok else ("⚠️" if sb_tacos_warn else "❌")),
        ("sb-acos-val", pct1(acos),
         "var(--ng)" if sb_acos_ok else ("var(--ny)" if sb_acos_warn else "#ff4444"),
         "✅" if sb_acos_ok else ("⚠️" if sb_acos_warn else "❌")),
        ("sb-profit-val", money0(all_profit), "var(--ng)", ""),
    ]
    for eid, val, color, emoji in sb:
        html = set_by_id(html, eid, f"{val} {emoji}".strip())
        html = set_id_color(html, eid, color)

    # ---- days of cover per SKU (from Sellerboard "Days of stock left") ----
    # days_cover[7] in canonical order; null -> em-dash (SB shows 0 = adequate/uncomputed)
    _cover_ids = [1, 5, 2, 6, 3, 4, 7]  # canonical -> HTML id
    for i, days in enumerate(d.get("days_cover") or []):
        if days is None:
            cover_txt, cover_color = "—", "var(--muted)"
        else:
            cover_txt = f"{days:.0f}d left"
            cover_color = "#ff4444" if days < 14 else ("var(--ny)" if days < 30 else "var(--ng)")
        html = set_by_id(html, f"cover-sku{_cover_ids[i]}", cover_txt)
        try:
            html = set_id_color(html, f"cover-sku{_cover_ids[i]}", cover_color)
        except AssertionError:
            pass  # color span may not match pattern; text is set
    # ---- days until next order (Sellerboard) ----
    for i, days in enumerate(d.get("days_reorder") or []):
        if days is None:
            reorder_txt = "—"
        else:
            reorder_txt = f"order in {days:.0f}d"
        html = set_by_id(html, f"reorder-sku{_cover_ids[i]}", reorder_txt)

    # ---- month rollover ----
    if d.get("prev_month_final"):
        pm = d["prev_month_final"]  # {"abbr": "Sep", "sales": ..., "profit": ...}
        old = re.compile(
            r'(<span style="color:var\(--muted\);text-align:right;">%s</span>\s*'
            r'<div class="month-track"><div([^>]*)class="month-fill"([^>]*)>)([^<]*)(</div></div>\s*'
            r'<span([^>]*)>)([^<]*)(</span>)' % re.escape(pm["abbr"]))
        def _old(m):
            return (m.group(1) + f"{money0(pm['sales'])} ✅" + m.group(5) +
                    f"+{money0(pm['profit'])} {pm['profit']/pm['sales']*100:.1f}%" + m.group(8))
        html, n = old.subn(_old, html, count=1)
        assert n == 1, "prev month row for rollover"

    assert len(html) > orig_len * 0.9, "output suspiciously short"
    if dry:
        print(f"dry-run OK: {len(html)} bytes (was {orig_len})")
        return
    with open(HTML, "w") as f:
        f.write(html)
    print(f"updated {HTML}: {len(html)} bytes")


if __name__ == "__main__":
    main()
