"""
抓取證交所 T86「三大法人買賣超日報」，取出每檔股票的投信買賣超，
存成每日 JSON，並重新產生手機版網頁（docs/index.html）。

用法：
  python scripts/fetch_twse_trust.py              # 抓今天（台北時間）
  python scripts/fetch_twse_trust.py 2026-10-27   # 抓指定日期
"""

import datetime as dt
import html
import json
import pathlib
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "docs"
TAIPEI = ZoneInfo("Asia/Taipei")

T86_URL = "https://www.twse.com.tw/fund/T86?response=json&date={ymd}&selectType=ALLBUT0999"
HEADERS = {"User-Agent": "Mozilla/5.0 (tw-fund-radar)"}


def fetch_t86(day: dt.date) -> dict | None:
    """回傳證交所原始 JSON；非交易日或失敗回傳 None。"""
    url = T86_URL.format(ymd=day.strftime("%Y%m%d"))
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("stat") == "OK" and payload.get("data"):
                return payload
            return None  # 非交易日：stat 不是 OK
        except Exception as exc:  # 網路錯誤就重試
            print(f"[warn] 第 {attempt + 1} 次抓取失敗：{exc}", file=sys.stderr)
            time.sleep(5)
    return None


def to_int(text: str) -> int:
    text = text.replace(",", "").strip()
    try:
        return int(text)
    except ValueError:
        return 0


def parse_trust(payload: dict) -> list[dict]:
    """找出「投信買賣超股數」欄位，依欄位名稱定位，不依固定順序。"""
    fields = payload["fields"]
    code_idx = 0
    name_idx = 1
    trust_idx = next(i for i, f in enumerate(fields) if "投信買賣超" in f)

    rows = []
    for row in payload["data"]:
        shares = to_int(row[trust_idx])
        rows.append({
            "code": row[code_idx].strip(),
            "name": row[name_idx].strip(),
            "trust_net_lots": round(shares / 1000),  # 股數換算成張
        })
    rows.sort(key=lambda r: r["trust_net_lots"], reverse=True)
    return rows


def save_day(day: dt.date, rows: list[dict]) -> pathlib.Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"twse_trust_{day.isoformat()}.json"
    path.write_text(json.dumps({"date": day.isoformat(), "rows": rows},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_recent_days(limit: int = 5) -> list[dict]:
    files = sorted(DATA_DIR.glob("twse_trust_*.json"), reverse=True)[:limit]
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


def build_site(days: list[dict]) -> None:
    """產生單頁網站：最新一日買超／賣超前 20 名，加上近 5 日累計。"""
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    if not days:
        return

    latest = days[0]
    rows = latest["rows"]
    buys = [r for r in rows if r["trust_net_lots"] > 0][:20]
    sells = sorted([r for r in rows if r["trust_net_lots"] < 0],
                   key=lambda r: r["trust_net_lots"])[:20]

    # 近 N 日累計
    cumulative: dict[str, dict] = {}
    for day in days:
        for r in day["rows"]:
            c = cumulative.setdefault(r["code"], {"name": r["name"], "total": 0})
            c["total"] += r["trust_net_lots"]
    cum_buys = sorted([c | {"code": k} for k, c in cumulative.items() if c["total"] > 0],
                      key=lambda c: c["total"], reverse=True)[:20]

    def table(items: list[dict], key: str) -> str:
        if not items:
            return "<p>無資料</p>"
        body = "".join(
            f"<tr><td>{html.escape(i['code'])}</td>"
            f"<td>{html.escape(i['name'])}</td>"
            f"<td class='num'>{i[key]:,}</td></tr>"
            for i in items
        )
        return f"<table><tr><th>代號</th><th>名稱</th><th>張數</th></tr>{body}</table>"

    cum_items = [{"code": c["code"], "name": c["name"], "trust_net_lots": c["total"]}
                 for c in cum_buys]

    page = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>台股投信買賣超</title>
<style>
  body {{ font-family: -apple-system, "PingFang TC", "Noto Sans TC", sans-serif;
         margin: 0; padding: 12px; background: #fafafa; color: #222; }}
  h1 {{ font-size: 20px; margin: 8px 0; }}
  h2 {{ font-size: 16px; margin: 20px 0 6px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; font-size: 14px; }}
  th, td {{ padding: 6px 4px; border-bottom: 1px solid #eee; text-align: left; }}
  td.num {{ text-align: right; }}
  .buy {{ color: #c62828; }} .sell {{ color: #2e7d32; }}
  .note {{ font-size: 12px; color: #666; margin-top: 16px; line-height: 1.6; }}
</style>
</head>
<body>
<h1>台股投信買賣超</h1>
<p>資料日期：{latest['date']}（收盤後更新，單位：張）</p>

<h2 class="buy">投信買超前 20 名</h2>
{table(buys, 'trust_net_lots')}

<h2 class="sell">投信賣超前 20 名</h2>
{table(sells, 'trust_net_lots')}

<h2>近 {len(days)} 個交易日累計買超</h2>
{table(cum_items, 'trust_net_lots')}

<p class="note">
資料來源：臺灣證券交易所三大法人買賣超日報（T86）。<br>
本網站僅供研究與資訊整理，不構成任何投資建議。投資人應自行判斷風險。
</p>
</body>
</html>
"""
    (SITE_DIR / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    if len(sys.argv) > 1:
        day = dt.date.fromisoformat(sys.argv[1])
    else:
        day = dt.datetime.now(TAIPEI).date()

    payload = fetch_t86(day)
    if payload is None:
        print(f"{day} 無資料（可能是非交易日或尚未公布），略過。")
    else:
        rows = parse_trust(payload)
        path = save_day(day, rows)
        print(f"已儲存 {path}，共 {len(rows)} 檔。")

    build_site(load_recent_days())
    print("網站已更新：docs/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
