from __future__ import annotations

import csv
import html
import io
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

from .db import connect

CSS = """
:root{color-scheme:light;--ink:#17212b;--muted:#637080;--paper:#f5f2e9;--line:#d6d0c2;--accent:#155c55}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 Georgia,serif}
header{background:#132b2a;color:#fff;padding:1rem 3vw;display:flex;gap:2rem;align-items:baseline}header a{color:#d9eee7}
main{padding:2rem 3vw;max-width:1500px;margin:auto}h1{font-size:1.7rem}.meta,.muted{color:var(--muted);font-family:system-ui,sans-serif}
form{display:flex;gap:.7rem;flex-wrap:wrap;margin:1rem 0}input,select,button{font:inherit;padding:.45rem;border:1px solid var(--line);background:white}
table{width:100%;border-collapse:collapse;background:#fff}th,td{text-align:left;padding:.6rem;border-bottom:1px solid var(--line);vertical-align:top}th{font-family:system-ui,sans-serif;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}
.money{font-variant-numeric:tabular-nums;white-space:nowrap}.tag{font:12px system-ui,sans-serif;padding:.15rem .35rem;border:1px solid var(--line)}a{color:var(--accent)}
@media(max-width:800px){table{display:block;overflow-x:auto}main{padding:1rem}header{padding:1rem}}
"""


def _layout(title: str, body: str) -> bytes:
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><header><strong>Insider Transactions</strong>"
            "<a href='/'>Feed</a><a href='/coverage'>Coverage</a><a href='/api/transactions'>API</a></header>"
            f"<main>{body}</main></body></html>").encode("utf-8")


def _rows(connection, query: dict[str, list[str]]) -> list[dict[str, object]]:
    clauses, params = [], []
    for key, column in (("country", "ce.jurisdiction_code"), ("action", "ce.action"), ("issuer", "ce.issuer_name")):
        if query.get(key, [""])[0]:
            clauses.append(f"{column} = ?" if key != "issuer" else f"{column} LIKE ?")
            value = query[key][0]
            params.append(value if key != "issuer" else f"%{value}%")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = ("SELECT ce.*, r.price_raw,r.price_amount_decimal,r.price_currency,r.quantity_decimal,r.quantity_unit,"
           "r.consideration_derived_decimal,r.consideration_currency FROM current_events ce "
           "LEFT JOIN reported_transaction_rows r ON r.transaction_group_id=ce.transaction_group_id AND r.selected_for_analytics=1" +
           where + " ORDER BY COALESCE(ce.published_at,ce.published_date) DESC,ce.event_id,r.occurrence_ordinal")
    return [dict(row) for row in connection.execute(sql, params)]


def _csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in {"=", "+", "-", "@"} else text


def _display_date(value: object) -> str:
    if not value:
        return "unknown"
    text = str(value)
    if len(text) == 10:
        try:
            return datetime.strptime(text, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            return text
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y %H:%M %z")
    except ValueError:
        return text


def application(database: Path):
    def app(environ, start_response):
        token = os.environ.get("INSIDER_TRACKER_TOKEN")
        if token and environ.get("HTTP_AUTHORIZATION") != f"Bearer {token}":
            start_response("401 Unauthorized", [("Content-Type", "text/plain"), ("WWW-Authenticate", "Bearer")])
            return [b"authentication required"]
        path = environ.get("PATH_INFO", "/")
        query = parse_qs(environ.get("QUERY_STRING", ""))
        connection = connect(database, readonly=True)
        try:
            if path == "/":
                rows = _rows(connection, query)
                cells = []
                for row in rows:
                    published = _display_date(row["published_at"] or row["published_date"])
                    party = row["party_name"] or "Anonymous disclosed role"
                    value = row["consideration_derived_decimal"] or "not reported"
                    cells.append("<tr>" + "".join([
                        f"<td>{html.escape(str(published))}<br><span class='muted'>trade {_display_date(row['trade_date'])}</span></td>",
                        f"<td><a href='/disclosure/{row['event_id']}'>{html.escape(str(row['issuer_name'] or 'Unresolved issuer'))}</a></td>",
                        f"<td>{html.escape(str(party))}<br><span class='tag'>{html.escape(str(row['party_type'] or 'unknown'))}</span></td>",
                        f"<td>{html.escape(str(row['action']))}<br><span class='muted'>{html.escape(str(row['mechanism']))}</span></td>",
                        f"<td class='money'>{html.escape(str(row['quantity_decimal'] or 'unknown'))} {html.escape(str(row['quantity_unit'] or ''))}</td>",
                        f"<td class='money'>{html.escape(str(row['price_raw'] or 'not reported'))}</td>",
                        f"<td class='money'>{html.escape(str(value))} {html.escape(str(row['consideration_currency'] or ''))}</td>",
                        f"<td>{html.escape(str(row['source_id']))}<br><span class='tag'>{'own-money eligible' if row['eligible_own_money_signal'] else 'excluded/uncertain'}</span></td>",
                    ]) + "</tr>")
                body = "<h1>Transaction feed</h1><p class='meta'>Ordered by first source publication evidence, not trade date.</p>"
                body += "<form><input name='issuer' placeholder='Issuer' value='{}'><select name='country'><option value=''>All countries</option>{}</select><select name='action'><option value=''>All actions</option><option>acquisition</option><option>disposal</option><option>grant</option><option>exercise</option></select><button>Filter</button><a href='/export.csv'>CSV export</a></form>".format(
                    html.escape(query.get("issuer", [""])[0]), "".join(f"<option>{code}</option>" for code in ("AT","BE","CH","DE","DK","ES","FI","FR","GB","GR","IE","IT","NL","NO","PL","PT","SE")))
                body += "<table><thead><tr><th>Published / traded</th><th>Issuer</th><th>Party</th><th>Action</th><th>Quantity</th><th>Reported price</th><th>Derived value</th><th>Source / quality</th></tr></thead><tbody>" + "".join(cells) + "</tbody></table>"
                start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
                return [_layout("Transaction feed", body)]
            if path == "/coverage":
                rows = connection.execute("SELECT j.name,s.*,(SELECT MAX(observed_at) FROM source_health_snapshots h WHERE h.source_id=s.source_id) checked FROM sources s JOIN jurisdictions j ON j.code=s.jurisdiction_code ORDER BY j.name").fetchall()
                body = "<h1>Coverage and operations</h1><p class='meta'>Status is evidence based. Registry-only sources are not live ingestion coverage.</p><table><tr><th>Country</th><th>Source</th><th>Status</th><th>Last verified</th><th>Last pipeline check</th><th>Rights</th></tr>" + "".join(
                    f"<tr><td>{html.escape(row['name'])}</td><td><a href='{html.escape(row['public_url'])}'>{html.escape(row['source_id'])}</a></td><td>{html.escape(row['status'])}</td><td>{html.escape(str(row['last_verified_at'] or 'unknown'))}</td><td>{html.escape(str(row['checked'] or 'not checked'))}</td><td>{html.escape(row['rights_status'])}</td></tr>" for row in rows) + "</table>"
                start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
                return [_layout("Coverage", body)]
            if path.startswith("/disclosure/"):
                event_id = path.rsplit("/", 1)[-1]
                event = connection.execute("SELECT * FROM current_events WHERE event_id=?", (event_id,)).fetchone()
                if not event:
                    start_response("404 Not Found", [("Content-Type", "text/plain")]); return [b"not found"]
                rows = connection.execute("SELECT r.* FROM reported_transaction_rows r WHERE transaction_group_id=? ORDER BY occurrence_ordinal", (event["transaction_group_id"],)).fetchall()
                pubs = connection.execute("SELECT sr.canonical_url,sr.published_at,sr.published_date FROM event_versions ev JOIN filing_publications fp ON fp.filing_version_id=ev.filing_version_id JOIN source_records sr ON sr.id=fp.source_record_id WHERE ev.economic_event_id=? ORDER BY COALESCE(sr.published_at,sr.published_date)", (event_id,)).fetchall()
                body = f"<h1>{html.escape(str(event['issuer_name']))}</h1><p>{html.escape(str(event['action']))} by {html.escape(str(event['party_name'] or 'anonymous disclosed role'))}; trade date {html.escape(str(event['trade_date'] or 'unknown'))}.</p><h2>Reported rows</h2><pre>{html.escape(json.dumps([dict(row) for row in rows], indent=2))}</pre><h2>Evidence</h2>" + "".join(f"<p><a href='{html.escape(row['canonical_url'])}'>{html.escape(row['canonical_url'])}</a> {html.escape(str(row['published_at'] or row['published_date']))}</p>" for row in pubs)
                start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")]); return [_layout("Disclosure", body)]
            if path == "/favicon.ico":
                start_response("204 No Content", []); return [b""]
            if path in {"/api/transactions", "/export.csv"}:
                rows = _rows(connection, query)
                if path.endswith(".csv"):
                    output = io.StringIO(newline=""); fields = list(rows[0]) if rows else ["event_id"]
                    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader(); writer.writerows({k: _csv_safe(v) for k, v in row.items()} for row in rows)
                    start_response("200 OK", [("Content-Type", "text/csv; charset=utf-8"), ("Content-Disposition", "attachment; filename=transactions.csv")]); return [output.getvalue().encode("utf-8")]
                payload = json.dumps({"data": rows, "count": len(rows), "decimals": "JSON strings", "sort": "publication_desc,event_id,row_ordinal"}, separators=(",", ":")).encode("utf-8")
                start_response("200 OK", [("Content-Type", "application/json")]); return [payload]
            start_response("404 Not Found", [("Content-Type", "text/plain")]); return [b"not found"]
        finally:
            connection.close()
    return app


def serve(database: Path, host: str, port: int) -> None:
    with make_server(host, port, application(database)) as server:
        print(f"Serving private pilot on http://{host}:{port}")
        server.serve_forever()
