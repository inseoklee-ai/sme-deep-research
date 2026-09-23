"""한국어 위키백과에서 딥리서처용 코퍼스를 모은다 — 주제: 중소기업 AI·디지털 전환.

시드 문서에서 2홉까지 넓혀 corpus.json 한 파일로 저장한다.
    {"docs": {제목: 본문}, "links": {제목: [docs 안의 다른 제목, ...]}}

실행: python scripts/archive/collect_corpus_v1_ko.py  (보관용 — v1, 한국어만)
"""
import hashlib
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

SEEDS = [
    "스마트팩토리", "디지털 트랜스포메이션", "제4차 산업혁명", "중소기업",
    "전사적 자원 관리", "사물인터넷", "인공지능", "기계 학습", "빅 데이터",
    "클라우드 컴퓨팅", "자동화", "정밀 농업", "로보틱 처리 자동화",
    "생성형 인공지능", "에지 컴퓨팅", "공급망 관리", "품질 관리", "디지털 트윈",
]

MAX_DOCS = 50          # 이만큼 모이면 멈춘다
MIN_CHARS = 3000       # 이보다 짧은 토막글은 저장하지 않는다
MIN_COCITE = 2         # 후보는 문서 몇 개 이상이 함께 가리켜야 하나
PREFILTER = 9000       # 위키 원문 바이트가 이보다 작으면 본문을 받지 않는다 (한글 3000자 ≈ 9000바이트)

# 주제와 상관없이 여러 시드가 가리키기만 하는 일반 문서 — 코퍼스를 흐리므로 뺀다
EXCLUDE = {
    "미국", "대한민국", "일본", "중국", "독일", "영국", "프랑스", "유럽", "유럽 연합",
    "영어", "한국어", "위키백과", "위키데이터", "국제 표준 도서 번호", "디지털 객체 식별자",
    "인터넷 아카이브", "구글 도서",
}

API = "https://ko.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "sme-deep-research/0.1 (educational corpus builder)"}  # 아스키만
OUT = Path(__file__).with_name("corpus_v1_ko.json")
CACHE = Path(__file__).resolve().parents[2] / "cache"
PAUSE = 1.0            # 호출 사이 쉬는 시간(초). 0.3초로는 429(Too Many Requests)가 났다

# 연도·날짜·목록·틀·분류 문서 제외
SKIP = re.compile(r"^(\d+년(대)?|\d+세기|\d+월 \d+일|기원전 .*)$|목록|^틀:|^분류:|동음이의")


def api(params: dict) -> dict:
    """호출 결과를 cache/ 에 남긴다 — 다시 돌려도 위키백과를 또 두드리지 않는다."""
    params = {**params, "format": "json", "formatversion": "2"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    CACHE.mkdir(exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    for 시도 in range(6):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
                d = json.load(r)
            f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            return d
        except urllib.error.HTTPError as e:
            if e.code != 429 or 시도 == 5:
                raise
            쉼 = int(e.headers.get("Retry-After") or 0) or 10 * (시도 + 1)
            print(f"    (429 — {쉼}초 쉬고 다시)", flush=True)
            time.sleep(쉼)


def chunks(xs: list, n: int = 50):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def query_all(params: dict) -> list[dict]:
    """continue 가 있으면 끝까지 이어 받아 응답 목록을 돌려준다."""
    out, cont = [], {}
    while True:
        d = api({**params, **cont})
        out.append(d)
        if "continue" not in d:
            return out
        cont = d["continue"]


def info(titles: list[str]) -> dict[str, tuple[str, int]]:
    """{요청한 제목: (실제 제목, 원문 바이트)}. 넘겨주기를 풀고, 없는 문서는 뺀다. 50건씩 묶는다."""
    out = {}
    for batch in chunks(sorted(set(titles))):
        d = api({"action": "query", "prop": "info", "titles": "|".join(batch), "redirects": 1})
        q = d.get("query", {})
        real = {p["title"]: p.get("length", 0) for p in q.get("pages", []) if not p.get("missing")}
        norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
        redir = {x["from"]: x["to"] for x in q.get("redirects", [])}
        for t in batch:
            r = redir.get(norm.get(t, t), norm.get(t, t))
            if r in real:
                out[t] = (r, real[r])
    return out


def links_of(titles: list[str]) -> dict[str, list[str]]:
    """{문서: [본문 링크(일반 문서) 원래 표기]}. 50건씩 묶어 받는다."""
    out = {t: set() for t in titles}
    for batch in chunks(titles):
        for d in query_all({"action": "query", "prop": "links", "titles": "|".join(batch),
                            "plnamespace": 0, "pllimit": "max"}):
            for p in d.get("query", {}).get("pages", []):
                out.setdefault(p["title"], set()).update(l["title"] for l in p.get("links", []))
    return {t: sorted(v) for t, v in out.items()}


def redirects_to(titles: list[str]) -> dict[str, str]:
    """{넘겨주기 제목: 실제 문서 제목} — 최종 links 를 docs 제목으로 맞출 때 쓴다."""
    out = {}
    for batch in chunks(titles):
        for d in query_all({"action": "query", "prop": "redirects", "titles": "|".join(batch),
                            "rdnamespace": 0, "rdlimit": "max"}):
            for p in d.get("query", {}).get("pages", []):
                for r in p.get("redirects", []):
                    out[r["title"]] = p["title"]
    return out


def extract_of(title: str) -> str:
    """평문 본문. extracts 는 한 번에 한 문서만 받을 수 있다."""
    d = api({"action": "query", "prop": "extracts", "explaintext": 1, "titles": title})
    p = d["query"]["pages"][0]
    return "" if p.get("missing") else p.get("extract", "")


def usable(title: str) -> bool:
    return not SKIP.search(title) and title not in EXCLUDE


def main():
    docs, dropped = {}, []

    def take(title: str, hop: str) -> bool:
        text = extract_of(title)
        if len(text) < MIN_CHARS:
            dropped.append((title, len(text), hop))
            return False
        docs[title] = text
        print(f"  [{hop}] {title}  {len(text):,}자", flush=True)
        return True

    def expand(sources: list[str], hop: str):
        """sources 가 함께 가리키는 문서를 많이 가리키는 순으로 채운다."""
        raw = links_of(sources)
        cocite = Counter(t for ls in raw.values() for t in set(ls) if usable(t))
        cand = [t for t, c in cocite.most_common() if c >= MIN_COCITE]
        meta = info(cand)
        seen = set(docs)
        for t in cand:
            if len(docs) >= MAX_DOCS:
                return
            if t not in meta:
                continue
            real, size = meta[t]
            if real in seen or not usable(real):
                continue
            seen.add(real)
            if size < PREFILTER:
                dropped.append((real, f"원문 {size:,}바이트", f"{hop}·{cocite[t]}"))
                continue
            take(real, f"{hop}·{cocite[t]}")

    print("■ 시드")
    seeds = info(SEEDS)
    for s in SEEDS:
        if s not in seeds:
            dropped.append((s, "문서 없음", "시드"))
            continue
        take(seeds[s][0], "시드")
    seed_titles = sorted({seeds[s][0] for s in seeds})   # 짧아서 뺀 시드의 링크도 1홉 후보로 쓴다

    print("■ 1홉 (시드 여러 개가 함께 가리키는 순)")
    expand(seed_titles, "1홉")
    if len(docs) < MAX_DOCS:
        print("■ 2홉 (모은 문서들이 함께 가리키는 순)")
        expand(sorted(docs), "2홉")

    # links 에는 docs 안에 실제로 있는 제목만 남긴다 (넘겨주기로 걸린 링크도 실제 제목으로 푼다)
    to_doc = {t: t for t in docs} | {r: t for r, t in redirects_to(sorted(docs)).items()}
    raw = links_of(sorted(docs))
    links = {t: sorted({to_doc[x] for x in raw.get(t, []) if x in to_doc} - {t}) for t in docs}
    OUT.write_text(json.dumps({"docs": docs, "links": links}, ensure_ascii=False, indent=1), encoding="utf-8")

    n_links = [len(v) for v in links.values()]
    total = sum(len(v) for v in docs.values())
    print("\n==== 결과 ====")
    print(f"문서 수            : {len(docs)}")
    print(f"총 글자 수         : {total:,}자  (대략 {total // 2:,} 토큰 · gpt-4o-mini 창 128,000)")
    print(f"내부 링크 총수     : {sum(n_links)}")
    print(f"문서당 링크 중앙값 : {statistics.median(n_links) if n_links else 0}")
    zero = [t for t, v in links.items() if not v]
    print(f"링크 0개 문서      : {len(zero)}건 {zero}")
    print(f"짧아서 뺀 문서     : {len(dropped)}건")
    for t, n, hop in dropped:
        print(f"   - [{hop}] {t} ({n:,}자)" if isinstance(n, int) else f"   - [{hop}] {t} ({n})")
    print(f"저장: {OUT}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
