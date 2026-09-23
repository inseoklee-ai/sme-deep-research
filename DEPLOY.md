# Streamlit Community Cloud 배포 절차

누구나 인터넷 주소로 들어와 **자기 OpenAI API 키를 넣고** 데모를 돌려 볼 수 있게 한다. 방문자의 키로 돌기 때문에 주인에게는 비용이 들지 않는다. Streamlit Community Cloud 는 공개 저장소를 무료로 띄워 준다.

## 배포 전에 이미 갖춰 둔 것

| 항목 | 상태 |
|---|---|
| 공개 저장소 | `inseoklee-ai/sme-deep-research` (main) |
| 실행 파일 | `app.py` |
| 패키지 | `requirements.txt` — 깨끗한 환경에서 `app.py` 를 시험해 통과한 판으로 고정 |
| 실행에 필요한 자료 | `data/` · `config.json` · 실험 기록 `output/ablation_runs.jsonl` · `output/ablation2_runs.jsonl` — 모두 저장소에 있다 |
| 공개 모드 | `DEMO_PUBLIC=1` 이면 ① 주인 키 선택지를 숨기고 ② 방문자 실행을 서버에 저장하지 않고 ③ '지난 실행 보기'에 실험 기록만 보인다 |
| 키 | 방문자 키는 그 사람의 세션에만 있다. 파일·기록·로그에 남지 않고, 동시 방문자끼리 섞이지 않는다 |

## 절차 (약 5분)

1. **https://share.streamlit.io** 에 들어가 **GitHub 계정(inseoklee-ai)으로 로그인**한다. 처음이면 Streamlit 이 GitHub 저장소를 읽을 권한을 묻는다 — 직접 확인하고 허용한다.
2. 오른쪽 위 **Create app** → **Deploy a public app from GitHub** 을 고른다.
3. 칸을 채운다.

   | 칸 | 값 |
   |---|---|
   | Repository | `inseoklee-ai/sme-deep-research` |
   | Branch | `main` |
   | Main file path | `app.py` |
   | App URL | 원하는 주소 (예: `sme-deep-research`) → `https://sme-deep-research.streamlit.app` |

4. **Advanced settings** 를 연다.
   - **Python version**: `3.12` (개발·시험한 판)
   - **Secrets** 칸에 아래 한 줄만 넣는다.

     ```toml
     DEMO_PUBLIC = "1"
     ```

   > ⚠️ **Secrets 에 `OPENAI_API_KEY` 를 넣지 않는다.** 넣으면 '이 PC 의 키' 경로로 주인 키가 쓰일 수 있다. 방문자는 화면에서 자기 키를 넣는다.

5. **Deploy** 를 누른다. 패키지 설치에 2~4분 걸린다.

## 배포 뒤 확인할 것

- [ ] 첫 화면 제목 아래에 **"🔒 공개 데모 — 자신의 OpenAI 키로 돌립니다 …"** 안내가 보인다 (안 보이면 Secrets 의 `DEMO_PUBLIC` 을 확인)
- [ ] 왼쪽 'API 키' 선택지가 **"내 OpenAI API 키 입력" 하나뿐**이다
- [ ] 키를 넣기 전에는 「조사 시작」 버튼이 눌리지 않는다
- [ ] **지난 실행 보기** 에서 질문을 고르면 탭 여섯 개가 모두 뜬다 (키 없이)
- [ ] 자기 키를 넣고 「키 확인」 → "키 확인 — gpt-4o-mini 을 쓸 수 있습니다" → 예시 질문 S1 로 한 번 돌려 본다 (약 1센트)
- [ ] 새로 고친 뒤 '지난 실행 보기'에 방금 돌린 실행이 **보이지 않는다** (공개 모드는 저장하지 않는다)
- [ ] 배포 주소를 README 맨 위에 적는다

## 알아 둘 것

- **잠들기** — 무료 플랜은 한동안 방문이 없으면 앱을 재운다. 오랜만에 열면 "Your app is in the oven / waking up" 화면이 몇 초~몇십 초 뜬다.
- **자동 갱신** — main 에 push 하면 앱이 알아서 다시 배포된다.
- **자원** — 앱당 메모리 약 1GB. 이 데모는 코퍼스 약 1MB, 실험 기록 약 8MB 를 올리므로 여유가 있다.
- **비용 안내** — 화면에 "한 번 조사에 약 1~2센트, 대조군 비교를 켜면 약 2배, OpenAI 대시보드에서 사용 한도를 걸어 두기를 권한다"가 적혀 있다.
- **로컬에서 공개 모드 미리 보기**

  ```bash
  set DEMO_PUBLIC=1 && .venv\Scripts\python -m streamlit run app.py
  ```

- **내리기** — share.streamlit.io 의 앱 목록에서 ⋮ → Delete.
