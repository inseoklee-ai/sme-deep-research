"""웹 데모 — 질문을 넣으면 팀이 나눠 읽고 써 온 보고서와, 절마다 누가 무엇을 읽고 무엇을 썼는지를 보여 준다.

    streamlit run app.py

API 키 — 보는 사람이 자기 OpenAI 키를 왼쪽에 넣고 돌린다. 키는 그 사람의 세션 메모리에만 있고
(graph.키쓰기 → contextvar), 파일·실행 기록·로그 어디에도 남지 않으며, 다른 방문자의 실행과 섞이지 않는다.
이 PC 에 keys.env / .env 가 있으면 '이 PC 의 키'도 고를 수 있다. '지난 실행 보기' 는 키 없이 된다.

공개 모드 (DEMO_PUBLIC=1 — Streamlit Cloud 에서는 Secrets 에 DEMO_PUBLIC = "1")
  - 주인 키 선택지를 숨긴다 (방문자는 자기 키만)
  - 방문자의 실행을 서버에 저장하지 않는다 (다음 방문자에게 남의 질문·보고서가 보이지 않게)
  - '지난 실행 보기' 에는 저장소에 들어 있는 실험 기록만 보인다
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

import baseline as B   # noqa: E402
import graph as G      # noqa: E402
import metrics as M    # noqa: E402
from compare import 원문대목  # noqa: E402

st.set_page_config(page_title="중소기업 AI 딥리서처", page_icon="🔎", layout="wide")

지표설명 = {
    "근거율": "인용이 붙은 문장 ÷ 전체 문장 (# 머리글 줄 제외) — 집필·예산·재위임",
    "인용편중": "가장 많이 인용된 문서 ÷ 전체 인용 — 배정·구역 (낮을수록 고르게)",
    "중복읽기율": "두 절 이상이 읽은 문서 ÷ 읽은 문서 — 구역 (팀 전용)",
    "읽고안쓴비율": "읽었지만 인용하지 않은 문서 ÷ 읽은 문서 — 탐색·배정 품질",
    "격리율": "코디네이터·편집자가 본 글자 ÷ 전체가 본 글자 — 격리 설계",
}


# ── 키 ───────────────────────────────────────────────────────────────────────

내키 = "내 OpenAI API 키 입력"
PC키 = "이 PC 의 keys.env 키"
공개 = os.getenv("DEMO_PUBLIC") == "1" or os.getenv("DEMO_HIDE_LOCAL_KEY") == "1"


def 키고르기() -> str | None:
    """왼쪽 패널의 키 칸. 실행에 쓸 키를 돌려준다(없으면 None). 키 자체는 화면에 다시 보이지 않는다."""
    선택지 = [내키]
    if G.파일키() and not 공개:
        선택지.append(PC키)
    방식 = st.radio("API 키", 선택지, help="보는 사람이 자기 키로 돌린다. 비용은 그 키의 계정에 청구된다.")
    if 방식 == PC키:
        st.caption("이 PC 의 keys.env / .env 에 있는 키를 쓴다 (주인 계정에 청구).")
        return G.파일키()
    key = st.text_input("OpenAI API 키", type="password", placeholder="sk-...", key="방문자키",
                        help="이 브라우저 세션의 메모리에만 있고, 파일·기록·로그에 남지 않는다. 탭을 닫으면 사라진다.")
    if key:
        지문 = hash(key)
        if st.session_state.get("키확인_지문") != 지문:   # 키가 바뀌면 확인 결과를 지운다
            st.session_state.pop("키확인", None)
        if st.button("키 확인", help="모델 목록만 조회한다 — 토큰을 쓰지 않는다"):
            st.session_state["키확인"] = G.키확인(key)
            st.session_state["키확인_지문"] = 지문
        if "키확인" in st.session_state:
            ok, msg = st.session_state["키확인"]
            (st.success if ok else st.error)(msg)
    st.caption("💡 한 번 조사에 약 1~2센트(gpt-4o-mini), 대조군 비교를 켜면 약 2배. "
               "OpenAI 대시보드에서 사용 한도를 걸어 두기를 권한다.")
    return key.strip() or None


# ── 보여 주기 ────────────────────────────────────────────────────────────────

def 지표판(rec: dict, 좁게: bool = False):
    m = M.재기(rec)
    if 좁게:                                      # 나란히 볼 때는 칸이 좁아 숫자가 잘린다 — 표 한 줄로
        st.dataframe([{k: ("-" if v is None else f"{v}%") for k, v in m["신호"].items()}], hide_index=True)
    else:
        cols = st.columns(5)
        for col, (k, v) in zip(cols, m["신호"].items()):
            col.metric(k, "-" if v is None else f"{v}%", help=지표설명[k])
    울림 = {k: v for k, v in m["경보"].items() if v}
    if 울림:
        st.warning("경보 (0 이어야 한다): " + " · ".join(f"{k} {v}" for k, v in 울림.items())
                   + (f" — {m['경보목록']}" if m["경보목록"] else ""))
    else:
        st.success("경보 없음 — 지어낸 제목·안 읽은 문서 인용·절 밖 인용·예산 미사용·고르기 대체·형식 문제 모두 0")
    r = m["참고"]
    st.caption(f"문장 {r['문장수']} · 인용 {r['인용수']}곳({r['인용문서수']}개 문서) · 읽기 {r['읽기횟수']}회 · "
               f"보고서 {r['보고서자수']:,}자 · LLM {r['LLM호출']}회 · 토큰 {r['입력토큰']:,}+{r['출력토큰']:,} · {r['초']}초")


def 절보기(rec: dict):
    """과제의 요점 — 절마다 누가, 무엇을 읽고, 무엇을 썼는가."""
    채택 = {int(k): v for k, v in rec.get("채택", {}).items()}
    판정 = {(x["번호"], x["바퀴"]): x for x in rec.get("원고판정", [])}
    for sec in sorted(rec["sections"], key=lambda s: (s["번호"], s.get("바퀴", 1))):
        바퀴 = sec.get("바퀴", 1)
        채택됨 = 채택.get(sec["번호"]) == 바퀴
        표시 = "✅ 최종본" if 채택됨 else "↩︎ 최종본 아님"
        if 바퀴 > 1:
            x = 판정.get((sec["번호"], 바퀴), {})
            표시 += f" · 재위임본 {x.get('결과', '')} (근거 문장 {x.get('근거문장', '')})"
        신고 = "충분" if sec["충분"] else f"부족 — {sec['부족']} [{sec.get('부족_출처') or '자기신고'}]"
        with st.expander(f"{sec['번호'] + 1}. {sec['절']} · {sec['역할']} · {바퀴}바퀴 · {표시}", expanded=(바퀴 == 1)):
            c1, c2 = st.columns([1, 2])
            with c1:
                st.markdown(f"**지시** {sec['지시']}")
                st.markdown(f"**시작 문서** «{sec['시작문서'] or '자율'}» · **예산** {sec['예산']}건")
                st.markdown(f"**피하기(남의 구역)** {', '.join(sec.get('피하기', [])) or '없음'}")
                st.markdown("**읽은 순서** " + " → ".join(
                    f"**«{d}»**" if d in sec.get("새로읽음", []) else f"«{d}»" for d in sec["읽은문서"]))
                st.markdown(f"**자기신고** {신고}")
                st.caption(f"인용 {len(sec['인용'])}곳 · 근거 문장 {sec.get('근거문장수', 0)} · 허위 인용 {len(sec['허위인용'])}")
            with c2:
                st.markdown("**조사관이 쓴 원고** (편집자는 고치지 않는다)")
                st.markdown(sec["본문"])
                st.markdown("**조사관이 받은 메모** — 원문은 여기까지만 올라온다")
                for d, memo in sec.get("메모", []):
                    st.markdown(f"- «{d}» {memo}")


def 기획보기(rec: dict):
    p = rec.get("plan") or {}
    if not p:
        st.info("대조군 — 기획 없이 혼자 고르고 읽었다. 읽은 순서: " + " → ".join(d for _, d in rec["visited"]))
        return
    st.markdown(f"**보고서 제목** {p.get('제목')}")
    if p.get("대상후보"):
        st.markdown("**1단계 — 코디네이터가 뽑은 대상** (★ 필수 → 코드가 이것만 절로 삼는다)")
        st.dataframe([{"필수": "★" if c["필수"] else "", "대상": c["이름"], "카드": ", ".join(c["카드"]),
                       "이유": c["이유"]} for c in p["대상후보"]], hide_index=True, width="stretch")
    st.markdown("**2단계 — 목차와 배정**")
    st.dataframe([{"절": t["절"], "역할": t["역할"], "시작 문서": t["시작문서"] or "자율", "예산": t["예산"],
                   "지시": t["지시"]} for t in p.get("목차", [])], hide_index=True, width="stretch")
    if p.get("교정"):
        st.markdown("**코드가 바로잡은 것** — 모델이 지어낸 제목·겹친 배정·명단에 없는 역할")
        st.dataframe(p["교정"], hide_index=True, width="stretch")
    st.caption(f"종료 사유: {p.get('종료', '-')}")


def 격리보기(rec: dict):
    calls = rec["calls"]
    위 = sum(c["입력자수"] for c in calls if c["누가"] in ("코디네이터", "편집자"))
    아래 = sum(c["입력자수"] for c in calls if c["누가"] == "조사관")
    c1, c2, c3 = st.columns(3)
    c1.metric("코디네이터·편집자가 본 글자", f"{위:,}")
    c2.metric("조사관이 본 글자", f"{아래:,}")
    c3.metric("격리율", f"{100 * 위 / max(위 + 아래, 1):.1f}%")
    st.bar_chart({"본 글자 수": {"코디네이터·편집자": 위, "조사관": 아래}}, horizontal=True)
    st.markdown("**LLM 호출 전체**")
    st.dataframe([{"누가": c["누가"], "용도": c["용도"], "입력 글자": c["입력자수"], "입력 토큰": c.get("입력토큰", 0),
                   "출력 토큰": c.get("출력토큰", 0), "초": c.get("초", 0), "대체": "⚠" if c.get("대체") else "",
                   "답(앞부분)": (c.get("답") or "")[:80]} for c in calls], hide_index=True, width="stretch")


def 인용보기(rec: dict, 최대: int = 40):
    st.caption("보고서 문장 ↔ 인용 ↔ 조사관이 받은 메모 ↔ 원문에서 낱말이 가장 많이 겹치는 대목. "
               "'읽지 않은 문서 인용'은 코드가 잡지만, 읽은 문서를 엉뚱한 문장에 붙인 것은 사람이 이 표로 잡는다.")
    메모 = {}
    for s in M.채택된절(rec):
        for d, m in s.get("메모", []):
            메모.setdefault(d, m)
    for d, m in rec.get("메모", []):
        메모.setdefault(d, m)
    rows = []
    for 문 in M.본문문장(rec["report"]):
        for c in dict.fromkeys(G.인용들(문)):
            rows.append({"문장": 문[:160], "인용": c, "받은 메모": (메모.get(c) or "(메모 없음)")[:200],
                         "원문 대목": 원문대목(c, 문, 220) if c in G.DOCS else "⚠ 코퍼스에 없는 제목"})
            if len(rows) >= 최대:
                break
    st.dataframe(rows, hide_index=True, width="stretch", height=520)


def 한편보기(rec: dict, 짝: dict | None = None):
    tabs = st.tabs(["① 보고서", "② 누가 무엇을 읽고 썼나", "③ 기획", "④ 격리", "⑤ 인용 확인"]
                   + (["⑥ 혼자와 비교"] if 짝 else []))
    with tabs[0]:
        지표판(rec)
        st.divider()
        st.markdown(rec["report"])
    with tabs[1]:
        if rec.get("sections"):
            절보기(rec)
        else:
            st.info("대조군은 절을 나누지 않는다 — 혼자 읽은 메모:")
            for d, m in rec.get("메모", []):
                st.markdown(f"- «{d}» {m}")
    with tabs[2]:
        기획보기(rec)
    with tabs[3]:
        격리보기(rec)
    with tabs[4]:
        인용보기(rec)
    if 짝:
        with tabs[5]:
            st.caption(f"대조군은 같은 모델·같은 카드·같은 도구로, 팀이 실제로 읽은 {짝['예산']}건만큼 읽었다. "
                       "지표는 명백한 실패를 거르는 데만 쓴다 — 어느 쪽이 나은지는 읽고 판단한다.")
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("팀")
                지표판(rec, 좁게=True)
                st.markdown(rec["report"].replace("\n# ", "\n### ").replace("# ", "### ", 1))
            with c2:
                st.subheader(짝.get("라벨", "혼자"))
                지표판(짝, 좁게=True)
                st.markdown(짝["report"].replace("\n# ", "\n### ").replace("# ", "### ", 1))


# ── 지난 실행 ────────────────────────────────────────────────────────────────

@st.cache_data
def 지난실행() -> list[dict]:
    out = []
    for name, path in (("실험 1", G.OUT / "ablation_runs.jsonl"), ("실험 2", G.OUT / "ablation2_runs.jsonl"),
                       *([] if 공개 else [("직접 실행", G.OUT / "runs.jsonl")])):
        if path.exists():
            for r in M.불러오기(path):
                e = r.get("실험") or {}
                r["_이름"] = (f"{name} · {e.get('qid') or r.get('qid')} #{e.get('반복', '')} · {e.get('조건') or r.get('라벨')}"
                             f" · {r.get('run_id')}")
                out.append(r)
    return out


# ── 화면 ─────────────────────────────────────────────────────────────────────

st.title("🔎 중소기업 AI·디지털 전환 딥리서처")
st.caption("코디네이터가 목차를 짜서 조사관들에게 절을 나눠 맡기고, 조사관들은 동시에 각자 문서를 골라 읽고 자기 절을 쓴다. "
           f"코퍼스: 위키백과 {len(G.DOCS)}건(한국어·영어) · {sum(len(v) for v in G.DOCS.values()):,}자 — 모델 창(12.8만 토큰)을 넘는다.")
if 공개:
    st.caption("🔒 공개 데모 — 자신의 OpenAI 키로 돌립니다. 넣은 키와 질문·결과는 서버에 저장되지 않고 다른 방문자에게 보이지 않습니다. "
               "[코드와 보고서](https://github.com/inseoklee-ai/sme-deep-research)")

with st.sidebar:
    모드 = st.radio("모드", ["새로 질문하기", "지난 실행 보기 (키 불필요)"])
    st.divider()
    if 모드 == "새로 질문하기":
        쓸키 = 키고르기()
        st.divider()
        st.subheader("설정")
        절수 = st.slider("절 수 상한", 1, 6, G.CFG["절수"])
        절예산 = st.slider("절당 읽기 예산", 1, 5, G.CFG["절예산"])
        st.markdown("**스위치** — 하나씩 꺼 보며 무엇이 값을 하는지 본다")
        sw = {k: st.checkbox(k, value=v, help={"역할": "끄면 모두 같은 범용 조사관",
                                                "배정": "끄면 시작 문서를 나눠 주지 않는다",
                                                "구역": "끄면 남의 구역을 피하지 않는다",
                                                "재위임": "끄면 한 바퀴로 끝낸다"}[k])
              for k, v in G.CFG["스위치"].items()}
        부족 = st.selectbox("부족 판정", ["자기신고+코드", "자기신고"],
                            index=0 if G.CFG["부족_판정"] == "자기신고+코드" else 1,
                            help="실험 1 에서 자기신고는 한 번도 '부족'을 말하지 않았다 — 코드 판정을 더하면 재위임이 돈다")
        비교 = st.checkbox("혼자 하는 대조군과 비교", value=False, help="팀이 실제로 읽은 건수만큼 읽는다 — 비용이 약 2배")
        스스로 = st.checkbox("대조군도 문서마다 찾을 것을 스스로 정함 (나)", value=True, disabled=not 비교)

if 모드 == "새로 질문하기":
    qs = G.QUESTIONS
    골라 = st.selectbox("예시 질문 (고르거나 아래에 직접 쓴다)", ["(직접 쓰기)"] + list(qs),
                        format_func=lambda k: k if k == "(직접 쓰기)" else f"{k} · {qs[k]['유형']} · {qs[k]['질문']}")
    if 골라 != "(직접 쓰기)":
        st.caption(f"왜 나눌 만한가: {qs[골라]['왜 나눌 만한가']}")
    질문 = st.text_area("질문", value="" if 골라 == "(직접 쓰기)" else qs[골라]["질문"], height=80)
    if not 쓸키:
        st.info("👈 왼쪽에 자신의 OpenAI API 키를 넣으면 조사를 시작할 수 있습니다. 키 없이는 '지난 실행 보기'로 실험 기록을 둘러볼 수 있습니다.")
    if st.button("조사 시작", type="primary", disabled=not (질문.strip() and 쓸키)):
        덮어쓸 = {"절수": 절수, "절예산": 절예산, "부족_판정": 부족, **sw}
        토큰 = G.키쓰기(쓸키)                     # 이 세션의 실행에만 이 키를 쓴다 (병렬 노드까지 전달)
        try:
            with st.status("팀이 조사 중 — 기획 → 배치 → 조사관 동시 파견 → 점검 → 종합", expanded=True) as box:
                rec = G.run(질문.strip(), 덮어쓸, qid=None if 골라 == "(직접 쓰기)" else 골라, 라벨="데모",
                            save=not 공개, verbose=False, on_log=lambda line: box.write(f"`{line}`"))
                box.update(label=f"끝 — {rec['초']}초 · LLM {len(rec['calls'])}회", state="complete", expanded=False)
            짝 = None
            if 비교:
                with st.spinner(f"대조군이 혼자 {rec['metrics']['참고']['읽기횟수']}건을 읽는 중…"):
                    짝 = B.혼자(질문.strip(), rec["metrics"]["참고"]["읽기횟수"], qid=rec["qid"],
                               라벨="혼자(나)" if 스스로 else "혼자(가)", 스스로지시=스스로, verbose=False)
            st.session_state["결과"] = (rec, 짝)
        except G.잔액소진:
            st.error("이 키의 잔액이 소진됐습니다 — OpenAI 대시보드에서 결제·한도를 확인하거나 다른 키를 넣어 주세요.")
        except Exception as e:                    # 실패는 화면까지 올린다 — 다만 키로 보이는 문자열은 가린다
            msg = re.sub(r"sk-[A-Za-z0-9_\-*]{4,}", "sk-…(가림)", str(e))
            st.error(f"실행 실패 — {type(e).__name__}: {msg[:500]}")
        finally:
            G._세션키.reset(토큰)                  # 이 세션의 키를 실행이 끝나면 내려놓는다
    if "결과" in st.session_state:
        한편보기(*st.session_state["결과"])
else:
    runs = 지난실행()
    if not runs:
        st.info("아직 기록이 없습니다 — ablation.py 나 '새로 질문하기' 로 만들 수 있습니다.")
    else:
        qids = sorted({(r.get("실험") or {}).get("qid") or r.get("qid") or "직접" for r in runs})
        q = st.selectbox("질문", qids, format_func=lambda k: f"{k} · {G.QUESTIONS[k]['질문']}" if k in G.QUESTIONS else k)
        후보 = [r for r in runs if ((r.get("실험") or {}).get("qid") or r.get("qid") or "직접") == q]
        골 = st.selectbox("실행", range(len(후보)), format_func=lambda i: 후보[i]["_이름"])
        rec = 후보[골]
        e = rec.get("실험") or {}
        짝 = next((r for r in runs if r.get("run_id") == rec.get("짝_run_id")), None) if rec.get("짝_run_id") else None
        if not rec.get("sections") and 짝:        # 대조군을 골랐으면 팀(짝)을 앞에, 대조군을 비교 칸에
            rec, 짝 = 짝, rec
        elif rec.get("sections") and e.get("조건") == "기본":
            짝 = next((r for r in runs if r.get("짝_run_id") == rec.get("run_id")
                       and (r.get("실험") or {}).get("조건") == "혼자(나)"), None)
        st.caption(f"설정: {json.dumps(rec.get('설정', {}), ensure_ascii=False)}")
        한편보기(rec, 짝)
