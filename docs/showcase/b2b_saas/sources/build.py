"""Render the synthetic PDF decks and annual accounts of the B2B SaaS showcase.

Each deck prints the figures of its answer-key pack in ``../packs``, so a PDF and its pack
cannot drift. The accounts add the statutory lines an auditor prints. The press, podcast and
forum sources are plain text files next to this script. Chrome prints the HTML to PDF, so the
showcase needs no PDF library.

Usage: uv run python docs/showcase/b2b_saas/sources/build.py
"""

import subprocess
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml

HERE = Path(__file__).parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SYNTHETIC = "Synthetic sample document. Invented company, invented figures."
DASH = "\u2013"  # an empty table cell
TIMES = "\u00d7"

type Pack = list[dict[str, object]]


@dataclass(frozen=True)
class Accounts:
    """Statutory figures in EUR thousand, (FY2024, FY2023)."""

    auditor: str
    legal_name: str
    net_sales: tuple[int, int]
    cost_of_sales: tuple[int, int]
    selling: tuple[int, int]
    admin: tuple[int, int]
    rnd: tuple[int, int]
    financial: tuple[int, int]
    tax: tuple[int, int]
    cash: tuple[int, int]
    receivables: tuple[int, int]
    deferred: tuple[int, int]
    equity: tuple[int, int]
    sales_split: dict[str, int]  # FY2024 note
    da: tuple[int, int]  # only the deck prints EBITDA, from these
    note_no: int


@dataclass(frozen=True)
class Company:
    key: str
    name: str
    city: str
    colour: str
    tagline: str
    headline: str  # cover line, "" for none
    arr_label: str
    arr_decimals: int
    summary: list[str]
    regions: list[tuple[str, str, int]]  # (table, row, EUR) beyond the pack rows
    product: list[str]
    gtm: list[str]
    team: list[str]
    accounts: Accounts
    retention_page: list[str] = field(default_factory=list)  # bullets when the pack has no NRR
    plan_page: list[str] = field(default_factory=list)  # bullets when the pack has no plan


def load_pack(key: str) -> Pack:
    rows: Pack = yaml.safe_load((HERE.parent / "packs" / f"{key}.yaml").read_text())["observations"]
    return rows


def m(value: Decimal, decimals: int = 2) -> str:
    return f"€{value / 1_000_000:.{decimals}f}m"


def k(value: Decimal | int) -> str:
    return f"{Decimal(value) / 1000:,.0f}"


def n(value: Decimal | int) -> str:
    return f"{value:,.0f}"


def pct(value: Decimal) -> str:
    return f"{value.normalize():f}%"


def paren(value: int) -> str:
    """Statutory style: a cost or a loss in brackets."""
    return f"({-value:,})" if value < 0 else f"{value:,}"


CSS = """
@page { size: 13.333in 7.5in; margin: 0 }
* { box-sizing: border-box }
body { margin: 0; font-family: Helvetica, Arial, sans-serif; color: #1d232b;
  font-variant-ligatures: none; font-feature-settings: "liga" 0 }
.slide { width: 13.333in; height: 7.5in; padding: 0.55in 0.7in; position: relative;
  page-break-after: always; overflow: hidden }
.slide h1 { font-size: 28pt; margin: 0 0 0.25in; color: var(--c) }
.slide h2 { font-size: 15pt; margin: 0 0 0.12in; color: #46505c; font-weight: normal }
.foot { position: absolute; bottom: 0.3in; left: 0.7in; right: 0.7in; font-size: 8pt;
  color: #8a939e; display: flex; justify-content: space-between }
.bar-top { position: absolute; top: 0; left: 0; right: 0; height: 0.12in; background: var(--c) }
ul { font-size: 15pt; line-height: 1.6; margin: 0; padding-left: 0.3in }
.tiles { display: grid; grid-template-columns: repeat(3, 3.7in); gap: 0.3in 0.25in }
.tile { border-left: 4px solid var(--c); padding: 0.05in 0.15in; background: #f4f6f8 }
.tile .l { font-size: 12pt; color: #46505c }
.tile .v { font-size: 26pt; font-weight: bold; margin: 0.04in 0 }
.tile .p { font-size: 10pt; color: #8a939e }
table { border-collapse: collapse; font-size: 13pt }
th, td { padding: 0.05in 0.18in; text-align: right; border-bottom: 1px solid #dde2e7 }
th:first-child, td:first-child { text-align: left; padding-left: 0 }
th { color: #46505c; font-weight: normal; border-bottom: 2px solid var(--c) }
tr.total td { font-weight: bold }
.chart { display: flex; align-items: flex-end; gap: 0.5in; height: 3.6in; margin-top: 0.1in }
.col { display: flex; flex-direction: column; align-items: flex-start; width: 1.5in }
.col .v { font-size: 16pt; font-weight: bold; margin-top: 0.06in }
.col .b { width: 1.5in; background: var(--c) }
.col .b.down { background: #c0504d }
.col .b.ghost { background: transparent }
.col .x { font-size: 11pt; color: #46505c; margin-top: 0.06in }
.side { position: absolute; right: 0.7in; top: 1.6in; width: 3.6in }
.note { font-size: 10pt; color: #6b7480; margin-top: 0.2in }
.cover { background: var(--c); color: white }
.cover h1 { color: white; font-size: 44pt; margin-top: 1.6in }
.cover .sub { font-size: 20pt }
.cover .hl { font-size: 24pt; margin-top: 0.4in; font-weight: bold }
.cover .foot { color: #e8ecf0 }
.a4 { width: 210mm; height: 297mm; padding: 25mm 22mm; position: relative;
  page-break-after: always; font-family: Georgia, serif; font-size: 10.5pt; line-height: 1.45 }
.a4 h1 { font-size: 18pt } .a4 h2 { font-size: 13pt; margin-top: 8mm }
.a4 table { font-size: 10.5pt; width: 100% }
.a4 th, .a4 td { padding: 1.2mm 2mm }
.a4 .foot { left: 22mm; right: 22mm; bottom: 12mm }
"""


def slide(c: Company, page: int, title: str, body: str, *, cls: str = "") -> str:
    return (
        f'<section class="slide {cls}"><div class="bar-top"></div><h1>{title}</h1>{body}'
        f'<div class="foot"><span>{c.name} · Investor presentation · Confidential</span>'
        f"<span>{SYNTHETIC}</span><span>{page}</span></div></section>"
    )


def tiles(items: list[tuple[str, str, str]]) -> str:
    cells = "".join(
        f'<div class="tile"><div class="l">{label}</div><div class="v">{value}</div>'
        f'<div class="p">{period}</div></div>'
        for label, value, period in items
    )
    return f'<div class="tiles">{cells}</div>'


def table(header: list[str], rows: list[list[str]], total: int | None = None) -> str:
    head = "".join(f"<th>{cell}</th>" for cell in header)
    body = "".join(
        f'<tr class="{"total" if i == total else ""}">'
        + "".join(f"<td>{cell}</td>" for cell in row)
        + "</tr>"
        for i, row in enumerate(rows)
    )
    return f"<table><tr>{head}</tr>{body}</table>"


def chart(bars: list[tuple[str, str, float, str]], gap: float = 0.5) -> str:
    """(value text, period text, height share 0..1, bar class)."""
    cols = "".join(
        f'<div class="col"><div class="b {kind}" style="height:{max(share, 0.02) * 2.8:.2f}in">'
        f'</div><div class="v">{value}</div><div class="x">{period}</div></div>'
        for value, period, share, kind in bars
    )
    return f'<div class="chart" style="gap:{gap}in">{cols}</div>'


def bar_chart(label: str, points: list[tuple[str, str, float]]) -> str:
    """Bars with the figures in a data table under them: (period, value text, height share)."""
    bars = "".join(
        f'<div class="b" style="width:1.3in;height:{share * 2.6:.2f}in"></div>'
        for _, _, share in points
    )
    cells = "".join(f'<td style="width:1.5in">{value}</td>' for _, value, _ in points)
    head = "".join(f"<th>{period}</th>" for period, _, _ in points)
    return (
        f'<div class="chart" style="gap:0.2in;margin-left:2.5in;height:2.7in">{bars}</div>'
        f'<table><tr><th style="width:2.3in"></th>{head}</tr>'
        f'<tr><td style="width:2.3in">{label}</td>{cells}</tr></table>'
    )


def bullets(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def deck(c: Company, pack: Pack) -> str:
    p = c.key
    v = {str(o["observation_id"]): Decimal(str(o["value"])) for o in pack}
    arr23, arr24, mrr23, mrr_q3, mrr24 = (v[f"{p}-0{i}"] for i in range(1, 6))
    rev23, rev24 = v[f"{p}-11"], v[f"{p}-12"]
    acc = c.accounts
    gp = [round((s - cs) / 10) * 10 for s, cs in zip(acc.net_sales, acc.cost_of_sales, strict=True)]
    ebit = [
        s - cs - sel - adm - r
        for s, cs, sel, adm, r in zip(
            acc.net_sales, acc.cost_of_sales, acc.selling, acc.admin, acc.rnd, strict=True
        )
    ]
    ebitda = [round((e + da) / 10) * 10 for e, da in zip(ebit, acc.da, strict=True)]
    ids = _ids(pack)
    pages = [
        f'<section class="slide cover" style="--c:{c.colour}"><h1>{c.name}</h1>'
        f'<div class="sub">{c.tagline}</div><div class="sub">Investor presentation · 1 March 2025'
        f'</div><div class="hl">{c.headline}</div><div class="foot"><span>Confidential</span>'
        f"<span>{SYNTHETIC}</span><span>1</span></div></section>",
        slide(c, 2, "Executive summary", bullets(c.summary)),
        slide(
            c,
            3,
            "Commercial momentum",
            tiles(
                [
                    ("Contracted ARR", m(v[ids["arr_contracted"]]), "at 31 Dec 2024"),
                    ("ACV bookings", m(v[ids["bookings_acv"]]), "FY2024"),
                    ("TCV bookings", m(v[ids["bookings_tcv"]]), "FY2024"),
                    ("Billings", m(v[ids["billings"]]), "FY2024"),
                    ("Deferred revenue", m(v[ids["deferred_revenue"]]), "at 31 Dec 2024"),
                    ("RPO", m(v[ids["backlog_rpo"]]), "at 31 Dec 2024"),
                ]
            ),
        ),
        slide(
            c,
            4,
            "ARR development",
            bar_chart(
                c.arr_label,
                [
                    ("Dec 2023", m(arr23, c.arr_decimals), float(arr23 / arr24)),
                    ("Dec 2024", m(arr24, c.arr_decimals), 1.0),
                ],
            )
            + f'<div class="side">{tiles([("Net new ARR", m(v[ids["net_new_arr"]]), "FY2024")])}'
            "</div>",
        ),
        slide(c, 5, "Revenue mix, FY2024", _revenue_mix(c, pack, v, ids, rev24)),
        slide(c, 6, "Customers and usage", _customers(c, v, ids)),
        slide(
            c,
            7,
            "Monthly recurring revenue",
            bar_chart(
                "MRR",
                [
                    ("Dec 2023", f"€{k(mrr23)}k", float(mrr23 / mrr24)),
                    ("Sep 2024", f"€{k(mrr_q3)}k", float(mrr_q3 / mrr24)),
                    ("Dec 2024", f"€{k(mrr24)}k", 1.0),
                ],
            ),
        ),
        slide(
            c,
            8,
            "P&amp;L summary",
            table(
                ["€k", "FY2023", "FY2024"],
                [
                    ["Total revenue", k(rev23), k(rev24)],
                    ["Gross profit", n(gp[1]), n(gp[0])],
                    [
                        "Gross margin %",
                        f"{gp[1] / float(rev23 / 1000):.1%}",
                        f"{gp[0] / float(rev24 / 1000):.1%}",
                    ],
                    ["EBITDA", paren(ebitda[1]), paren(ebitda[0])],
                ],
            )
            + '<div class="note">Management accounts. EBITDA excludes share-based payment.</div>',
        ),
        slide(
            c,
            9,
            "Revenue run-rate",
            tiles(
                [("Run-rate ARR", m(v[ids["arr_run_rate"]]), f"December 2024 revenue {TIMES} 12")]
            )
            + '<div class="note">Run-rate ARR annualises recognised recurring revenue of the '
            "month. It is not the same as contracted or live ARR.</div>",
        ),
        slide(
            c,
            10,
            "Churn",
            table(
                ["", "FY2024"],
                [
                    ["Annual logo churn*", f"{v[ids['churn_logo_annual']]:.1f}%"],
                    [
                        "Monthly gross revenue churn",
                        f"{v[ids['churn_revenue_gross_monthly']]:.2f}%",
                    ],
                ],
            )
            + f'<div class="note">* Avg. monthly logo churn: '
            f"{pct(v[ids['churn_logo_monthly']])} in FY2024.</div>",
        ),
        slide(c, 11, "Retention", _retention(c, v, ids)),
        slide(c, 12, "MRR bridge, Q4 2024", _bridge(v, p, mrr_q3, mrr24)),
        slide(c, 13, "Contracts and pricing", _contracts(v, ids)),
        slide(c, 14, "Product", bullets(c.product)),
        slide(c, 15, "FY2025 plan", _plan(c, v, ids, arr24)),
        slide(c, 16, "Go-to-market", bullets(c.gtm)),
        slide(c, 17, "Cohorts", _cohorts(v, ids)),
        slide(c, 18, "Team", bullets(c.team)),
        slide(
            c,
            19,
            "Cash",
            tiles(
                [
                    ("Gross burn", m(v[ids["burn_gross"]]), "December 2024, monthly"),
                    ("Net burn", f"€{k(v[ids['burn_net']])}k", "December 2024, monthly"),
                ]
            ),
        ),
    ]
    return f'<html><head><meta charset="utf-8"><style>{CSS}</style></head><body style="--c:{c.colour}">{"".join(pages)}</body></html>'  # noqa: E501


def _ids(pack: Pack) -> dict[str, str]:
    """Metric id to observation id of the first deck row at 2024-12-31, and "plan" to the
    FY2025 row if the pack has one.
    """
    ids: dict[str, str] = {}
    for o in pack:
        if "document_id" in o:
            continue
        if str(o["period_end"]) == "2024-12-31":
            ids.setdefault(str(o["metric_id"]), str(o["observation_id"]))
        elif str(o["period_end"]) == "2025-12-31":
            ids["plan"] = str(o["observation_id"])
    return ids


def _revenue_mix(
    c: Company, pack: Pack, v: dict[str, Decimal], ids: dict[str, str], rev24: Decimal
) -> str:
    mix = table(
        ["€k", "FY2024"],
        [
            ["Subscription revenue", k(v[ids["revenue_subscription"]])],
            ["Usage revenue", k(v[ids["revenue_usage"]])],
            ["Professional services revenue", k(v[ids["revenue_services"]])],
            ["Hardware revenue", k(v[ids["revenue_hardware"]])],
            ["Total revenue", k(rev24)],
            ["% recurring", pct(v[ids["recurring_revenue_share"]])],
        ],
        total=4,
    )
    splits: list[list[str]] = []
    for title, metric in (
        ("Revenue by region", "revenue_by_geography"),
        ("Revenue by segment", "revenue_by_segment"),
        ("Revenue by currency", "revenue_by_currency"),
    ):
        rows = [
            (str(o.get("region") or o.get("segment")), v[str(o["observation_id"])])
            for o in pack
            if o["metric_id"] == metric
        ]
        rows += [(row, Decimal(amount)) for name, row, amount in c.regions if name == title]
        splits += [[title, row, k(amount)] for row, amount in rows]
    return (
        f'<div style="display:flex;gap:0.6in"><div>{mix}</div>'
        f'<div style="font-size:12pt">{table(["Split", "", "€k"], splits)}</div></div>'
    )


def _customers(c: Company, v: dict[str, Decimal], ids: dict[str, str]) -> str:
    p = c.key
    vehicles = p == "halyard"
    licensed = "Licensed vehicles" if vehicles else "Licensed seats"
    active = "Vehicles tracked" if vehicles else "Active seats"
    utilisation = "Licence utilisation" if vehicles else "Seat utilisation"
    stock = table(
        ["", "31 Dec 2023", "31 Dec 2024"],
        [
            ["Paying customers", n(v[f"{p}-13"]), n(v[f"{p}-14"])],
            ["Active customers", DASH, n(v[ids["customers_active"]])],
            ["Logos", DASH, n(v[ids["logos"]])],
            ["Registered users", DASH, n(v[ids["users_registered"]])],
            [licensed, DASH, n(v[ids["seats_licensed"]])],
            [active, DASH, n(v[ids["seats_active"]])],
            [utilisation, DASH, pct(v[ids["seat_utilisation"]])],
            ["Enterprise share (ARR above €50k)", DASH, pct(v[ids["customers_enterprise_share"]])],
        ],
    )
    flow = table(
        ["", "FY2024"],
        [
            ["New customers", n(v[ids["customers_new"]])],
            ["Churned customers", n(v[ids["customers_churned"]])],
            ["ARPA (monthly, Dec 2024)", f"€{n(v[ids['arpu']])}"],
        ],
    )
    return f'<div style="display:flex;gap:0.7in"><div>{stock}</div><div>{flow}</div></div>'


def _retention(c: Company, v: dict[str, Decimal], ids: dict[str, str]) -> str:
    if "nrr" not in ids:
        return bullets(c.retention_page)
    order = ["nrr", "grr"] if c.key == "kestrel" else ["grr", "nrr"]
    names = {"nrr": "Net revenue retention", "grr": "Gross revenue retention"}
    rows = [[names[metric], pct(v[ids[metric]])] for metric in order]
    rows.append(["Renewal rate", pct(v[ids["renewal_rate"]])])
    return table(["", "FY2024"], rows) + (
        '<div class="note">Retention on the customer base at 1 January 2024.</div>'
    )


def _bridge(v: dict[str, Decimal], p: str, opening: Decimal, closing: Decimal) -> str:
    """Outflows print as amounts on red bars, as many decks show a waterfall."""
    steps = [
        ("New MRR", v[f"{p}-06"], ""),
        ("Expansion MRR", v[f"{p}-07"], ""),
        ("Reactivation MRR", v[f"{p}-08"], ""),
        ("Contraction MRR", v[f"{p}-09"], "down"),
        ("Churned MRR", v[f"{p}-10"], "down"),
    ]
    top = max(opening, closing) + v[f"{p}-06"] + v[f"{p}-07"]
    bars = [(k(opening), "MRR Sep 2024", float(opening / top), "")]
    bars += [(k(value), label, float(value / top) * 4, kind) for label, value, kind in steps]
    bars.append((k(closing), "MRR Dec 2024", float(closing / top), ""))
    return "<h2>€k, Q4 2024</h2>" + chart(bars, gap=0.12)


def _contracts(v: dict[str, Decimal], ids: dict[str, str]) -> str:
    rows = [
        ["Average contract term (months)", n(v[ids["contract_length_avg"]])],
        ["% on annual plans", pct(v[ids["contract_annual_share"]])],
        ["% billed upfront", pct(v[ids["payment_terms_upfront_share"]])],
        ["Average ACV", f"€{n(v[ids['acv_avg']])}"],
        ["ASP", f"€{n(v[ids['asp']])}"],
    ]
    concentration = [
        ("Top customer %", "revenue_concentration_top1"),
        ("Top 5 concentration", "revenue_concentration_top5"),
        ("Top 10 concentration", "revenue_concentration_top10"),
    ]
    rows += [[label, pct(v[ids[metric]])] for label, metric in concentration if metric in ids]
    return table(["", "FY2024"], rows)


def _plan(c: Company, v: dict[str, Decimal], ids: dict[str, str], arr24: Decimal) -> str:
    if "plan" not in ids:
        return bullets(c.plan_page)
    return (
        table(
            ["€m", "FY2024A", "FY2025P"],
            [["ARR", f"{arr24 / 1_000_000:.2f}", f"{v[ids['plan']] / 1_000_000:.2f}"]],
        )
        + '<div class="note">Plan approved by the board in January 2025.</div>'
    )


def _cohorts(v: dict[str, Decimal], ids: dict[str, str]) -> str:
    items = []
    if "nrr_cohort_12m" in ids:
        items.append(("M12 cohort NRR", pct(v[ids["nrr_cohort_12m"]]), "FY2024 cohorts"))
    items += [
        ("Cohort retention", pct(v[ids["cohort_retention_curve"]]), "logos, month 12, FY2024"),
        (
            "Expected customer lifetime (months)",
            n(v[ids["customer_lifetime_months"]]),
            "at 31 Dec 2024",
        ),
        (
            "Median customer tenure (months)",
            n(v[ids["customer_tenure_median"]]),
            "at 31 Dec 2024",
        ),
    ]
    return tiles(items)


def accounts(c: Company) -> str:
    a = c.accounts
    gp = [s - cs for s, cs in zip(a.net_sales, a.cost_of_sales, strict=True)]
    ebit = [g - s - ad - r for g, s, ad, r in zip(gp, a.selling, a.admin, a.rnd, strict=True)]
    ebt = [e + f for e, f in zip(ebit, a.financial, strict=True)]
    net = [e - t for e, t in zip(ebt, a.tax, strict=True)]

    def row(label: str, pair: tuple[int, int] | list[int], *, cost: bool = False) -> list[str]:
        sign = -1 if cost else 1
        return [label, paren(sign * pair[0]), paren(sign * pair[1])]

    def page(no: int, body: str) -> str:
        return (
            f'<section class="a4">{body}<div class="foot"><span>{a.legal_name} · '
            f"Annual financial statements 2024</span><span>{SYNTHETIC}</span>"
            f"<span>{no}</span></div></section>"
        )

    income = table(
        ["EUR thousand", "2024", "2023"],
        [
            row("Net sales", a.net_sales),
            row("Cost of sales", a.cost_of_sales, cost=True),
            row("Gross profit", gp),
            row("Selling expenses", a.selling, cost=True),
            row("Administrative expenses", a.admin, cost=True),
            row("Research and development expenses", a.rnd, cost=True),
            row("Operating result", ebit),
            row("Financial result", a.financial),
            row("Profit before tax", ebt),
            row("Income taxes", a.tax, cost=True),
            row("Net result for the year", net),
        ],
    )
    balance = table(
        ["EUR thousand", "31 Dec 2024", "31 Dec 2023"],
        [
            row("Trade receivables", a.receivables),
            row("Cash and cash equivalents", a.cash),
            row("Total equity", a.equity),
            row("Deferred income", a.deferred),
        ],
    )
    split = table(
        ["EUR thousand", "2024"],
        [[label, n(amount)] for label, amount in a.sales_split.items()]
        + [["Net sales", n(a.net_sales[0])]],
        total=len(a.sales_split),
    )
    pages = [
        page(
            1,
            f'<div style="margin-top:70mm"><h1>{a.legal_name}</h1><p style="font-size:14pt">'
            "Annual financial statements for the financial year<br>1 January to 31 December 2024"
            f"</p><p>{c.city}</p><p>Approved by the management board on 30 June 2025</p></div>",
        ),
        page(
            2,
            "<h1>Independent auditor's report</h1><p>To the shareholders of "
            f"{a.legal_name}</p><h2>Opinion</h2><p>We have audited the annual financial "
            "statements of the company, which comprise the balance sheet as at 31 December 2024, "
            "the income statement for the financial year from 1 January to 31 December 2024 and "
            "the notes. In our opinion, the annual financial statements give a true and fair view "
            "of the assets, liabilities and financial position of the company as at 31 December "
            "2024 and of its financial performance for the financial year then ended.</p>"
            "<h2>Basis for the opinion</h2><p>We conducted our audit in accordance with the "
            "applicable auditing standards. Our responsibilities are described further in this "
            "report. We are independent of the company and we have fulfilled our other ethical "
            "responsibilities. We believe that the audit evidence we have obtained is sufficient "
            f"and appropriate to provide a basis for our opinion.</p><p>{c.city}, 30 June 2025"
            f"</p><p>{a.auditor}</p>",
        ),
        page(3, f"<h1>Income statement</h1><p>For the financial year 2024</p>{income}"),
        page(4, f"<h1>Balance sheet (extract)</h1>{balance}"),
        page(
            5,
            "<h1>Notes</h1><h2>1. General</h2><p>The financial statements are prepared in euro. "
            "Amounts are in EUR thousand unless stated otherwise.</p><h2>2. Revenue recognition"
            "</h2><p>Subscription fees are recognised over the contract term. Services are "
            "recognised as delivered. Hardware is recognised on delivery.</p>"
            f"<h2>{a.note_no}. Net sales</h2><p>Net sales by category, financial year 2024:</p>"
            f"{split}",
        ),
    ]
    return f'<html><head><meta charset="utf-8"><style>{CSS}@page {{ size: A4; margin: 0 }}</style></head><body style="--c:#333">{"".join(pages)}</body></html>'  # noqa: E501


def render(html: str, pdf: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html, "utf-8")
        subprocess.run(  # noqa: S603 -- fixed binary, arguments built here
            [
                CHROME,
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
    print(f"wrote {pdf.relative_to(HERE)}")


# The statutory lines are chosen so that the deck P&L (rounded to EUR 10k) and the accounts
# agree, and every subtotal adds up. Only the planted issues of the packs may raise a question.
COMPANIES = [
    Company(
        key="kestrel",
        name="Kestrel Ledger",
        city="Munich",
        colour="#1f5f8b",
        tagline="Finance operations for the mid-market",
        headline="~€12m ARR at December 2024",
        arr_label="ARR (exit)",
        arr_decimals=2,
        summary=[
            "One platform for accounts payable, month-end close and spend control",
            "Built for mid-market finance teams of 5 to 50 people",
            "268 paying customers in DACH and Benelux at the end of 2024",
            "ARR up 47% in 2024, with efficient growth",
            "Raising a Series B to scale sales in Germany and enter the Nordics",
        ],
        regions=[
            ("Revenue by region", "Rest of Europe", 4_150_000),
            ("Revenue by segment", "Enterprise", 3_650_000),
            ("Revenue by currency", "Other currencies", 1_950_000),
        ],
        product=[
            "Invoice capture with line-level matching to purchase orders",
            "Close checklist with automatic reconciliation of bank and ledger",
            "Spend policies enforced at approval, not at audit",
            "Connectors to DATEV, SAP Business One, Microsoft Dynamics and Exact",
        ],
        gtm=[
            "Inside sales for companies below EUR 100m turnover",
            "Field sales and partners for larger accounts",
            "Implementation partners in Germany, Austria and the Netherlands",
        ],
        team=[
            "Founders from finance operations and from enterprise software",
            "Product and engineering in Munich and Lisbon",
            "Finance, legal and people functions in place for a Series B company",
        ],
        accounts=Accounts(
            auditor="Feldmann Ostrowski Wirtschaftsprüfung (invented firm)",
            legal_name="Kestrel Ledger GmbH",
            net_sales=(10_052, 6_703),
            cost_of_sales=(2_211, 1_610),
            selling=(5_120, 3_700),
            admin=(2_160, 1_690),
            rnd=(3_050, 2_240),
            financial=(-35, -20),
            tax=(12, 8),
            cash=(6_840, 9_950),
            receivables=(1_420, 980),
            deferred=(3_402, 2_310),
            equity=(5_210, 7_746),
            sales_split={"Subscription": 9_282, "Usage": 250, "Professional services": 520},
            da=(420, 310),
            note_no=3,
        ),
    ),
    Company(
        key="halyard",
        name="Halyard Fleet",
        city="Dublin",
        colour="#2e7d5b",
        tagline="Connected fleets, measured every second",
        headline="",
        arr_label="ARR",
        arr_decimals=2,
        summary=[
            "Telematics devices and a per-vehicle subscription for logistics and service fleets",
            "Recurring revenue of €18.9m in FY2024",
            "1,480 paying customers in Ireland, the UK and the Benelux",
            "Hardware sold at low margin to win multi-year software contracts",
            "Next step: insurance data products built on the driving data",
        ],
        regions=[
            ("Revenue by region", "Ireland and Benelux", 11_700_000),
            ("Revenue by segment", "Field service", 10_300_000),
            ("Revenue by currency", "EUR-billed", 11_900_000),
        ],
        product=[
            "Own-design tracker with a 5-year battery and a CAN-bus reader",
            "Driver scoring, route replay and fuel analytics",
            "Tachograph download and compliance reports for the UK and the EU",
            "Open API used by transport-management systems",
        ],
        gtm=[
            "Direct sales to fleets above 50 vehicles",
            "Dealer channel for small fleets",
            "Leasing partners bundle the device into vehicle leases",
        ],
        team=[
            "Founded by engineers from automotive electronics",
            "Hardware team in Cork, software team in Dublin and Manchester",
            "Installation network of certified partners in four countries",
        ],
        retention_page=[
            "Customers stay: most fleets sign 36-month contracts",
            "Account managers review usage with each fleet every quarter",
            "Upsell of fuel and driver modules is the main expansion lever",
        ],
        plan_page=[
            "Grow the UK direct sales team",
            "Launch the insurance data product with two pilot insurers",
            "Bring device gross margin to break-even",
        ],
        accounts=Accounts(
            auditor="Corrib &amp; Lane, Chartered Accountants (invented firm)",
            legal_name="Halyard Fleet Limited",
            net_sales=(21_480, 16_104),
            cost_of_sales=(8_160, 6_200),
            selling=(9_400, 7_600),
            admin=(4_300, 3_500),
            rnd=(5_050, 4_100),
            financial=(-110, -80),
            tax=(20, 15),
            cash=(11_200, 16_300),
            receivables=(3_900, 2_700),
            deferred=(4_096, 3_050),
            equity=(12_400, 17_960),
            sales_split={
                "Subscription": 16_392,
                "Usage": 300,
                "Services": 898,
                "Hardware": 3_890,
            },
            da=(1_150, 900),
            note_no=3,
        ),
    ),
    Company(
        key="pinewick",
        name="Pinewick Security",
        city="Berlin",
        colour="#6b3fa0",
        tagline="Identity threat detection for the enterprise",
        headline="€45m ARR at December 2024",
        arr_label="ARR (exit)",
        arr_decimals=2,
        summary=[
            "Detects attacks on identities across cloud, SaaS and on-premise directories",
            "610 paying customers, of which 46% are enterprise accounts",
            "Net revenue retention of 124% in FY2024",
            "Close to cash-flow break-even at the end of 2024",
            "Raising growth capital to expand in the US",
        ],
        regions=[
            ("Revenue by region", "Rest of world", 13_400_000),
            ("Revenue by segment", "Mid-market", 9_100_000),
            ("Revenue by currency", "Other currencies", 8_500_000),
        ],
        product=[
            "Agentless sensors for Active Directory, Entra ID and Okta",
            "Behaviour models trained per tenant",
            "Response playbooks that disable a session in seconds",
            "Certified for ISO 27001 and SOC 2 Type II",
        ],
        gtm=[
            "Enterprise field sales in DACH, the Nordics and the UK",
            "Managed security service providers resell to the mid-market",
            "Technology alliances with two of the large identity providers",
        ],
        team=[
            "Founders from a national computer emergency response team",
            "Research team publishes on identity attacks",
            "US office opened in Boston in 2024",
        ],
        accounts=Accounts(
            auditor="Ashgrove Audit Partners (invented firm)",
            legal_name="Pinewick Security GmbH",
            net_sales=(38_610, 26_004),
            cost_of_sales=(6_950, 4_990),
            selling=(17_800, 13_100),
            admin=(6_200, 4_700),
            rnd=(9_100, 6_900),
            financial=(-60, -50),
            tax=(45, 30),
            cash=(21_400, 23_100),
            receivables=(7_800, 5_600),
            deferred=(15_612, 10_900),
            equity=(18_300, 19_845),
            sales_split={"Subscription": 36_906, "Usage": 400, "Professional services": 1_304},
            da=(1_600, 1_250),
            note_no=4,
        ),
    ),
]


def main() -> None:
    for c in COMPANIES:
        render(deck(c, load_pack(c.key)), HERE / c.key / f"{c.key}-deck-2025.pdf")
        render(accounts(c), HERE / c.key / f"{c.key}-accounts-fy2024.pdf")


if __name__ == "__main__":
    main()
