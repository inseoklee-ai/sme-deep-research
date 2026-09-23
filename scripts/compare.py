"""나란히 읽기 자료 — 같은 질문의 보고서 여러 편, 조사관 원고 대 최종본, 인용 대조표를 한 문서로 만든다.

    python scripts/compare.py M1                 # 반복 1, 조건 기본 · 역할끔 · 혼자(가) · 혼자(나)
    python scripts/compare.py M1 --rep 2 --cond 기본 배정끔 혼자(나)

산출: output/compare/<qid>_<반복>.md
지표는 명백한 실패를 거르는 데만 쓴다 — 어느 쪽이 나은지는 사람이 읽고 적는다.

인용 대조표: 보고서 문장마다 붙은 «문서» 에 대해
  ① 그 문장을 쓴 조사관이 받은 메모(요약) 가운데 그 문서의 것
  ② 원문에서 그 문장과 낱말이 가장 많이 겹치는 대목 (영어 원문이면 번역하지 않은 채)
를 나란히 둔다. '읽지 않은 문서 인용'은 코드가 잡지만, 읽은 문서를 엉뚱한 문장에 붙인 것은
사람이 이 표를 보고 잡는다. ②는 낱말 겹침으로 고른 후보일 뿐 판정이 아니다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import graph as G      # noqa: E402
import metrics as M    # noqa: E402

RUNS = G.OUT / "ablation_runs.jsonl"
OUT = G.OUT / "compare"


def _낱말(글: str) -> set:
    """겹침을 볼 낱말 — 영문 4자 이상, 한글 2자 이상, 숫자(85%, 1.5 같은). 한국어 문장과 영어 원문 사이에서는
    괄호 속 영어 용어와 숫자만 겹치므로 약한 단서다. 판정은 사람이 원문을 열어 보고 한다."""
    return {w.lower() for w in re.findall(r"[A-Za-z]{4,}|[가-힣]{2,}|\d+(?:\.\d+)?%?", 글)}


def 원문대목(doc: str, 문장: str, 폭: int = 260) -> str:
    """원문을 문단으로 나눠, 문장과 겹치는 낱말(영문 4자 이상·한글 2자 이상)이 가장 많은 문단의 앞부분."""
    want = _낱말(re.sub(r"«[^»]+»", "", 문장))
    best, score = "", -1
    for para in re.split(r"\n\s*\n|\n(?===)", G.DOCS.get(doc, "")):
        s = len(want & _낱말(para))
        if s > score and len(para.strip()) > 40:
            best, score = para.strip(), s
    return f"{re.sub(r'\s+', ' ', best)[:폭]}… (겹친 낱말 {max(score, 0)}개)"


def 인용표(run: dict, 최대: int = 12) -> list[str]:
    메모 = {}
    for s in M.채택된절(run):
        for d, m in s.get("메모", []):
            메모[(s["절"], d)] = m
    for d, m in run.get("메모", []):                 # 대조군은 절이 없다
        메모[("(혼자)", d)] = m
    절이름 = {s["절"] for s in M.채택된절(run)}
    rows, n = [], 0
    현재절 = "(혼자)"
    for line in run["report"].split("\n"):
        if line.startswith("## "):                   # 머리글 '## 2. 절 제목  _(역할)_' 에서 절 제목을 읽는다
            head = re.sub(r"^##\s*\d+\.\s*|\s*_\(.*\)_\s*$", "", line).strip()
            현재절 = head if head in 절이름 else "(혼자)"
            continue
        for 문 in G.문장들(line):
            for c in dict.fromkeys(G.인용들(문)):
                if n >= 최대:
                    return rows
                n += 1
                memo = 메모.get((현재절, c)) or 메모.get(("(혼자)", c)) or "(이 절의 메모에 없음)"
                rows.append(f"| {n} | {문[:140]} | «{c}» | {memo[:180]} | {원문대목(c, 문)} | |")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("qid")
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--cond", nargs="*", default=["기본", "역할끔", "혼자(가)", "혼자(나)"])
    a = ap.parse_args()
    runs = {(r["실험"]["qid"], r["실험"]["반복"], r["실험"]["조건"]): r for r in M.불러오기(RUNS)}
    picked = [(c, runs.get((a.qid, a.rep, c))) for c in a.cond]
    q = G.QUESTIONS[a.qid]
    out = [f"# 나란히 읽기 — {a.qid} (반복 {a.rep})", "", f"**질문** {q['질문']}  ",
           f"**유형** {q['유형']} · **왜 나눌 만한가** {q['왜 나눌 만한가']}", "",
           "## 1. 지표 (명백한 실패 거르기용 — 순위표 아님)", "",
           "| 조건 | 근거율 | 인용편중 | 중복읽기 | 읽고안씀 | 격리율 | 글자수 | 경보 |", "|---|---|---|---|---|---|---|---|"]
    for c, r in picked:
        if not r:
            out.append(f"| {c} | (기록 없음) | | | | | | |")
            continue
        m = M.재기(r)
        s = m["신호"]
        울림 = ", ".join(f"{k} {v}" for k, v in m["경보"].items() if v) or "없음"
        out.append(f"| {c} | {s['근거율']} | {s['인용편중']} | {s['중복읽기율'] if s['중복읽기율'] is not None else '-'} | "
                   f"{s['읽고안쓴비율']} | {s['격리율']} | {m['참고']['보고서자수']:,} | {울림} |")
    out += ["", "## 2. 나의 판단 (직접 적는다)", "",
            "- 어느 쪽이 나은가: ", "- 그렇게 판단한 이유: ", "- 마음에 안 드는 대목 → 어느 절 · 어느 자료에서 비롯됐나: ", ""]
    for k, (c, r) in enumerate(picked, start=3):
        if not r:
            continue
        out += [f"## {k}. {c}", ""]
        if r.get("plan", {}).get("목차"):
            out += ["**목차 · 배정**", "", "| 절 | 역할 | 시작 문서 | 예산 | 읽은 문서 | 자기신고 |", "|---|---|---|---|---|---|"]
            for s in M.채택된절(r):
                신고 = "충분" if s["충분"] else f"부족: {s['부족']}"
                out.append(f"| {s['절']} | {s['역할']} | {s['시작문서'] or '자율'} | {s['예산']} | "
                           f"{', '.join(s['읽은문서'])} | {신고} |")
            out.append("")
        else:
            out += [f"**읽은 순서** {' → '.join(d for _, d in r['visited'])}", ""]
        out += ["<details><summary>최종 보고서 펼치기</summary>", "", r["report"], "", "</details>", ""]
        if r.get("sections"):
            out += ["**조사관 원고 대 최종본** — 편집자는 본문을 고치지 않는다. 같지 않으면 표시한다.", ""]
            for s in M.채택된절(r):
                same = s["본문"] in r["report"]
                out.append(f"- {s['절']}: {'최종본에 그대로 들어감' if same else '⚠ 최종본과 다름'} "
                           f"({len(s['본문'])}자, 재위임본 채택 {s.get('바퀴', 1) > 1})")
            out.append("")
        out += ["**인용 대조표** (앞 12곳) — 맨 끝 칸에 제자리 ○ / 어긋남 ✕ 를 직접 적는다", "",
                "| # | 보고서 문장 | 인용 | 조사관이 받은 메모 | 원문에서 겹치는 대목 | 판정 |", "|---|---|---|---|---|---|"]
        out += 인용표(r) + [""]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{a.qid}_{a.rep}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"저장: {path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
