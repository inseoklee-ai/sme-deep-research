"""딥리서처 — 기획 → 배치 → 서브에이전트 → 점검 → 종합.

    python graph.py M2                    # questions.json 의 질문 ID 로 한 번 실행
    python graph.py "직접 쓴 질문"          # 아무 질문이나
    python graph.py M2 --set 재위임=false  # 스위치를 바꿔서 (역할·배정·구역·재위임, 절수·절예산 …)

실행 기록은 output/runs.jsonl 에 한 줄씩, 보고서는 output/reports/<run_id>.md 에 남는다.

설계 메모 (수업 코드에서 바꾼 것)
- 설정은 전역 변수가 아니라 State 안에 싣는다. 노드는 s["설정"] 만 본다 — 스위치를 껐는데
  코드 경로가 그대로인 사고를 막고, 한 프로세스에서 설정을 바꿔 가며 돌려도 섞이지 않는다.
- LLM 호출 기록(누가·무엇에·몇 자)을 State 의 calls 에 리듀서로 쌓는다 — 격리를 숫자로 보이는
  재료이고, 조사관 넷이 동시에 써도 안전하다.
- 코디네이터가 절마다 예산을 나눈다. 합계는 절수×절예산을 넘지 못한다(대조군과 같은 총 예산).
- 배정한 시작 문서가 목록에 없으면 아무 문서로 바꾸지 않고 '자율'로 둔 뒤 교정 기록을 남긴다.
- 재위임 원고는 근거가 줄지 않을 때만 채택한다 (원고_정책 = "근거비교").
"""
from __future__ import annotations

import argparse
import json
import operator
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
CORPUS = json.loads((ROOT / "data" / "corpus.json").read_text(encoding="utf-8"))
DOCS: dict[str, str] = CORPUS["docs"]
LINKS: dict[str, list[str]] = CORPUS["links"]
QUESTIONS = {q["id"]: q for q in json.loads((ROOT / "data" / "questions.json").read_text(encoding="utf-8"))["questions"]}
ROSTER: dict[str, str] = CFG["역할_명단"]
OUT = ROOT / "output"

KEYS_ENV = os.getenv("KEYS_ENV", r"C:\Users\lis29\projects\keys.env")   # 키는 저장소 밖에 둔다


# ── 공통 도구 ─────────────────────────────────────────────────────────────────

class Research(TypedDict):
    question: str
    설정:     dict                                # 이번 실행의 설정 (config.json + 덮어쓴 값)
    plan:     dict                                # ① 목차 · 역할 · 시작 문서 · 예산 · 배치 · 바퀴
    sections: Annotated[list, operator.add]       # 서브에이전트가 올린 원고 — 재위임본까지 전부 쌓인다
    visited:  Annotated[list, operator.add]       # (절 번호, 문서) — 누가 무엇을 읽었나
    calls:    Annotated[list, operator.add]       # LLM 호출 기록 — 격리율의 재료
    report:   str                                 # ④ 완성된 보고서
    log:      Annotated[list, operator.add]
    task:     dict                                # Send 로 서브에이전트 한 명에게만 가는 지시
    prior:    dict                                # 재위임일 때 지난 바퀴의 원고


_llm = None


def llm():
    """키가 필요한 순간에만 만든다 — 지표만 다시 잴 때는 키 없이 import 되게."""
    global _llm
    if _llm is None:
        try:
            from dotenv import load_dotenv
            load_dotenv(KEYS_ENV)
            load_dotenv(ROOT / ".env")
        except ImportError:
            pass
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(f"OPENAI_API_KEY 가 없습니다 — {KEYS_ENV} 또는 .env 에 넣어 주세요.")
        from langchain_openai import ChatOpenAI
        _llm = ChatOpenAI(model=CFG["모델"], temperature=0, timeout=90, max_retries=0)
    return _llm


일시적오류 = ("RateLimit", "APIConnection", "Timeout", "InternalServer")


def ask(system: str, user: str, 누가: str, 용도: str, cap: int | None = None) -> tuple[str, dict]:
    """LLM 한 번 부르고 (답, 호출 기록) 을 돌려준다. 입력은 cap 자에서 자른다(창을 넘지 않게)."""
    cap = cap or CFG["읽기_입력상한"]
    body = user[:cap]
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": body}]
    t0 = time.time()
    for 시도 in range(4):
        try:
            res = llm().invoke(msgs)
            break
        except Exception as e:                    # 잠깐 막힌 것만 다시 — 설정 오류는 바로 드러낸다
            if 시도 == 3 or not any(k in type(e).__name__ for k in 일시적오류):
                raise
            time.sleep(2 ** 시도)
    usage = getattr(res, "usage_metadata", None) or {}
    rec = {"누가": 누가, "용도": 용도, "입력자수": len(body), "지시자수": len(system),
           "잘림": len(user) > cap, "입력토큰": usage.get("input_tokens", 0),
           "출력토큰": usage.get("output_tokens", 0), "초": round(time.time() - t0, 2)}
    if 용도 in ("기획", "고르기"):
        rec["답"] = res.content[:300]            # 나중에 '왜 그렇게 골랐나'를 의심할 수 있게
    return res.content, rec


def jload(raw: str, default):
    """모델이 JSON 앞뒤에 군더더기를 붙여도 {...} / [...] 만 오려 읽는다. 깨지면 default."""
    try:
        m = re.search(r"\[.*\]" if isinstance(default, list) else r"\{.*\}", raw, re.S)
        return json.loads(m.group(0))
    except Exception:
        return default


def 문장들(글: str) -> list[str]:
    """문장 분리 규칙은 여기 하나뿐이다 — metrics.py 도 이 함수를 쓴다(규칙이 갈라지면 지표가 흔들린다)."""
    return [x.strip() for x in re.split(r"(?<=[.!?。])\s+|\n", 글) if len(x.strip()) > 15]


def 인용들(글: str) -> list[str]:
    return re.findall(r"«([^»]+)»", 글)


def 인용형식교정(글: str) -> tuple[str, int]:
    """모델이 «제목» 대신 [제목] 으로 쓴 인용을 바로잡는다. 코퍼스에 있는 제목만, 고친 건수를 돌려준다.
    대조군(baseline.py)에도 똑같이 적용한다 — 한쪽만 고쳐 주면 비교가 기운다."""
    n = 0

    def fix(m):
        nonlocal n
        if m.group(1) in DOCS:
            n += 1
            return f"«{m.group(1)}»"
        return m.group(0)
    return re.sub(r"\[([^\[\]\n]{1,80})\]", fix, 글), n


def 근거문장수(sec: dict) -> int:
    """그 원고에서, 실제로 읽은 문서를 인용한 문장 수."""
    read = set(sec.get("읽은문서", []))
    return sum(1 for 문 in 문장들(sec.get("본문", "")) if any(c in read for c in 인용들(문)))


def 역할문장(t: dict) -> str:
    기본 = CFG["기본_역할"]
    return f"너는 {t['역할']}이다. {ROSTER.get(t['역할'], ROSTER[기본])}."


# ── ① 기획 ────────────────────────────────────────────────────────────────────

def cards() -> str:
    """코디네이터가 보는 것은 문서 전체가 아니라 제목 + 앞부분 카드뿐이다."""
    n = CFG["카드_글자수"]
    return "\n".join(f"- {t}: {re.sub(r'\s+', ' ', v[:n])}" for t, v in DOCS.items())


def _제목맞추기(seed: str) -> str | None:
    """대소문자·공백만 다른 것은 같은 문서로 본다. 그 밖의 '그럴듯한 제목'은 인정하지 않는다."""
    if seed in DOCS:
        return seed
    key = re.sub(r"\s+", " ", seed).strip().casefold()
    return next((t for t in DOCS if t.casefold() == key), None)


def plan(s: dict) -> dict:
    st = s["설정"]
    총예산 = st["절수"] * st["절예산"]
    roster = "\n".join(f"- {k}: {v}" for k, v in ROSTER.items())
    raw, rec = ask(
        "너는 리서치 팀의 코디네이터다. 질문에 답하는 보고서의 목차를 짜고 절마다 조사관 한 명을 맡긴다.\n"
        f"- 절은 1개 이상 {st['절수']}개 이하. 질문이 문서 한두 건으로 답이 나오면 절을 적게 둔다.\n"
        "- 목차는 **대상 단위**로 나눈다 — 질문이 실제로 묻는 기술·방법·수단·장벽 유형처럼, 문서 카드가 "
        "나뉜 단위와 맞춘다. '개요·정의·장단점·사례·도입방법' 같은 형식 단위나 '기술 측면·조직 측면·"
        "비용 측면' 같은 측면 단위로 나누지 마라. 그렇게 나누면 조사관 전원이 같은 문서를 읽는다.\n"
        "- 절마다 가장 먼저 읽을 시작 문서를 카드 목록에서 하나 고른다. 제목은 카드에 적힌 그대로 "
        "(영어 제목은 영어 그대로) 한 글자도 바꾸지 말고, 절끼리 서로 다른 문서를 준다.\n"
        f"- 절마다 읽을 문서 수(예산)를 1~{st['절예산_최대']} 사이로 정한다. 모든 절의 합은 {총예산} 이하. "
        "근거가 여러 문서에 흩어진 절에 더 준다.\n"
        f"- 절의 성격에 맞는 조사관을 명단에서 고른다.\n[조사관 명단]\n{roster}\n"
        "- 보고서 제목·절 제목·지시는 한국어로 쓴다.\n"
        'JSON으로만: {"제목":"보고서 제목","목차":[{"절":"절 제목","지시":"이 절에서 밝혀야 할 것 한두 문장",'
        '"역할":"명단의 이름 그대로","시작문서":"카드의 제목 그대로","예산":3}]}',
        f"[질문] {s['question']}\n[읽을 수 있는 문서 카드]\n{cards()}", 누가="코디네이터", 용도="기획")
    obj = jload(raw, {})

    toc, taken, 교정 = [], set(), []
    for item in (obj.get("목차") or [])[:st["절수"]]:
        절 = str(item.get("절") or "무제")
        원래 = str(item.get("시작문서") or "")
        seed = _제목맞추기(원래) if 원래 else None
        if not st["배정"]:                        # 스위치: 시작 문서를 주지 않는다
            seed = None
        elif 원래 and seed is None:
            교정.append({"절": 절, "원래": 원래, "사유": "목록에 없는 제목 → 자율"})
        elif seed in taken:
            교정.append({"절": 절, "원래": 원래, "사유": "다른 절과 중복 → 자율"})
            seed = None
        if seed:
            taken.add(seed)
        role = str(item.get("역할") or "")
        if not st["역할"]:                        # 스위치: 모두 같은 범용 조사관
            role = CFG["기본_역할"]
        elif role not in ROSTER:
            교정.append({"절": 절, "원래": role, "사유": "명단에 없는 역할 → 기본 역할"})
            role = CFG["기본_역할"]
        try:
            budget = int(item.get("예산") or st["절예산"])
        except (TypeError, ValueError):
            budget = st["절예산"]
        toc.append({"절": 절, "지시": str(item.get("지시") or s["question"]), "역할": role,
                    "시작문서": seed or "", "예산": max(1, min(budget, st["절예산_최대"]))})
    if not toc:
        교정.append({"절": "개요", "원래": raw[:80], "사유": "목차를 못 읽음 → 한 절짜리 기본 목차"})
        toc = [{"절": "개요", "지시": s["question"], "역할": CFG["기본_역할"], "시작문서": "", "예산": st["절예산"]}]

    while sum(t["예산"] for t in toc) > 총예산:    # 합계 상한 — 가장 큰 절부터 하나씩 깎는다
        max(toc, key=lambda t: t["예산"])["예산"] -= 1

    p = {"제목": str(obj.get("제목") or s["question"]), "목차": toc,
         "배치": list(range(len(toc))), "바퀴": 1, "교정": 교정}
    seeds = " · ".join(f"{t['역할']}→«{t['시작문서'] or '자율'}»×{t['예산']}" for t in toc)
    note = f" · 교정 {len(교정)}건" if 교정 else ""
    return {"plan": p, "calls": [rec], "log": [f"① 기획   목차 {len(toc)}절 · {seeds}{note}"]}


# ── ② 배치 ────────────────────────────────────────────────────────────────────

def dispatch(s: dict) -> dict:
    p = s["plan"]
    return {"log": [f"② 배치   {p.get('바퀴', 1)}바퀴 · 서브에이전트 {len(p.get('배치', []))}명 동시 파견"]}


def fanout(s: dict):
    """배치 뒤 갈림길 — 절마다 Send 하나. 남의 구역(다른 절의 시작 문서 + 이미 읽힌 문서)을 알려 준다."""
    idxs = s["plan"].get("배치", [])
    if not idxs:
        return "review"
    toc = s["plan"]["목차"]
    adopted = 채택원고(s["sections"], s["설정"]["원고_정책"])[0]
    sends = []
    for i in idxs:
        남의구역 = {t["시작문서"] for j, t in enumerate(toc) if j != i and t["시작문서"]}
        남의구역 |= {d for j, sec in adopted.items() if j != i for d in sec["읽은문서"]}
        sends.append(Send("researcher", {
            "question": s["question"], "설정": s["설정"],
            "task": {**toc[i], "번호": i, "바퀴": s["plan"].get("바퀴", 1),
                     "피하기": sorted(남의구역) if s["설정"]["구역"] else []},
            "prior": adopted.get(i, {})}))
    return sends


# ── ③ 서브에이전트 ─────────────────────────────────────────────────────────────

def read_one(title: str, brief: str) -> tuple[str, dict]:
    """격리의 경계선 — 원문은 여기서만 읽히고, 밖으로는 간추린 메모만 나간다."""
    return ask("너는 자료 조사 담당이다. 아래 문서를 읽고 지시에 관련된 내용만 한국어로 여섯 문장 이내로 "
               "간추려라. 수치·고유명사는 원문 그대로 옮긴다. 관련 없으면 '관련 없음'이라고만 답하라.\n"
               f"[지시] {brief}",
               f"[문서: {title}]\n{DOCS[title]}", 누가="조사관", 용도="읽기")


def 후보목록(read: list, 피하기: list) -> list:
    """읽은 문서의 링크가 다음 후보다. 링크가 막히면 전체에서, 그것도 막히면 구역을 푼다."""
    쓴것 = set(read) | set(피하기)
    frontier = sorted({x for v in read for x in LINKS.get(v, []) if x in DOCS} - 쓴것)
    return frontier or [x for x in DOCS if x not in 쓴것] or [x for x in DOCS if x not in read]


def 다음문서(t: dict, read: list, 피하기: list) -> tuple[str | None, dict]:
    """다음에 읽을 문서 하나. 예산이 남아 있으면 반드시 고른다 — 대조군도 예산을 끝까지 쓰므로
    같은 조건을 맞춘다. 모델이 후보에 없는 제목을 내면 후보 첫 번째로 바꾸고 기록한다."""
    cand = 후보목록(read, 피하기)
    if not cand:
        return None, [{"누가": "조사관", "용도": "고르기", "입력자수": 0, "지시자수": 0, "잘림": False,
                       "입력토큰": 0, "출력토큰": 0, "초": 0, "답": "(후보 없음)"}]
    return 고르기(역할문장(t) + " 맡은 절을 쓰기 위해", f"[맡은 절] {t['절']}\n[지시] {t['지시']}", read, cand)


def 고르기(누구: str, 맥락: str, read: list, cand: list, 누가: str = "조사관") -> tuple[str, list]:
    """후보 중 하나를 모델이 고른다. 이미 읽었거나 후보에 없는 제목이면 한 번 더 묻고,
    그래도 안 되면 후보 첫 번째로 바꾼다(대체 — 건수를 센다). 대조군도 이 함수를 쓴다."""
    recs, 주의 = [], ""
    for _ in range(2):
        raw, rec = ask(f"{누구} 다음에 읽을 문서를 후보 중에서 정확히 하나 고른다.\n"
                       'JSON으로만: {"문서":"후보에 있는 제목 그대로"}',
                       f"{맥락}\n[이미 읽음] {', '.join(read) or '없음'}\n[후보] {', '.join(cand[:60])}{주의}",
                       누가=누가, 용도="고르기")
        recs.append(rec)
        pick = _제목맞추기(str(jload(raw, {}).get("문서") or ""))
        if pick and pick in cand:
            return pick, recs
        주의 = f"\n[주의] 방금 고른 «{pick or raw[:40]}» 는 이미 읽었거나 후보에 없다. 후보 목록에서 다시 골라라."
    recs[-1]["대체"] = True                       # 두 번 다 못 써서 후보 첫 번째로
    return cand[0], recs


def 탐색(t: dict, prior: dict) -> tuple[list, list, list, list]:
    """예산만큼 새로 읽는다. 배정된 시작 문서가 1순위. (읽은 문서, 메모, 호출 기록, 이번에 새로 읽은 것)."""
    read, notes = list(prior.get("읽은문서", [])), [list(n) for n in prior.get("메모", [])]
    피하기 = t.get("피하기") or []
    recs, 새로 = [], []
    다음 = t.get("시작문서") if t.get("시작문서") in DOCS else None
    for _ in range(t["예산"]):                   # 코드가 정한 상한 — 모델이 어길 수 없다
        if 다음 is None or 다음 in read:
            다음, rs = 다음문서(t, read, 피하기)
            recs += rs
        if 다음 is None:
            break
        memo, rec = read_one(다음, t["지시"])
        recs.append(rec)
        notes.append([다음, memo])
        read.append(다음)
        새로.append(다음)
        다음 = None
    return read, notes, recs, 새로


집필_형식 = ('JSON으로만: {"문장":[{"글":"한국어 문장 하나","근거":["자료 제목"]}, ...],'
            '"충분":true,"부족":""}\n'
            '- "근거" 에는 그 문장의 근거가 된 자료 제목을 자료 목록의 [ ] 안 제목 그대로(영어 제목은 영어 그대로, '
            '번역하지 말고) 적는다. 근거가 없는 문장은 쓰지 않는다.')


def 문장조립(문장: list) -> tuple[str, int]:
    """[{"글","근거"}] → '… 이다 «제목».' 인용을 마침표 앞에 둔다 — 마침표 뒤에 두면 문장 분리기가
    인용을 다음 문장에 붙인다(수업 코드의 숨은 문제). (본문, 근거 칸이 빈 문장 수)."""
    out, 빈근거 = [], 0
    for x in 문장:
        if not isinstance(x, dict):
            continue
        글 = re.sub(r"\s+", " ", str(x.get("글") or "")).strip()
        if not 글:
            continue
        근거 = [str(c).strip() for c in (x.get("근거") or []) if str(c).strip()]
        근거 = [_제목맞추기(c) or c for c in 근거]   # 대소문자만 다른 건 맞추고, 지어낸 제목은 그대로 둔다(→ 허위 인용으로 잡힌다)
        if not 근거:
            빈근거 += 1
        끝 = 글[-1] if 글[-1] in ".!?" else "."
        몸 = 글[:-1].rstrip() if 글[-1] in ".!?" else 글
        out.append(f"{몸} {' '.join(f'«{c}»' for c in dict.fromkeys(근거))}{끝}" if 근거 else f"{몸}{끝}")
    return " ".join(out), 빈근거


def 집필(t: dict, notes: list) -> tuple[dict, dict]:
    """모은 메모만 근거로 절 원고를 쓰고 충분/부족을 스스로 신고한다(같은 호출 — 추가 비용 0).
    문장별 구조로 받아 코드가 인용 표기를 붙인다 — 자유 서술에 «» 를 맡기면 gpt-4o-mini 가 자주 빠뜨린다."""
    자료 = "\n\n".join(f"[{d}]\n{n}" for d, n in notes) or "(읽은 자료 없음)"
    raw, rec = ask(f"{역할문장(t)} 아래 자료만 근거로 보고서의 한 절을 한국어로 쓴다. "
                   "문장 여섯 개 이상 열두 개 이하, 모두 합쳐 600자 이상. 자료에 없는 내용은 쓰지 마라. "
                   "다 쓴 뒤 스스로 신고한다 — 충분/부족은 문장 수나 글자 수가 아니라 **지시가 묻는 내용을 자료로 "
                   "채웠는가**로만 판단한다. 못 채웠으면 충분을 false 로 하고, 자료에 없어서 비어 있는 내용이 "
                   "무엇인지 한 문장으로 적는다(다음 조사관이 그 빈 칸을 겨냥해 새 문서를 찾는다).\n"
                   + 집필_형식,
                   f"[맡은 절] {t['절']}\n[지시] {t['지시']}\n[모은 자료]\n{자료}", 누가="조사관", 용도="집필")
    obj = jload(raw, {})
    text, 빈근거 = 문장조립(obj.get("문장") or [])
    교정수 = 0
    if len(text) < 100:                          # 구조를 못 지켰으면 원문에서라도 건지고 [제목] 을 «제목» 으로
        text = re.sub(r'^\s*\{.*?"(본문|글)"\s*:\s*"?', "", raw, flags=re.S)[:2500].strip()
        text, 교정수 = 인용형식교정(text)
        rec["구조실패"] = True
    rec["인용형식교정"] = 교정수
    return {"본문": text, "충분": bool(obj.get("충분")), "부족": str(obj.get("부족") or ""),
            "교정": 교정수, "빈근거": 빈근거}, rec


def researcher(s: dict) -> dict:
    """절 하나를 통째로 맡는다 — 탐색하고, 쓰고, 원고만 올린다(원문·메모 원본은 위로 안 간다)."""
    t = s["task"]
    read, notes, recs, 새로 = 탐색(t, s.get("prior") or {})
    원고, rec = 집필(t, notes)
    인용 = 인용들(원고["본문"])
    sec = {"번호": t["번호"], "절": t["절"], "역할": t["역할"], "바퀴": t["바퀴"], "지시": t["지시"],
           "시작문서": t.get("시작문서", ""), "예산": t["예산"], "피하기": t.get("피하기", []),
           "본문": 원고["본문"], "읽은문서": read, "새로읽음": 새로, "메모": notes, "인용": 인용,
           "허위인용": sorted({c for c in 인용 if c not in read}),
           "충분": 원고["충분"], "부족": 원고["부족"], "인용형식교정": 원고["교정"], "근거없는문장": 원고["빈근거"],
           "대체선택": sum(1 for r in recs if r.get("대체"))}
    sec["근거문장수"] = 근거문장수(sec)
    mark = "충분" if sec["충분"] else f"부족({sec['부족'][:24]})"
    return {"sections": [sec], "calls": recs + [rec],
            "visited": [[t["번호"], d] for d in 새로],
            "log": [f"   ③ {t['역할']} «{t['절'][:16]}» 새로 {len(새로)}/{t['예산']}건 (누적 {len(read)}) · "
                    f"{len(원고['본문'])}자 · 인용 {len(인용)}곳 · 근거문장 {sec['근거문장수']} · {mark}"]}


# ── 두 번째 원고를 어떻게 할까 ──────────────────────────────────────────────────

def 채택원고(sections: list, 정책: str) -> tuple[dict, list]:
    """절 번호별로 채택된 원고 하나와, 재위임 원고를 받았는지/버렸는지 판정 기록을 돌려준다.

    "근거비교": 새 원고는 ① 허위 인용이 없고 ② 읽은 문서를 인용한 문장 수가 이전 원고 이상일 때만
               채택한다. 무조건 덮어쓰면 인용을 빠뜨린 재작성본이 멀쩡한 원고를 지운다.
    "덮어쓰기": 수업 코드와 같다 — 늘 마지막 원고.
    """
    adopted, 판정 = {}, []
    for sec in sorted(sections, key=lambda x: (x["번호"], x.get("바퀴", 1))):
        i = sec["번호"]
        old = adopted.get(i)
        if old is None or 정책 == "덮어쓰기":
            adopted[i] = sec
            if old is not None:
                판정.append({"번호": i, "바퀴": sec["바퀴"], "결과": "채택(덮어쓰기)"})
            continue
        ok = not sec["허위인용"] and sec["근거문장수"] >= old["근거문장수"]
        판정.append({"번호": i, "바퀴": sec["바퀴"], "결과": "채택" if ok else "기각",
                     "근거문장": f"{old['근거문장수']}→{sec['근거문장수']}", "허위인용": sec["허위인용"]})
        if ok:
            adopted[i] = sec
    return adopted, 판정


# ── ③ 점검 ────────────────────────────────────────────────────────────────────

def review(s: dict) -> dict:
    """LLM 을 부르지 않는다 — 조사관이 스스로 적은 충분/부족만 모아 누구를 다시 보낼지 정한다."""
    st, p = s["설정"], s["plan"]
    toc, wheel = p["목차"], p.get("바퀴", 1)
    adopted, 판정 = 채택원고(s["sections"], st["원고_정책"])
    이번판정 = [x for x in 판정 if x["바퀴"] == wheel]
    판정글 = "".join(f" · {toc[x['번호']]['절'][:10]} 재위임본 {x['결과']}({x.get('근거문장', '')})" for x in 이번판정)

    if not st["재위임"] or wheel >= st["바퀴_상한"]:    # 예산 쪽 상한을 먼저 본다 — 무한 루프 차단
        gaps = []
    else:
        gaps = [i for i in range(len(toc)) if not adopted.get(i, {}).get("충분", False)]

    if not gaps:
        why = "재위임 끔" if not st["재위임"] else ("바퀴 소진" if wheel >= st["바퀴_상한"] else "빈 칸 없음")
        남은부족 = sum(1 for i in range(len(toc)) if not adopted.get(i, {}).get("충분", False))
        return {"plan": {**p, "배치": [], "종료": why},
                "log": [f"④ 점검   {len(toc)}절 중 부족 {남은부족}개 — 종합으로 ({why}){판정글}"]}

    newtoc = [dict(t) for t in toc]
    for i in gaps:
        prev = adopted.get(i, {})
        newtoc[i]["지시"] = (f"{toc[i]['지시']} (재위임: 지난번에 «{'», «'.join(prev.get('읽은문서', [])) or '없음'}» 를 "
                             f"읽었지만 '{prev.get('부족') or '근거가 모자랐다'}'. 그 빈 칸을 겨냥해 아직 안 본 문서를 찾아라)")
    return {"plan": {**p, "목차": newtoc, "배치": gaps, "바퀴": wheel + 1},
            "log": [f"④ 점검   {len(toc)}절 중 부족 {len(gaps)}개 — "
                    f"«{'», «'.join(toc[i]['절'][:12] for i in gaps)}» 재위임{판정글}"]}


def route(s: dict) -> str:
    return "more" if s["plan"].get("배치") else "done"


# ── ④ 종합 ────────────────────────────────────────────────────────────────────

def synthesize(s: dict) -> dict:
    """편집자는 절 본문을 고치지 않는다 — 제목과 첫머리만 보고 머리말·맺음말을 쓴다(인용을 지킨다)."""
    adopted, _ = 채택원고(s["sections"], s["설정"]["원고_정책"])
    order = [adopted[i] for i in sorted(adopted)]
    n = CFG["종합_첫머리_글자수"]
    outline = "\n".join(f"{k+1}. {x['절']}: {x['본문'][:n]}…" for k, x in enumerate(order))
    raw, rec = ask("너는 보고서를 마무리하는 편집자다. 아래는 조사관들이 각자 쓴 절의 제목과 첫머리다. "
                   "본문은 고치지 말고, 전체를 여는 머리말과 닫는 맺음말만 한국어로 써라. 각각 세 문장 이내.\n"
                   'JSON으로만: {"머리말":"...","맺음말":"..."}',
                   f"[질문] {s['question']}\n[보고서 제목] {s['plan']['제목']}\n[절 목록]\n{outline}",
                   누가="편집자", 용도="종합")
    obj = jload(raw, {})
    parts = [f"# {s['plan']['제목']}", str(obj.get("머리말") or "")]
    for k, x in enumerate(order):
        parts.append(f"## {k+1}. {x['절']}  _({x['역할']})_\n\n{x['본문']}")
    parts.append(f"## 맺음말\n\n{obj.get('맺음말') or ''}")
    report = "\n\n".join(p for p in parts if p.strip())
    return {"report": report, "calls": [rec],
            "log": [f"⑤ 종합   {len(order)}절 이어붙임 → 보고서 {len(report):,}자 (편집자는 절 첫머리 {n}자씩만 봤다)"]}


# ── 그래프 ────────────────────────────────────────────────────────────────────

def build():
    g = StateGraph(Research)
    for name, fn in (("plan", plan), ("dispatch", dispatch), ("researcher", researcher),
                     ("review", review), ("synthesize", synthesize)):
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_edge("plan", "dispatch")
    g.add_conditional_edges("dispatch", fanout, ["researcher", "review"])          # ②⇉③ 팬아웃
    g.add_edge("researcher", "review")
    g.add_conditional_edges("review", route, {"more": "dispatch", "done": "synthesize"})   # 재위임 루프
    g.add_edge("synthesize", END)
    return g.compile()


def 설정만들기(덮어쓸: dict | None = None) -> dict:
    st = {k: CFG[k] for k in ("절수", "절예산", "절예산_최대", "바퀴_상한", "원고_정책")} | dict(CFG["스위치"])
    for k, v in (덮어쓸 or {}).items():
        if k not in st:
            raise KeyError(f"모르는 설정: {k} (가능: {', '.join(st)})")
        st[k] = v
    return st


def 격리(calls: list) -> dict:
    """코디네이터·편집자가 본 글자 수와 조사관이 본 글자 수를 따로 센다."""
    위 = sum(c["입력자수"] for c in calls if c["누가"] in ("코디네이터", "편집자"))
    아래 = sum(c["입력자수"] for c in calls if c["누가"] == "조사관")
    return {"코디네이터가_본_글자": 위, "조사관이_본_글자": 아래,
            "격리율": round(100 * 위 / max(위 + 아래, 1), 1), "LLM호출": len(calls),
            "입력토큰": sum(c["입력토큰"] for c in calls), "출력토큰": sum(c["출력토큰"] for c in calls),
            "고르기_대체": sum(1 for c in calls if c.get("대체")),
            "인용형식교정": sum(c.get("인용형식교정", 0) for c in calls),
            "집필_구조실패": sum(1 for c in calls if c.get("구조실패"))}


def run(question: str, 덮어쓸: dict | None = None, qid: str | None = None, 라벨: str = "기본",
        save: bool = True, verbose: bool = True) -> dict:
    st = 설정만들기(덮어쓸)
    t0 = time.time()
    final = build().invoke({"question": question, "설정": st, "plan": {}, "sections": [], "visited": [],
                            "calls": [], "report": "", "log": [], "task": {}, "prior": {}},
                           {"recursion_limit": 50})
    adopted, 판정 = 채택원고(final["sections"], st["원고_정책"])
    rec = {"run_id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
           "시각": datetime.now().isoformat(timespec="seconds"), "qid": qid, "질문": question, "라벨": 라벨,
           "설정": st, "초": round(time.time() - t0, 1), "plan": final["plan"],
           "sections": final["sections"], "채택": {str(k): v["바퀴"] for k, v in adopted.items()},
           "원고판정": 판정, "visited": final["visited"], "calls": final["calls"],
           "격리": 격리(final["calls"]), "report": final["report"], "log": final["log"]}
    if verbose:
        for line in final["log"]:
            print(line)
        g = rec["격리"]
        print(f"   · 격리: 코디네이터·편집자 {g['코디네이터가_본_글자']:,}자 / 조사관 {g['조사관이_본_글자']:,}자 "
              f"→ 격리율 {g['격리율']}% · LLM {g['LLM호출']}회 · 토큰 {g['입력토큰']:,}+{g['출력토큰']:,} · {rec['초']}초\n"
              f"   · 고르기 대체 {g['고르기_대체']}회 · 집필 구조 실패 {g['집필_구조실패']}회 · 인용 형식 교정 {g['인용형식교정']}곳")
    if save:
        (OUT / "reports").mkdir(parents=True, exist_ok=True)
        with open(OUT / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        (OUT / "reports" / f"{rec['run_id']}.md").write_text(final["report"], encoding="utf-8")
        if verbose:
            print(f"   · 저장: output/runs.jsonl · output/reports/{rec['run_id']}.md")
    return rec


def _값(v: str):
    return {"true": True, "false": False}.get(v.lower(), int(v) if v.isdigit() else v)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="딥리서처 한 번 실행")
    ap.add_argument("q", help="questions.json 의 ID(예: M2) 또는 질문 문장")
    ap.add_argument("--set", nargs="*", default=[], help="설정 덮어쓰기, 예: 재위임=false 절예산=2")
    ap.add_argument("--label", default="기본")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()
    q = QUESTIONS.get(a.q, {"id": None, "질문": a.q})
    over = dict(kv.split("=", 1) for kv in a.set)
    print(f"[{q['id'] or '직접'}] {q['질문']}")
    run(q["질문"], {k: _값(v) for k, v in over.items()}, qid=q["id"], 라벨=a.label, save=not a.no_save)
