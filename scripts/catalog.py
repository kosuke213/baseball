"""Validate, inspect links, and publish the stage-1 source inventory.

Only documentation/portal metadata is requested. This is not a data downloader.
Run from any directory: python scripts/catalog.py validate|check-links|build.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data_sources"
DOCS = ROOT / "docs" / "data-sources"
STATES = {"documentation_reviewed", "portal_candidate"}
KINDS = {"dataset", "portal", "research_index", "reference"}
RIGHTS = {"documented", "needs_review", "mixed", "restricted"}
LABELS = {"documentation_reviewed": "資料確認済み", "portal_candidate": "一次資料未確認"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def validate(catalog):
    rows = catalog["sources"]
    ids, urls = set(), set()
    categories = set(catalog["categories"])
    for s in rows:
        assert s["id"] not in ids, f"Duplicate id: {s['id']}"
        ids.add(s["id"])
        assert s["entry_url"] not in urls, f"Duplicate entry URL: {s['entry_url']}"
        urls.add(s["entry_url"])
        assert s["category"] in categories
        assert s["kind"] in KINDS and s["review_status"] in STATES
        assert s["priority"] in ("A", "B", "C")
        assert s["rights"]["status"] in RIGHTS
        assert s["sample_status"] == "not_collected_stage1"
        assert s["name"] and s["provider_group"] and s["description"] and s["coverage"]["notes"]
        assert s["acquisition"]["method"] and s["next_action"] and s["limitations"]
        if s["rights"]["status"] == "documented":
            assert s["rights"]["evidence_url"] and s["rights"]["data_license"] != "unknown"
        if s["review_status"] == "documentation_reviewed":
            assert s["evidence"], f"Missing reviewed documentation: {s['id']}"
        for url in [s["entry_url"], *s["documentation_urls"], *s.get('access_urls',[]), *[e["url"] for e in s["evidence"]]]:
            assert urlsplit(url).scheme == "https" and urlsplit(url).hostname
            assert not urlsplit(url).username and not urlsplit(url).password
    for tool in catalog["tools"]:
        assert tool["id"] not in ids
        ids.add(tool["id"])
        assert tool["role"] and tool["data_rights_note"]
    return rows


class Title(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "title": self.inside = True

    def handle_endtag(self, tag):
        if tag == "title": self.inside = False

    def handle_data(self, data):
        if self.inside: self.parts.append(data)


def check_links(catalog, refresh=False, retry_statuses=(), retry_urls=()):
    urls = set()
    encodings = {}
    for s in catalog["sources"]:
        urls.update([s["entry_url"], *s["documentation_urls"], *s.get('access_urls',[]), *[e["url"] for e in s["evidence"]]])
        if s.get('encoding_hint'):
            encodings[s['entry_url']] = s['encoding_hint']
    for t in catalog["tools"]:
        urls.update([t["url"], *t.get("documentation_urls", [])])
    # Per-host serialization + a small interval avoid a burst to one provider.
    locks = defaultdict(threading.Lock)
    last = defaultdict(float)
    rate_limited_hosts = set()

    def one(url):
        host = urlsplit(url).hostname
        with locks[host]:
            delay = 0.25 - (time.monotonic()-last[host])
            if delay > 0: time.sleep(delay)
            method = 'HEAD' if urlsplit(url).path.lower().endswith('.pdf') else 'GET'
            result = {"url": url, "checked_at": datetime.now(timezone.utc).isoformat(),
                      "method": method, "max_response_bytes": 0 if method=='HEAD' else 131072}
            if host in rate_limited_hosts:
                result.update({"status": "skipped_after_rate_limit", "http_status": None})
                return result
            request = Request(quote(url, safe=":/?&=#%+@,;"), method=method, headers={"User-Agent": "BaseballSimulationLab-SourceInventory/0.1 (documentation check)"})
            try:
                with urlopen(request, timeout=15) as response:
                    body = b'' if method=='HEAD' else response.read(131073)
                    prefix = body[:131072]
                    result.update({"status": "reachable", "http_status": response.status,
                                   "final_url": response.url, "content_type": response.headers.get("Content-Type"),
                                   "bytes_read": len(body), "truncated": len(body)>131072,
                                   "observed_body_sha256": hashlib.sha256(prefix).hexdigest()})
                    if "html" in (result["content_type"] or ""):
                        parser = Title()
                        meta = re.search(br'charset\s*=\s*["\x27]?([\w-]+)',prefix[:4096],re.I)
                        encoding = encodings.get(url) or (meta.group(1).decode('ascii') if meta else response.headers.get_content_charset() or 'utf-8')
                        try:
                            decoded = prefix.decode(encoding, errors='replace')
                        except LookupError:
                            decoded = prefix.decode('utf-8', errors='replace')
                        result['detected_encoding'] = encoding
                        parser.feed(decoded)
                        result["page_title"] = " ".join("".join(parser.parts).split())[:240]
            except HTTPError as error:
                result.update({"http_status": error.code,
                               "status": "rate_limited" if error.code == 429 else "http_error"})
                result["retry_after"] = error.headers.get("Retry-After")
                if error.code == 429:
                    rate_limited_hosts.add(host)
            except (URLError, TimeoutError, OSError) as error:
                message = str(error)
                # Do not persist proxy URLs, credentials, or arbitrary exception strings.
                result.update({"status": "proxy_blocked" if "Tunnel connection failed: 403" in message else "connection_error",
                               "http_status": None, "error_type": type(error).__name__})
            last[host] = time.monotonic()
            return result

    previous = read_json(DATA/"link_checks.json")["checks"] if (DATA/"link_checks.json").exists() and not refresh else []
    checks = [c for c in previous if c['url'] in urls and c['status'] not in retry_statuses and c['url'] not in retry_urls]
    remaining = sorted(urls-set(c['url'] for c in checks))
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(one, url) for url in remaining]
        for future in as_completed(futures):
            checks.append(future.result())
            write_json(DATA/"link_checks.json", {"scope":"documentation_and_portal_metadata_only", "checks":sorted(checks,key=lambda c:c['url'])})
    checks.sort(key=lambda c:c['url'])
    print(json.dumps(Counter(c["status"] for c in checks), ensure_ascii=False))


def access(s, checks):
    return checks.get(s["entry_url"], {}).get("status", "not_checked")


def escape(value):
    return str(value).replace("|", "／").replace("\n", " ")


def build(catalog):
    rows = validate(catalog)
    checks = {c["url"]: c for c in read_json(DATA/"link_checks.json")["checks"]} if (DATA/"link_checks.json").exists() else {}
    DATA.mkdir(exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    csv_rows = []
    for s in rows:
        csv_rows.append({"ID": s["id"], "名称": s["name"], "分類": catalog["categories"][s["category"]],
                         "提供元グループ": s["provider_group"], "種類": s["kind"],
                         "対象リーグ": " / ".join(s["leagues"]), "内容": s["description"],
                         "収録範囲": s["coverage"]["notes"], "取得方法": s["acquisition"]["method"],
                         "料金・認証": s["acquisition"]["access_notes"], "想定形式": " / ".join(s["formats"]),
                         "入口URL": s["entry_url"], "資料確認": LABELS[s["review_status"]],
                         "入口接続結果": access(s, checks), "データ利用条件": s["rights"]["data_license"],
                         "本文確認HTTP": s.get('portal_review',{}).get('status','未実施・別資料参照'),
                         "条件確認状況": s["rights"]["status"], "条件に関する注意": s["rights"]["notes"],
                         "次段階の調査優先度": s["priority"], "結合候補キー": " / ".join(s["join_keys"]),
                         "注意点": " / ".join(s["limitations"]), "次に確認すること": s["next_action"],
                         "本体サンプル": s["sample_status"]})
    with (DATA/"sources.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]),lineterminator='\n')
        writer.writeheader()
        writer.writerows(csv_rows)
    # This generated database contains only inventory metadata, never player data.
    db = DATA/"catalog.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE IF EXISTS sources")
        conn.execute("DROP TABLE IF EXISTS link_checks")
        conn.execute("CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, provider_group TEXT NOT NULL, priority TEXT NOT NULL, review_status TEXT NOT NULL, entry_access TEXT NOT NULL, metadata_json TEXT NOT NULL)")
        conn.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)", [(s["id"],s["name"],s["category"],s["provider_group"],s["priority"],s["review_status"],access(s,checks),json.dumps(s,ensure_ascii=False)) for s in rows])
        conn.execute("CREATE TABLE link_checks (url TEXT PRIMARY KEY, status TEXT NOT NULL, metadata_json TEXT NOT NULL)")
        conn.executemany("INSERT INTO link_checks VALUES (?,?,?)",[(u,c["status"],json.dumps(c,ensure_ascii=False)) for u,c in checks.items()])
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == len(rows)
    summary = {"catalog_entries": len(rows), "provider_groups": len({s['provider_group'] for s in rows}),
               "categories": dict(Counter(catalog['categories'][s['category']] for s in rows)),
               "kinds": dict(Counter(s['kind'] for s in rows)),
               "review_status": dict(Counter(s['review_status'] for s in rows)),
               "entry_access": dict(Counter(access(s, checks) for s in rows)),
               "portal_review_http_status": dict(Counter(str(s['portal_review'].get('status')) for s in rows if s.get('portal_review'))),
               "priority": dict(Counter(s['priority'] for s in rows)),
               "rights_status": dict(Counter(s['rights']['status'] for s in rows)),
               "supporting_tools": len(catalog['tools']), "sample_datasets_collected": 0,
               "link_checks": len(checks), "link_check_status": dict(Counter(c['status'] for c in checks.values()))}
    write_json(DATA/"summary.json",summary)
    table = ["# データ・情報源の収集先台帳", "", f"調査日: {catalog['review_date']}。候補 **{len(rows)}件**、提供元グループ **{summary['provider_groups']}**、補助ツール **{len(catalog['tools'])}件**。", "",
             f"説明資料・公開ページを確認: **{summary['review_status'].get('documentation_reviewed',0)}件**。十分な資料確認が残る候補: **{summary['review_status'].get('portal_candidate',0)}件**。統計レコードのサンプルセットは未作成です。", "",
             "件数はデータセット・入口・参考資料を含みます。同じ提供元の別データは同じグループで識別します。候補数は取得済みデータ数や独立した提供企業数ではありません。", "",
             "「資料確認済み」は説明資料の確認を意味します。HTTP 200は入口ページへの接続確認です。どちらもデータ取得・欠損検査・利用許可の完了を意味しません。優先度A/B/Cは次の調査順で、収集許可ではありません。本体サンプル取得は第2段階です。", "",
             "[調査方法・注意点](methodology.md) / [重点候補と発見事項](findings.md) / [検証記録](validation.md) / [Excel向けCSV](../../data_sources/sources.csv) / [機械可読JSON](../../data_sources/catalog.json) / [接続結果](../../data_sources/link_checks.json)", "",
             "## 分類別", "", "| 分類 | 件数 |", "|---|---:|"]
    for category, title in catalog['categories'].items():
        subset=[s for s in rows if s['category']==category]
        table.append(f"| [{title}]({category}.md) | {len(subset)} |")
        lines=[f"# {title}", "", "[台帳トップへ](README.md)", "", "| ID | 候補 | 優先度 | 資料 | 入口接続 |", "|---|---|---|---|---|"]
        for s in subset:
            lines.append(f"| [{s['id']}](#{s['id'].lower()}) | {escape(s['name'])} | {s['priority']} | {LABELS[s['review_status']]} | {access(s,checks)} |")
        for s in subset:
            lines += ["", f"## {s['id']}", "", f"**{s['name']}** — {s['description']}", "",
                      f"- 提供元グループ: `{s['provider_group']}` / 種類: `{s['kind']}` / 対象: {'・'.join(s['leagues'])}",
                      f"- 入口: {s['entry_url']}", f"- 収録範囲: {s['coverage']['notes']}",
                      f"- 取得方法・形式: {s['acquisition']['method']} / {'・'.join(s['formats'])}",
                      f"- 料金・認証: {s['acquisition']['access_notes']}",
                      f"- 条件: {s['rights']['data_license']}（{s['rights']['status']}）。{s['rights']['notes']}",
                      f"- 状態: {LABELS[s['review_status']]} / 入口 {access(s,checks)} / 本体サンプル未取得",
                      f"- 結合キー候補: {'・'.join(s['join_keys']) or '未確認'}",
                      f"- 次の確認: {s['next_action']}",
                      "- 注意点: " + ' / '.join(s['limitations'])]
            for e in s['evidence']:
                lines.append(f"- 確認資料: [{escape(e['note'])}]({e['url']})")
            if s.get('portal_review'):
                lines.append(f"- 別途の本文確認: HTTP {s['portal_review'].get('status')}。軽量接続チェックと日時・取得方法が異なるため結果が異なる場合があります。")
            for url in s.get('access_urls',[]):
                lines.append(f"- 追加の取得入口・案内: {url}")
        (DOCS/(category+'.md')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
    table += ["", "## 補助ツール", "", "ライブラリは取得元データとは別に数えます。コードのOSSライセンスをデータの利用許可として扱いません。", "", "| ツール | 役割 | 注意点 |", "|---|---|---|"]
    for t in catalog['tools']:
        table.append(f"| [{escape(t['name'])}]({t['url']}) | {escape(t['role'])} | {escape(t['data_rights_note'])} |")
    table += ["", "## 再生成", "", "リポジトリ直下でPython 3.11以上を使用:", "", "```bash", "python scripts/catalog.py validate", "python scripts/catalog.py build", "# 未確認URLだけを確認", "python scripts/catalog.py check-links", "# 接続許可の変更後などに、すべてを明示的に再調査する場合", "python scripts/catalog.py check-links --refresh", "python scripts/catalog.py build", "```", "", "buildはCSV・閲覧用Markdown・台帳用SQLiteを再生成します。catalog.jsonが編集元です。既存の試合DBには触れません。check-linksは各URLを1回確認し、429の後は同じホストへの残りの要求を止めます。"]
    (DOCS/'README.md').write_text('\n'.join(table)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['validate','check-links','build'])
    parser.add_argument('--refresh',action='store_true',help='既存の接続結果を再利用せず、明示的に再確認')
    parser.add_argument('--retry-status',action='append',default=[],help='接続設定変更後など、指定した状態だけを再確認')
    parser.add_argument('--retry-url',action='append',default=[],help='修正・診断後、台帳内の指定URLだけを再確認')
    args=parser.parse_args()
    catalog=read_json(DATA/'catalog.json')
    validate(catalog)
    if args.command=='check-links': check_links(catalog,args.refresh,args.retry_status,args.retry_url)
    elif args.command=='build': build(catalog)
    else: print(f"Valid: {len(catalog['sources'])} sources; {len(catalog['tools'])} tools")


if __name__=='__main__':
    main()
