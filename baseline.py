"""대조군 — 혼자 하는 오케스트레이터. 나누지 않는다: 한 명이 고르고, 읽고, 요약을 한 맥락에 쌓아 두고 다 쓴다.

    python baseline.py M2 --budget 9     # 읽기 예산을 팀 실행이 실제로 읽은 건수에 맞춘다

공정성 — 팀과 다른 것은 '나눠 맡기느냐' 하나뿐이어야 한다. 나머지는 팀의 함수를 그대로 쓴다.
  자료·모델      같은 코퍼스, 같은 모델(gpt-4o-mini, temperature 0)
  처음 보는 것   코디네이터와 같은 카드(graph.cards)를 보고 첫 문서를 고른다
  읽기           graph.read_one — 같은 요약 프롬프트, 같은 6만 자 상한
  고르기         graph.고르기 · graph.후보목록 — 같은 링크 후보, 같은 다시 묻기·대체 규칙 (피하기만 없다)
  예산           짝지은 팀 실행이 실제로 읽은 건수만큼, 끝까지 쓴다
  집필 형식      문장별 {글, 근거} → graph.문장조립 이 «제목» 을 붙인다, graph.인용형식교정 도 같다
한계 — 대조군도 원문 대신 read_one 의 요약만 쌓는다(원문 전체는 창에 안 들어간다). 그래서 이 비교는
'창을 넘는가'가 아니라 '나눠 맡기는 것이 값을 하는가'를 잰다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from datetime import datetime

import graph as G

누구 = "너는 혼자 조사하고 보고서를 쓰는 조사자다. 질문에 답하기 위해"


def 혼자(question: str, 예산: int, qid: str | None = None, 라벨: str = "혼자", 절수: int | None = None,
        스스로지시: bool = False, save: bool = False, verbose: bool = True) -> dict:
    """스스로지시=False: 읽을 때 질문 전체를 지시로 쓴다 — (가) 수업 방식.
    스스로지시=True: 다음 문서를 고르는 같은 호출에서 '이 문서에서 찾을 것'도 정해 그것을 지시로 쓴다 — (나)."""
    절수 = 절수 or G.CFG["절수"]
    t0 = time.time()
    read, notes, calls, 지시들 = [], [], [], []

    # 첫 문서 — 코디네이터가 본 것과 같은 카드를 보고 고른다
    first, rs = G.고르기(누구, f"[질문] {question}\n[읽을 수 있는 문서 카드]\n{G.cards()}", [], list(G.DOCS),
                         누가="코디네이터", 찾을것=스스로지시)
    calls += rs
    다음, 지시 = first, rs[-1].get("찾을것") or question
    while len(read) < 예산:                     # 예산은 끝까지 쓴다 — 중간에 멈추면 상대 손발을 묶는 셈
        if 다음 is None:
            cand = G.후보목록(read, [])
            if not cand:
                break
            요약 = "\n".join(f"- {d}: {m[:120]}" for d, m in notes)
            다음, rs = G.고르기(누구, f"[질문] {question}\n[지금까지 모은 요약]\n{요약 or '없음'}", read, cand,
                               누가="코디네이터", 찾을것=스스로지시)
            calls += rs
            지시 = rs[-1].get("찾을것") or question
        지시 = 지시 if 스스로지시 else question
        memo, rec = G.read_one(다음, 지시)
        calls.append(rec)
        지시들.append(지시)
        notes.append([다음, memo])
        read.append(다음)
        다음 = None

    자료 = "\n\n".join(f"[{d}]\n{n}" for d, n in notes) or "(읽은 자료 없음)"
    raw, rec = G.ask(
        "너는 혼자 조사하고 보고서를 쓰는 필자다. 아래 요약들만 근거로 질문에 답하는 보고서를 한국어로 쓴다.\n"
        f"- 절은 1개 이상 {절수}개 이하. 절마다 문장 여섯 개 이상 열두 개 이하. 자료에 없는 내용은 쓰지 마라.\n"
        "- 머리말과 맺음말은 각각 세 문장 이내.\n"
        'JSON으로만: {"제목":"보고서 제목","머리말":"...","절":[{"제목":"절 제목","문장":[{"글":"한국어 문장 하나",'
        '"근거":["자료 제목"]}]}],"맺음말":"..."}\n'
        '- "근거" 에는 그 문장의 근거가 된 자료 제목을 자료 목록의 [ ] 안 제목 그대로(영어 제목은 영어 그대로, '
        '번역하지 말고) 적는다. 근거가 없는 문장은 쓰지 않는다.',
        f"[질문] {question}\n[모은 요약]\n{자료}", 누가="코디네이터", 용도="집필")
    obj = G.jload(raw, {})
    parts, 교정 = [f"# {obj.get('제목') or question}", str(obj.get("머리말") or "")], 0
    for k, sec in enumerate((obj.get("절") or [])[:절수]):
        본문, _ = G.문장조립(sec.get("문장") or []) if isinstance(sec, dict) else ("", 0)
        parts.append(f"## {k+1}. {sec.get('제목') or '무제'}  _(혼자)_\n\n{본문}")
    rec["답"] = raw[:12000]                      # 구조가 깨졌을 때 나중에 다시 건질 수 있게 원답을 남긴다
    if len(parts) == 2:                          # 구조를 못 지켰으면 팀과 같은 함수로 문장 조각을 건진다
        rec["구조실패"] = True
        본문, _ = G.문장조립(G.문장건지기(raw))
        if len(본문) < 100:                      # 그래도 안 되면 팀과 같은 규칙으로 원문에서 건진다
            본문, 교정 = G.인용형식교정(re.sub(r"^\s*\{.*?\"(본문|글)\"\s*:\s*\"?", "", raw, flags=re.S)[:6000])
        parts.append(f"## 1. 본문  _(혼자)_\n\n{본문}")
    rec["인용형식교정"] = 교정
    parts.append(f"## 맺음말\n\n{obj.get('맺음말') or ''}")
    calls.append(rec)
    report = "\n\n".join(p for p in parts if p.strip())

    out = {"run_id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4],
           "시각": datetime.now().isoformat(timespec="seconds"), "qid": qid, "질문": question, "라벨": 라벨,
           "설정": {"예산": 예산, "절수": 절수, "모델": G.CFG["모델"], "스스로지시": 스스로지시}, "예산": 예산, "초": round(time.time() - t0, 1),
           "plan": {}, "sections": [], "채택": {}, "visited": [["(혼자)", d] for d in read],
           "메모": notes, "읽기지시": 지시들, "calls": calls, "격리": G.격리(calls), "report": report, "log": []}
    from metrics import 재기
    out["metrics"] = 재기(out)
    if verbose:
        m = out["metrics"]
        print(f"혼자     예산 {예산} · 읽음 {len(read)}건 {read}")
        print(f"         보고서 {len(report):,}자 · LLM {len(calls)}회 · {out['초']}초")
        print("⑥ 측정   " + " · ".join(f"{k} {v}%" for k, v in m["신호"].items() if v is not None)
              + " · 경보 " + (", ".join(f"{k} {v}" for k, v in m["경보"].items() if v) or "없음"))
    if save:
        (G.OUT / "reports").mkdir(parents=True, exist_ok=True)
        with open(G.OUT / "runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        (G.OUT / "reports" / f"{out['run_id']}.md").write_text(report, encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="혼자 하는 대조군 한 번 실행")
    ap.add_argument("q", help="questions.json 의 ID 또는 질문 문장")
    ap.add_argument("--budget", type=int, default=G.CFG["절수"] * G.CFG["절예산"], help="읽기 예산 (팀 실행과 짝지어 맞춘다)")
    ap.add_argument("--self-brief", action="store_true", help="(나) 문서마다 찾을 것을 스스로 정한다")
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args()
    q = G.QUESTIONS.get(a.q, {"id": None, "질문": a.q})
    print(f"[{q['id'] or '직접'}] {q['질문']}")
    혼자(q["질문"], a.budget, qid=q["id"], 라벨="혼자(나)" if a.self_brief else "혼자(가)",
        스스로지시=a.self_brief, save=a.save)
