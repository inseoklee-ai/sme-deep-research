"""위키백과(한국어 + 영어)에서 딥리서처용 코퍼스를 모은다 — 주제: 중소기업 AI·디지털 전환.

한국어 위키만으로는 도메인 핵심 문서(예지 정비·MES·디지털 트윈·공급망 관리·품질 관리 …)가
토막글이거나 아예 없어서(v1: collect_corpus_v1_ko.py), 현장 주제는 영어 위키에서 받는다.

저장 형식은 수업과 같다.
    {"docs": {제목: 본문}, "links": {제목: [docs 안의 다른 제목, ...]}, "lang": {제목: "ko"|"en"}}
- 언어가 다른 문서끼리도 링크를 잇는다 — 한국어 문서가 가리킨 「디지털 트윈」이 코퍼스에
  「Digital twin」으로 들어와 있으면, 위키 언어 간 연결(langlinks)로 풀어서 잇는다

실행: python scripts/collect_corpus.py
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

# 한국 맥락이 필요하거나 한국어 문서가 충분히 긴 주제
KO_SEEDS = [
    "중소기업", "스마트팩토리", "전사적 자원 관리", "사물인터넷", "빅 데이터",
    "클라우드 컴퓨팅", "자동화", "생성형 인공지능", "에지 컴퓨팅", "인공지능", "기계 학습",
    "로봇공학",   # 1홉 동점 경계에서 빠졌다 들어왔다 하던 것을 시드로 고정 (사용자 결정)
]
# 한국어 위키에 없거나 토막글인 현장 주제
EN_SEEDS = [
    # 중소기업 · 전환 일반
    "Small and medium enterprises", "Digital transformation", "Fourth Industrial Revolution",
    "Artificial intelligence in industry",
    # 제조 현장
    "Smart manufacturing", "Industrial internet of things", "Manufacturing execution system",
    "Predictive maintenance", "Condition monitoring", "Digital twin", "Machine vision", "Cobot",
    # 품질 · 생산성
    "Quality management", "Statistical process control", "Lean manufacturing",
    "Total productive maintenance", "Overall equipment effectiveness",
    # 사무 · 공급망 · 물류 (양계장·계란유통 트럭 운행 실증과 이어지는 곳)
    "Robotic process automation", "Supply chain management", "Demand forecasting",
    "Warehouse management system", "Fleet management", "Telematics", "Precision agriculture",
    # 도입 장벽 — 기술이 아니라 사람과 조직
    "Diffusion of innovations", "Technology acceptance model", "Change management",
]

MAX_DOCS = 45          # 이만큼 모이면 멈춘다 — 50으로 두면 넓은 일반 문서(경제학·기술 …)가 빈자리를 채운다
MIN_CHARS = 3000       # 이보다 짧은 토막글은 저장하지 않는다
MAX_CHARS = 60000      # 이보다 긴 문서는 여기서 자른다 — 조사관 read_one 의 입력 상한과 같다
MIN_COCITE = 3         # 확장 후보는 시드 몇 개 이상이 함께 가리켜야 하나
PREFILTER = {"ko": 9000, "en": 12000}   # 위키 원문 바이트가 이보다 작으면 본문을 받지 않는다

# 여러 시드가 가리키기만 하는 일반 문서 — 코퍼스를 흐리므로 뺀다 (v1 에서 AI 철학으로 흘렀던 교훈)
EXCLUDE = {
    "미국", "대한민국", "일본", "중국", "독일", "영국", "프랑스", "유럽", "유럽 연합", "영어", "한국어",
    "위키백과", "위키데이터", "위키미디어 공용", "웨이백 머신", "ArXiv", "국제 표준 도서 번호",
    "디지털 객체 식별자", "수학", "컴퓨터 과학", "통계학",
    "United States", "China", "Germany", "Japan", "United Kingdom", "India", "European Union",
    "Wayback Machine", "ArXiv", "ISBN (identifier)", "Doi (identifier)", "ISSN (identifier)",
    "S2CID (identifier)", "PMID (identifier)", "Bibcode (identifier)", "JSTOR (identifier)",
    "OCLC (identifier)", "Internet", "Computer", "Mathematics", "Statistics", "Computer science",
    "Engineering", "Software", "Data", "Wikipedia", "Wikidata",
    # v2 첫 실행에서 들어왔다가 뺀 것 — 참고문헌 식별자이거나 주제보다 너무 넓다
    "Handle System", "PubMed Central", "Technological singularity", "Green Revolution",
    "History of technology", "Industrial Revolution", "Electrical engineering", "Economics",
    "Technology", "Technological revolution",
}

API = {"ko": "https://ko.wikipedia.org/w/api.php", "en": "https://en.wikipedia.org/w/api.php"}
HEADERS = {"User-Agent": "sme-deep-research/0.1 (educational corpus builder)"}  # 아스키만
OUT = Path(__file__).resolve().parents[1] / "data" / "corpus.json"
CACHE = Path(__file__).resolve().parents[1] / "cache"
PAUSE = 1.0            # 호출 사이 쉬는 시간(초). 0.3초로는 429(Too Many Requests)가 났다

# 연도·날짜·목록·틀·분류 문서 제외
SKIP = re.compile(r"^(\d+년(대)?|\d+세기|\d+월 \d+일|기원전 .*|\d{3,4}s?)$|목록|^틀:|^분류:|동음이의"
                  r"|^List of|^Outline of|^Timeline of|^Index of|disambiguation", re.I)
# 본문 끝의 참고 자료 절 — 근거로 쓸 내용이 없고 제목 나열뿐이라 잘라낸다
TAIL = re.compile(r"\n==+\s*(같이 보기|각주|외부 링크|참고 문헌|참고 자료|출처|더 읽을거리|"
                  r"See also|References|External links|Further reading|Notes|Bibliography|Sources)\s*==+.*",
                  re.S)


def api(lang: str, params: dict) -> dict:
    """호출 결과를 cache/ 에 남긴다 — 다시 돌려도 위키백과를 또 두드리지 않는다."""
    params = {**params, "format": "json", "formatversion": "2"}
    url = f"{API[lang]}?{urllib.parse.urlencode(params)}"
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


def query_all(lang: str, params: dict) -> list[dict]:
    """continue 가 있으면 끝까지 이어 받아 응답 목록을 돌려준다."""
    out, cont = [], {}
    while True:
        d = api(lang, {**params, **cont})
        out.append(d)
        if "continue" not in d:
            return out
        cont = d["continue"]


def info(lang: str, titles: list[str]) -> dict[str, tuple[str, int]]:
    """{요청한 제목: (실제 제목, 원문 바이트)}. 넘겨주기를 풀고, 없는 문서는 뺀다. 50건씩 묶는다."""
    out = {}
    for batch in chunks(sorted(set(titles))):
        q = api(lang, {"action": "query", "prop": "info", "titles": "|".join(batch), "redirects": 1}).get("query", {})
        real = {p["title"]: p.get("length", 0) for p in q.get("pages", []) if not p.get("missing")}
        norm = {x["from"]: x["to"] for x in q.get("normalized", [])}
        redir = {x["from"]: x["to"] for x in q.get("redirects", [])}
        for t in batch:
            r = redir.get(norm.get(t, t), norm.get(t, t))
            if r in real:
                out[t] = (r, real[r])
    return out


def links_of(lang: str, titles: list[str]) -> dict[str, list[str]]:
    """{문서: [본문 링크(일반 문서) 원래 표기]}. 50건씩 묶어 받는다."""
    out = {t: set() for t in titles}
    for batch in chunks(titles):
        for d in query_all(lang, {"action": "query", "prop": "links", "titles": "|".join(batch),
                                  "plnamespace": 0, "pllimit": "max"}):
            for p in d.get("query", {}).get("pages", []):
                out.setdefault(p["title"], set()).update(l["title"] for l in p.get("links", []))
    return {t: sorted(v) for t, v in out.items()}


def redirects_to(lang: str, titles: list[str]) -> dict[str, str]:
    """{넘겨주기 제목: 실제 문서 제목} — 최종 links 를 docs 제목으로 맞출 때 쓴다."""
    out = {}
    for batch in chunks(titles):
        for d in query_all(lang, {"action": "query", "prop": "redirects", "titles": "|".join(batch),
                                  "rdnamespace": 0, "rdlimit": "max"}):
            for p in d.get("query", {}).get("pages", []):
                for r in p.get("redirects", []):
                    out[r["title"]] = p["title"]
    return out


def other_lang(lang: str, titles: list[str]) -> dict[str, str]:
    """{이 언어 제목: 다른 언어 제목} — 한↔영 같은 주제를 알아본다."""
    to = "en" if lang == "ko" else "ko"
    out = {}
    for batch in chunks(titles):
        for d in query_all(lang, {"action": "query", "prop": "langlinks", "titles": "|".join(batch),
                                  "lllang": to, "lllimit": "max"}):
            for p in d.get("query", {}).get("pages", []):
                for l in p.get("langlinks", []):
                    out[p["title"]] = l["title"]
    return out


def extract_of(lang: str, title: str) -> str:
    """평문 본문. extracts 는 한 번에 한 문서만 받을 수 있다."""
    d = api(lang, {"action": "query", "prop": "extracts", "explaintext": 1, "titles": title})
    p = d["query"]["pages"][0]
    return "" if p.get("missing") else p.get("extract", "")


def usable(title: str) -> bool:
    return not SKIP.search(title) and title not in EXCLUDE


def main():
    docs, lang_of, dropped, cut = {}, {}, [], []

    def take(lang: str, title: str, hop: str) -> bool:
        text = TAIL.sub("", extract_of(lang, title)).strip()
        if len(text) < MIN_CHARS:
            dropped.append((title, f"{len(text):,}자", hop))
            return False
        if len(text) > MAX_CHARS:
            cut.append((title, len(text)))
            text = text[:MAX_CHARS].rsplit("\n", 1)[0]
        docs[title], lang_of[title] = text, lang
        print(f"  [{hop}·{lang}] {title}  {len(text):,}자", flush=True)
        return True

    print("■ 시드")
    seed_titles = {"ko": [], "en": []}
    for lang, seeds in (("ko", KO_SEEDS), ("en", EN_SEEDS)):
        meta = info(lang, seeds)
        for s in seeds:
            if s not in meta:
                dropped.append((s, "문서 없음", f"시드·{lang}"))
                continue
            seed_titles[lang].append(meta[s][0])
            take(lang, meta[s][0], "시드")

    # 같은 주제가 다른 언어로 이미 들어와 있으면 확장 때 또 넣지 않는다
    twin = {t for lang in ("ko", "en") for t in other_lang(lang, [d for d in docs if lang_of[d] == lang]).values()}

    print("■ 1홉 (시드 여러 개가 함께 가리키는 순 — 두 언어 후보를 한 줄로 세운다)")
    cand = []
    for lang in ("ko", "en"):
        raw = links_of(lang, seed_titles[lang])
        cocite = Counter(t for ls in raw.values() for t in set(ls) if usable(t))
        top = [t for t, c in cocite.most_common() if c >= MIN_COCITE]
        meta = info(lang, top)
        cand += [(cocite[t], lang, *meta[t]) for t in top if t in meta]
    seen = set(docs) | twin
    # 동점은 제목순 — 집합 순회 순서에 맡기면 실행마다 어느 문서가 45건 안에 드는지가 바뀔 수 있다
    for c, lang, real, size in sorted(cand, key=lambda x: (-x[0], x[1], x[2])):
        if len(docs) >= MAX_DOCS:
            break
        if real in seen or not usable(real):
            continue
        seen.add(real)
        if size < PREFILTER[lang]:
            dropped.append((real, f"원문 {size:,}바이트", f"1홉·{c}·{lang}"))
            continue
        take(lang, real, f"1홉·{c}")

    # links — 같은 언어는 넘겨주기를 풀고, 다른 언어는 langlinks 로 풀어 docs 제목에 맞춘다
    to_doc = {t: t for t in docs}
    for lang in ("ko", "en"):
        mine = sorted(d for d in docs if lang_of[d] == lang)
        to_doc |= {r: t for r, t in redirects_to(lang, mine).items()}
        for t, other in other_lang(lang, mine).items():
            to_doc.setdefault(other, t)       # 다른 언어 쪽 제목으로 가리켜도 이 문서에 닿는다
    raw = {}
    for lang in ("ko", "en"):
        raw |= links_of(lang, sorted(d for d in docs if lang_of[d] == lang))
    links = {t: {to_doc[x] for x in raw.get(t, []) if x in to_doc} - {t} for t in docs}
    # 같은 주제의 한↔영 문서(예: 중소기업 ↔ Small and medium enterprises)는 서로를 가리키게 한다
    for lang in ("ko", "en"):
        for t, other in other_lang(lang, sorted(d for d in docs if lang_of[d] == lang)).items():
            if other in docs:
                links[t].add(other)
                links[other].add(t)
    links = {t: sorted(v) for t, v in links.items()}
    docs = dict(sorted(docs.items()))
    lang_of = dict(sorted(lang_of.items()))
    links = dict(sorted(links.items()))
    OUT.write_text(json.dumps({"docs": docs, "links": links, "lang": lang_of}, ensure_ascii=False, indent=1),
                   encoding="utf-8")

    n_links = [len(v) for v in links.values()]
    total = sum(len(v) for v in docs.values())
    zero = [t for t, v in links.items() if not v]
    inbound = Counter(x for v in links.values() for x in v)
    unreachable = [t for t in docs if not inbound[t]]
    print("\n==== 결과 ====")
    print(f"문서 수            : {len(docs)}  (ko {sum(v == 'ko' for v in lang_of.values())} · "
          f"en {sum(v == 'en' for v in lang_of.values())})")
    print(f"총 글자 수         : {total:,}자  (대략 {total // 3:,}~{total // 2:,} 토큰 · gpt-4o-mini 창 128,000)")
    print(f"내부 링크 총수     : {sum(n_links)}")
    print(f"문서당 링크 중앙값 : {statistics.median(n_links) if n_links else 0}")
    print(f"링크 0개 문서      : {len(zero)}건 {zero}")
    print(f"아무도 안 가리키는 문서(탐색으로 못 닿음): {len(unreachable)}건 {unreachable}")
    print(f"{MAX_CHARS:,}자에서 자른 문서 : {len(cut)}건 " + ", ".join(f"{t}({n:,}자)" for t, n in cut))
    print(f"뺀 문서            : {len(dropped)}건")
    for t, why, hop in dropped:
        print(f"   - [{hop}] {t} ({why})")
    print(f"저장: {OUT}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
