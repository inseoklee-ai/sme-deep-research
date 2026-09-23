"""절제 실험 — 스위치를 하나씩 끄고, 혼자 하는 대조군과 함께 같은 잣대로 잰다.

    python ablation.py                    # 전체: 질문 11 × 조건 7 × 반복 3 = 231회. 끊기면 다시 실행 — 이어서 돈다
    python ablation.py --only M1 S1       # 일부 질문만
    python ablation.py --summary          # 새로 돌리지 않고 기록으로 요약만 다시 만든다

조건 7가지
  기본 · 배정끔 · 구역끔 · 역할끔 · 재위임끔   (팀 — 한 번에 스위치 하나만 끈다)
  혼자(가)  질문 전체를 읽기 지시로 (수업 방식)
  혼자(나)  문서마다 찾을 것을 스스로 정해 읽기 지시로 (같은 호출, 추가 비용 없음)
대조군의 읽기 예산 = 같은 질문·같은 반복의 '기본' 실행이 실제로 읽은 건수 (짝 맞춤)

산출물
  output/ablation_runs.jsonl        실행 기록 한 줄씩 (끝나는 즉시 저장 — 이어서 돌리기의 근거)
  output/ablation_errors.jsonl      실패한 실행 (다시 실행하면 그 칸만 다시 돈다)
  output/reports/ablation/*.md      보고서 — 나란히 읽기용
  output/ablation.json              요약: 조건별 평균·흔들림, 유형별, 질문별, 공정성 점검표, 스위치 확인
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import statistics
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import baseline as B
import graph as G
import metrics as M

RUNS = G.OUT / "ablation_runs.jsonl"
ERRS = G.OUT / "ablation_errors.jsonl"
SUMMARY = G.OUT / "ablation.json"
REPORTS = G.OUT / "reports" / "ablation"

팀조건 = {"기본": {}, "배정끔": {"배정": False}, "구역끔": {"구역": False},
          "역할끔": {"역할": False}, "재위임끔": {"재위임": False}}
혼자조건 = {"혼자(가)": False, "혼자(나)": True}          # 값 = 스스로지시
조건들 = list(팀조건) + list(혼자조건)
반복수 = 3

# 실험 2 — 실험 1 에서 재위임이 한 번도 열리지 않아(부족 신고 0/96), 코드 판정을 더해 재위임만 다시 잰다.
# 두 조건 모두 같은 코드 판정 설정 — 다른 것은 재위임 켜고 끔 하나뿐이다.
실험2 = {"기본": {"부족_판정": "자기신고+코드"}, "재위임끔": {"부족_판정": "자기신고+코드", "재위임": False}}

# 지표 규칙의 지문 — 실험 도중 문장 분리·지표 코드가 바뀌면 기록마다 달라져서 드러난다
지표지문 = hashlib.sha1((inspect.getsource(G.문장들) + inspect.getsource(M)).encode()).hexdigest()[:10]

_lock = threading.Lock()
_멈춤 = threading.Event()


def _기록(path: Path, rec: dict) -> None:
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def 불러오기() -> dict:
    """이미 끝난 (질문, 반복, 조건) → 기록. 같은 칸이 두 번 있으면 뒤의 것."""
    done = {}
    if RUNS.exists():
        for r in M.불러오기(RUNS):
            e = r["실험"]
            done[(e["qid"], e["반복"], e["조건"])] = r
    return done


def 한칸(qid: str, 반복: int, 조건: str, done: dict) -> dict | None:
    if (qid, 반복, 조건) in done or _멈춤.is_set():
        return done.get((qid, 반복, 조건))
    q = G.QUESTIONS[qid]["질문"]
    if 조건 in 팀조건:
        rec = G.run(q, 팀조건[조건], qid=qid, 라벨=조건, save=False, verbose=False)
    else:
        짝 = done.get((qid, 반복, "기본"))
        if 짝 is None:
            return None                           # 기본이 아직 없으면 예산을 모른다 — 다음에
        예산 = 짝["metrics"]["참고"]["읽기횟수"]
        rec = B.혼자(q, 예산, qid=qid, 라벨=조건, 스스로지시=혼자조건[조건], verbose=False)
        rec["짝_run_id"] = 짝["run_id"]
    rec["실험"] = {"qid": qid, "반복": 반복, "조건": 조건, "지표지문": 지표지문}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{qid}_{반복}_{조건}.md").write_text(rec["report"], encoding="utf-8")
    _기록(RUNS, rec)
    done[(qid, 반복, 조건)] = rec
    return rec


def 한묶음(qid: str, 반복: int, done: dict) -> list[str]:
    """한 (질문, 반복) — 기본을 먼저 돌려 대조군 예산을 정하고, 나머지를 차례로."""
    msgs = []
    for 조건 in 조건들:
        if _멈춤.is_set():
            break
        try:
            t0 = time.time()
            새로 = (qid, 반복, 조건) not in done
            rec = 한칸(qid, 반복, 조건, done)
            if rec and 새로:
                s = rec["metrics"]["신호"]
                msgs.append(f"  {qid} #{반복} {조건:<7} 근거율 {s['근거율']} · 편중 {s['인용편중']} · "
                            f"읽기 {rec['metrics']['참고']['읽기횟수']} · {time.time() - t0:.0f}초")
                print(msgs[-1], flush=True)
        except G.잔액소진 as e:
            _멈춤.set()
            print(f"\n■ 멈춤: {e}\n", flush=True)
            break
        except Exception as e:                    # 한 칸이 실패해도 기록하고 다음 칸으로 — 다시 실행하면 그 칸만 다시 돈다
            _기록(ERRS, {"시각": datetime.now().isoformat(timespec="seconds"), "qid": qid, "반복": 반복,
                         "조건": 조건, "오류": repr(e), "추적": traceback.format_exc()[-1500:]})
            print(f"  {qid} #{반복} {조건} 실패: {e!r}", flush=True)
    return msgs


# ── 요약 ─────────────────────────────────────────────────────────────────────

def _통계(xs: list) -> dict | None:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"평균": round(statistics.mean(xs), 1), "최소": round(min(xs), 1), "최대": round(max(xs), 1), "n": len(xs)}


def 스위치확인(r: dict) -> list[str]:
    """스위치를 껐다고 로그만 찍고 코드 경로는 그대로인 사고를 기록으로 잡는다."""
    조건, toc = r["실험"]["조건"], (r.get("plan") or {}).get("목차", [])
    bad = []
    if 조건 == "배정끔" and any(t["시작문서"] for t in toc):
        bad.append("배정끔인데 시작 문서가 있다")
    if 조건 == "구역끔" and any(s.get("피하기") for s in r.get("sections", [])):
        bad.append("구역끔인데 피하기 목록이 있다")
    if 조건 == "역할끔" and any(t["역할"] != G.CFG["기본_역할"] for t in toc):
        bad.append("역할끔인데 기본 역할이 아닌 절이 있다")
    if 조건 == "재위임끔" and any(s.get("바퀴", 1) > 1 for s in r.get("sections", [])):
        bad.append("재위임끔인데 2바퀴 원고가 있다")
    if 조건 == "기본" and toc and not any(t["시작문서"] for t in toc):
        bad.append("기본인데 시작 문서가 하나도 없다")
    if r["실험"]["지표지문"] != 지표지문:
        bad.append("지표 규칙이 지금과 다른 버전으로 잰 기록")
    return bad


def 요약(done: dict) -> dict:
    runs = list(done.values())
    for r in runs:                                # 저장된 값을 믿지 않고 지금 규칙으로 다시 잰다
        r["metrics"] = M.재기(r)
    유형 = {qid: q["유형"] for qid, q in G.QUESTIONS.items()}

    def 묶어(filter_) -> dict:
        out = {}
        for 조건 in 조건들:
            rs = [r for r in runs if r["실험"]["조건"] == 조건 and filter_(r)]
            if not rs:
                continue
            out[조건] = {"실행수": len(rs),
                         **{k: _통계([r["metrics"]["신호"][k] for r in rs]) for k in M.신호},
                         "보고서자수": _통계([r["metrics"]["참고"]["보고서자수"] for r in rs]),
                         "LLM호출": _통계([r["metrics"]["참고"]["LLM호출"] for r in rs]),
                         "입력토큰": _통계([r["metrics"]["참고"]["입력토큰"] for r in rs]),
                         "경보합계": {k: sum(r["metrics"]["경보"][k] or 0 for r in rs) for k in M.경보}}
        return out

    # 공정성 점검표 — 팀(기본)과 대조군 짝마다 ②같은 만큼 ③막히지 않았나 ④같은 자
    공정 = []
    for (qid, 반복, 조건), r in sorted(done.items()):
        if 조건 not in 혼자조건:
            continue
        짝 = done.get((qid, 반복, "기본"))
        if not 짝:
            continue
        mt, mb = 짝["metrics"], r["metrics"]
        문제 = []
        if mb["참고"]["읽기횟수"] != mt["참고"]["읽기횟수"]:
            문제.append(f"읽기 건수 다름 {mt['참고']['읽기횟수']}≠{mb['참고']['읽기횟수']}")
        for k in ("예산미사용", "고르기대체", "집필형식문제", "빈절·입력잘림"):
            if mb["경보"][k] or mt["경보"][k]:
                문제.append(f"{k} 팀 {mt['경보'][k]} / 혼자 {mb['경보'][k]}")
        if r["실험"]["지표지문"] != 짝["실험"]["지표지문"]:
            문제.append("지표 규칙 버전이 다름")
        공정.append({"qid": qid, "반복": 반복, "대조군": 조건, "읽기": mb["참고"]["읽기횟수"],
                     "원문글자_팀": sum(c["입력자수"] for c in 짝["calls"] if c["용도"] == "읽기"),
                     "원문글자_혼자": sum(c["입력자수"] for c in r["calls"] if c["용도"] == "읽기"),
                     "문제": 문제})

    흔들림 = {}
    for qid in G.QUESTIONS:
        for 조건 in 조건들:
            xs = [done[(qid, k, 조건)]["metrics"]["신호"]["근거율"] for k in range(1, 반복수 + 1) if (qid, k, 조건) in done]
            if len(xs) >= 2:
                흔들림.setdefault(qid, {})[조건] = round(max(xs) - min(xs), 1)

    재위임 = {}
    for 조건 in 조건들:
        rs = [r for r in runs if r["실험"]["조건"] == 조건 and r.get("sections")]
        if not rs:
            continue
        출처 = {}
        for r in rs:
            for sec in r["sections"]:
                if not sec.get("충분", True):
                    k = (sec.get("부족_출처") or "자기신고").split(" ")[0]
                    출처[k] = 출처.get(k, 0) + 1
        판정 = [x["결과"] for r in rs for x in r.get("원고판정", [])]
        재위임[조건] = {"재위임_일어난_실행": sum(1 for r in rs if any(s.get("바퀴", 1) > 1 for s in r["sections"])),
                        "실행수": len(rs), "부족_신고_출처": 출처,
                        "재위임본_채택": 판정.count("채택"), "재위임본_기각": 판정.count("기각")}

    return {"생성": datetime.now().isoformat(timespec="seconds"), "지표지문": 지표지문, "실행수": len(runs),
            "재위임": 재위임,
            "조건별": 묶어(lambda r: True),
            "유형별": {u: 묶어(lambda r, u=u: 유형.get(r["실험"]["qid"]) == u) for u in dict.fromkeys(유형.values())},
            "질문별": {qid: 묶어(lambda r, qid=qid: r["실험"]["qid"] == qid) for qid in G.QUESTIONS},
            "근거율_흔들림(최대-최소)": 흔들림,
            "공정성점검": {"짝수": len(공정), "문제있는짝": [x for x in 공정 if x["문제"]], "전체": 공정},
            "스위치확인": {f"{r['실험']['qid']}#{r['실험']['반복']} {r['실험']['조건']}": b
                           for r in runs if (b := 스위치확인(r))}}


def 표(summary: dict) -> str:
    rows = [f"{'조건':<8} {'n':>3} {'근거율':>14} {'편중':>14} {'중복':>6} {'안씀':>6} {'격리':>6} {'자수':>6}  경보"]
    for 조건, v in summary["조건별"].items():
        def c(k, w=14):
            s = v.get(k)
            if not s:
                return f"{'-':>{w}}"
            return f"{s['평균']:5.1f} ({s['최소']:.0f}~{s['최대']:.0f})" if w == 14 else f"{s['평균']:6.1f}"
        울림 = ", ".join(f"{k} {n}" for k, n in v["경보합계"].items() if n) or "없음"
        rows.append(f"{조건:<8} {v['실행수']:>3} {c('근거율')} {c('인용편중')} {c('중복읽기율', 6)} {c('읽고안쓴비율', 6)} "
                    f"{c('격리율', 6)} {c('보고서자수', 6)}  {울림}")
    return "\n".join(rows)


def main():
    ap = argparse.ArgumentParser(description="절제 실험")
    ap.add_argument("--only", nargs="*", help="질문 ID 일부만")
    ap.add_argument("--workers", type=int, default=3, help="동시에 도는 (질문, 반복) 묶음 수")
    ap.add_argument("--summary", action="store_true", help="새로 돌리지 않고 요약만")
    ap.add_argument("--exp", type=int, default=1, help="1: 조건 7가지 · 2: 코드 판정을 더한 재위임 켜고 끔")
    a = ap.parse_args()
    if a.exp == 2:
        global RUNS, ERRS, SUMMARY, REPORTS, 팀조건, 혼자조건, 조건들
        RUNS, ERRS = G.OUT / "ablation2_runs.jsonl", G.OUT / "ablation2_errors.jsonl"
        SUMMARY, REPORTS = G.OUT / "ablation2.json", G.OUT / "reports" / "ablation2"
        팀조건, 혼자조건 = dict(실험2), {}
        조건들 = list(팀조건)
    done = 불러오기()
    qids = a.only or list(G.QUESTIONS)
    if not a.summary:
        할일 = [(q, k) for q in qids for k in range(1, 반복수 + 1)
                if any((q, k, c) not in done for c in 조건들)]
        남은칸 = sum(1 for q, k in 할일 for c in 조건들 if (q, k, c) not in done)
        print(f"■ 절제 실험 — 이미 {len(done)}칸 끝남 · 남은 {남은칸}칸 ({len(할일)}묶음) · 동시 {a.workers}묶음 · 지표지문 {지표지문}", flush=True)
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = [ex.submit(한묶음, q, k, done) for q, k in 할일]
            for _ in as_completed(futs):
                pass
        print(f"■ {'멈춤' if _멈춤.is_set() else '끝'} — {(time.time() - t0) / 60:.1f}분", flush=True)
    s = 요약(불러오기())
    SUMMARY.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n" + 표(s))
    p = s["공정성점검"]
    print(f"\n공정성 점검: 짝 {p['짝수']}개 중 문제 있는 짝 {len(p['문제있는짝'])}개")
    for x in p["문제있는짝"][:10]:
        print(f"   {x['qid']}#{x['반복']} {x['대조군']}: {'; '.join(x['문제'])}")
    print(f"스위치 확인: 어긋난 기록 {len(s['스위치확인'])}건", *(f"\n   {k}: {v}" for k, v in list(s["스위치확인"].items())[:10]))
    if ERRS.exists():
        print(f"실패 기록: {ERRS} — 다시 실행하면 그 칸만 다시 돈다")
    print(f"저장: {SUMMARY}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
