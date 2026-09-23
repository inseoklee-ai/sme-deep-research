# HANDOFF — 중소기업 AI·디지털 전환 딥리서처 (2026-09-23)

다른 세션에서 이어받을 때 먼저 읽는 문서다. 오늘 한 일, 내린 결정, 알아낸 것, 조심할 것, 남은 일을 정리했다.
과제 규정은 [ASSIGNMENT.md](ASSIGNMENT.md), 설계·실험·회고 전체는 [REPORT.md](REPORT.md) 에 있다.

## 무엇을 만들었나

모두의연구소(AIFFEL) 「딥리서치 에이전트 오케스트레이션」 실습 과제. 전날 배운 수업 프로젝트
(`C:\Users\lis29\projects\deep-research-orchestrator` — 한국 근대사 34건, 노드 6개)를 바탕으로,
**본업 도메인(SME AI 주치의)을 주제로 나만의 딥리서처**를 만들었다.

- 코디네이터가 목차를 짜서 절마다 조사관을 배정 → 조사관 N명이 동시에 각자 문서를 골라 읽고 절을 씀 →
  부족한 절만 재위임 → 편집자가 이어 붙임 → 정답표 없는 지표로 재고, 스위치를 하나씩 꺼서 무엇이 값을 했는지 가림
- **제출 주소**: https://github.com/inseoklee-ai/sme-deep-research (public, main)
- **라이브 데모**: https://sme-deep-research-52pwp9cxzm7krbu7je4jcz.streamlit.app/ (Streamlit Community Cloud, 공개 모드)

**진행 방식** — 사용자가 단계마다 설명을 듣고 **승인한 뒤에만** 다음 단계로 넘어갔다. 과제가 "직접 할 것"으로
정한 세 가지(무엇을 절로 나눌지 · 대조군이 공정한지 · 결과를 의심하기)는 진행 전에 협의해서 정했다.
**설명·자료는 한글 기본, 영어는 필요할 때만 괄호 안에** (사용자가 두 번 지적했다).

## 환경

| 항목 | 값 |
|---|---|
| 프로젝트 폴더 | `C:\Users\lis29\projects\sme-deep-research` |
| Python | 3.12, 가상환경 `.venv\` |
| 패키지 | `requirements.txt` — 깨끗한 환경에서 시험 통과한 판으로 고정 (streamlit 1.64.0 · langgraph 1.2.12 · langchain-openai 1.6.4 · openai 3.19.0) |
| 모델 | OpenAI `gpt-4o-mini`, temperature 0 |
| 키 (명령줄) | `C:\Users\lis29\projects\keys.env` 의 `OPENAI_API_KEY` (또는 프로젝트 `.env`). 둘 다 `.gitignore` |
| 키 (데모) | 방문자가 화면에 자기 키를 넣는다 — 세션(contextvar)에만 있고 파일·기록에 안 남음 |
| GitHub | 계정 `inseoklee-ai`, `gh` 로그인되어 있음 |
| 화면 캡처 | `scripts/screenshots.py` — playwright 로 이 PC 의 Edge 사용 (`.venv` 에 playwright 설치됨, requirements 에는 없음) |

## 자주 쓰는 명령

```bash
.venv\Scripts\python graph.py M2
```

```bash
.venv\Scripts\python -m streamlit run app.py
```

```bash
.venv\Scripts\python metrics.py --test
```

| 명령 | 하는 일 |
|---|---|
| `graph.py M2 [--set 재위임=false]` | 팀 한 번 실행 (질문 ID 또는 문장) → `output/runs.jsonl` · `output/reports/` |
| `baseline.py M2 --budget 9 [--self-brief]` | 혼자 하는 대조군 |
| `ablation.py [--exp 2] [--summary]` | 실험 1(231회) / 실험 2(66회). **끊기면 같은 명령으로 이어서 돈다** |
| `metrics.py [파일] [--test]` | 기록 다시 재기 (키 불필요) |
| `scripts/compare.py M1` | 나란히 읽기 자료 → `output/compare/` |
| `scripts/collect_corpus.py` | 코퍼스 다시 모으기 (`cache/` 있으면 위키 호출 없음) |
| `scripts/screenshots.py [--live S2]` | 데모 화면 캡처 → `docs/screenshots/` (데모가 떠 있어야 함) |

## 파일 지도

```
data/corpus.json        위키백과 45건(ko 12 · en 33) · 891,738자 · links 247 · lang
data/questions.json     질문 11건 (S1~S3 한 건 · M1~M5 여러 갈래 · T1~T3 한 대상 추적) + "왜 나눌 만한가"
config.json             절수 4 · 절예산 3(최대 5) · 바퀴 상한 2 · 역할 명단 6 · 스위치 4 · 부족_판정 "자기신고+코드"
graph.py                기획 → 배치 → 조사관 → 점검 → 종합. 공용 도구(ask·고르기·문장조립·문장건지기·키쓰기 …)
metrics.py              신호 5 · 경보 7. 문장 분리는 graph.문장들 하나만
baseline.py             혼자(가)·(나) — 팀 함수를 그대로 가져다 쓴다
ablation.py             실험 1 · 2, 공정성 점검표, 스위치 확인, 지표 지문
app.py                  Streamlit 데모 (공개 모드 DEMO_PUBLIC)
scripts/                collect_corpus · compare · screenshots · archive/(폐기한 한국어 v1)
output/ablation_runs.jsonl · ablation.json      실험 1 기록·요약
output/ablation2_runs.jsonl · ablation2.json    실험 2 기록·요약
output/compare/         M1_1 · T1_1 · S3_1 · S1_1 나란히 읽기 자료
output/dev/             개발 중 버그가 있던 실행 기록 — 증거로 보관 (REPORT 9장이 가리킨다)
docs/screenshots/       README·REPORT 캡처 13장
ASSIGNMENT.md · README.md · REPORT.md · DEPLOY.md · HANDOFF.md
```

## 오늘 한 일 (순서대로)

| 단계 | 한 일 | 커밋 |
|---|---|---|
| 주제 | 후보 넷(SME AI 도입 · 계란 파동사 · AI 생태계 · 메모리얼 캔버스 시대 배경) 중 **SME AI 도입** 선택 | – |
| 0 코퍼스 | 한국어 v1 폐기(AI 철학으로 흐름) → 한·영 v2 → 넓은 문서 제외 · 45건 상한 · 로봇공학 시드 고정 v3. 동점 순서 비결정성 수정 | `f1e5a3d` |
| 1 질문 | 11건, 절의 축 = 대상 단위(관점은 역할로), 역할 명단 6 | `4e04309` |
| 2 그래프 | 수업 노드를 스크립트로 옮기며 설정을 State 에, 호출 기록 리듀서, 코디네이터 예산 배분, 배정 검사, 근거비교 원고 정책. 인용 형식·예산·인용 위치·부족 오신고 수정. 기획을 **두 단계 + 코드 절 구성**으로 | `4e04309` `837692f` |
| 3 지표 | 신호 5 · 경보 7, 옛 기록으로 계기판 검증, 수업 코드의 숨은 문제 2개 수정 | `5f13742` |
| 4 실험 | 대조군 (가)·(나), 공정성 잣대 5가지, 실험 1(231회) · 실험 2(재위임, 66회), 나란히 읽기 자료 | `3e8b329` `342f4a6` |
| 5 데모 | Streamlit 탭 6개, 지난 실행 보기, README·캡처 | `1eb936d` |
| REPORT | 12장 구성, 8장(직접 판단)·11장(회고)은 AI 초안 → 사용자 검토 후 초안 표시 제거 | `34930ee` `1d63584` |
| 배포 | 방문자 자기 키(세션 격리), 공개 모드, 판 고정, DEPLOY.md, Streamlit Cloud 배포·점검 | `f1d4d50` `dbba1c6` `f9cae7e` `7adb46f` |

## 사용자가 내린 결정

- 주제: **SME AI 도입** (본업). 코퍼스는 **한·영 위키 혼합(A안)**, 로봇공학 시드 고정
- 절의 축: **대상 단위, 관점은 역할로**. 질문 11건·역할 6개 그대로 승인
- 두 번째 원고: **근거비교**(허위 인용 없고 근거 문장이 줄지 않을 때만 채택)
- 목차: 프롬프트 보강(A) → 한 번 더 → 두 단계 기획으로
- 지표: 신호 5 · 경보 7, 근거율 분모는 `#` 머리글만 빼고 머리말·맺음말은 남김, 절 밖 인용 경보 포함
- 대조군: 짝 맞춤 예산, 같은 카드·도구·집필 형식, 읽기 지시 **(다) 둘 다** 돌림. 공정성 잣대 5가지 확정
- 실험 규모: **전체 A(231회)**, 비용 상한 없음(끊기면 키를 바꿔 이어서)
- 재위임: 실험 1 에서 0회 발동 → **(b) 코드 판정 추가**, 기본값을 `자기신고+코드` 로
- 요약 단계의 빈칸 채우기 문제는 **지금 고치지 않고 개선점으로** 남김 (고치면 실험 결과와 코드 판이 달라진다)
- REPORT 는 AI 가 먼저 채우고 사용자가 검토 → 초안 표시 제거(나)
- GitHub **public** `sme-deep-research`, Streamlit Cloud 배포

## 알아낸 것 (REPORT 에 자세히)

| 장치 | 결과 |
|---|---|
| 나눠 맡기기 | ✅ 팀 근거율 80.1 대 혼자 64.8/63.7, 짝 30~32/33 우세, 보고서 약 2배 |
| 배정·구역 | ✅ 끄면 중복 읽기 4→31%, 편중 30→38. 근거율은 그대로 |
| 역할 | ❌ 차이 없음 |
| 재위임(자기신고) | ❌ 약 200개 절에서 '부족' 0회 |
| 재위임(코드 판정) | △ 11/33 발동, 절 수준 개선, 보고서 수준 차이 없음 |
| 흔들림 | 3회 평균끼리도 8%p 는 우연 (실험 2 T1) |

**실패 추적 3건** — ① M1 「중소기업」 절의 원문에 없는 문장은 **요약(`read_one`) 단계**에서 생겼다 ② T1 에 센서·IIoT 가 없는 건 코디네이터가 "Internet of Things" 처럼 **영어 제목**을 적어 한국어 문서(«사물인터넷»)가 배정 검사에서 빠졌기 때문 ③ M4 는 세 번 다 같은 목차로 텔레매틱스·차량 관리가 한 번도 안 뽑혔다.

## 조심할 것 (오늘 실제로 걸린 것)

- **Python 문자열 치환 패치가 두 번 깨졌다.** heredoc 안의 `\n` 이 실제 줄바꿈으로 바뀌거나 치환 대상이 안 맞았다. 한 번은 패치가 실패했는데 **다음 줄 명령이 이어서 실행**돼 이전 판으로 실험이 5회 더 돌았다. → 코드 수정은 **Edit 도구**로, 큰 함수 교체는 **스크래치 파일에 써서 붙이기**. 명령을 `&&` 로 묶어 실패하면 멈추게.
- **Windows 경로 길이** — 스크래치 폴더 아래에 git clone 하면 "Filename too long". 짧은 임시 경로(`C:\Users\lis29\AppData\Local\Temp\...`)를 쓴다.
- **위키백과 API 429** — 호출 사이 1초, `Retry-After` 존중, `cache/` 에 응답 저장.
- **Streamlit Cloud 화면 점검** — 앱이 iframe 안이라 바깥 페이지에서 클릭·검색이 안 된다. `https://<앱주소>/~/+/` 로 직접 열면 된다.
- **Streamlit Cloud Secrets** — 채팅에서 복사하면 둥근 따옴표가 되어 "Invalid TOML". `DEMO_PUBLIC = 1` 을 직접 친다. **Secrets 에 `OPENAI_API_KEY` 를 넣지 않는다**(주인 키가 노출될 수 있다). 배포 폼은 파일 URL 을 요구한다 — `https://github.com/inseoklee-ai/sme-deep-research/blob/main/app.py`.
- **push 는 매번 사용자에게 확인**받고 했다. push 전에 전체 기록에서 키 패턴을 검사했다(통과).
- `requirements.txt` 판을 올리면 `use_container_width` 같은 제거 예정 옵션이 깨질 수 있다 — 올린 뒤 깨끗한 환경에서 `streamlit.testing.v1.AppTest` 로 시험.

## 비용

실험 1 약 2.20달러 · 실험 2 약 0.69달러 · 개발·데모 약 0.41달러 — **합계 약 3.3달러** (gpt-4o-mini 가격표 기준 추정).

## 남은 일

- [ ] **배포된 데모를 사용자 키로 직접 한 번 돌려 보기** — 키 확인 → S1 실행 → 새로 고친 뒤 '지난 실행 보기'에 그 실행이 없는지 확인 (공개 모드는 저장하지 않는다)
- [ ] (선택) REPORT 11장의 개선점 구현 — ① `read_one` 에 "문서에 적힌 것만" 강화 + 근거 대목 대조 ② 배정 검사에서 langlinks 로 한↔영 제목 인정 ③ 인용이 문장을 뒷받침하는지 재는 약한 지표 ④ 한국 중소기업 실태 자료 보강 ⑤ 한 건짜리 질문은 나누지 않는 라우팅 ⑥ M4 같은 대상 선택 반복 실수 줄이기
  - 고치면 실험 결과가 지금 판과 달라지므로, 실험을 다시 돌리고 REPORT 수치를 함께 고쳐야 한다
- [ ] (선택) 블로그 글 — `naver-blog-post-writer` 스킬로 SME 대표 대상 포스팅 초안
