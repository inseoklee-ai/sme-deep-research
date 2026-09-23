"""README 용 화면 캡처 — 떠 있는 데모(localhost:8501)를 이 PC 의 Edge 로 열어 탭마다 찍는다.

    streamlit run app.py                      # 먼저 데모를 띄운다
    python scripts/screenshots.py             # '지난 실행 보기' 화면들 (키·비용 없음)
    python scripts/screenshots.py --live S2   # '새로 질문하기' 로 한 번 실제로 돌려 진행 화면까지 (약 1~2센트)

산출: docs/screenshots/*.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
URL = "http://localhost:8501"
탭 = [("01_report", "① 보고서"), ("02_who_read_what", "② 누가 무엇을 읽고 썼나"), ("03_plan", "③ 기획"),
      ("04_isolation", "④ 격리"), ("05_citations", "⑤ 인용 확인"), ("06_vs_solo", "⑥ 혼자와 비교")]


def 기다림(page, ms=2500):
    page.wait_for_timeout(ms)
    page.wait_for_selector("text=중소기업 AI·디지털 전환 딥리서처", timeout=30000)


def 탭찍기(page, 앞: str = ""):
    for name, label in 탭:
        t = page.get_by_role("tab", name=label)
        if t.count() == 0:
            continue
        t.first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / f"{앞}{name}.png"))
        print("저장", OUT / f"{앞}{name}.png")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", help="이 질문 ID 로 '새로 질문하기' 를 실제로 한 번 돌려 찍는다")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        page.goto(URL)
        기다림(page)
        if a.live:
            page.get_by_text("혼자 하는 대조군과 비교").click()
            page.locator('[data-testid="stSelectbox"]').filter(has_text="예시 질문").locator("input").click()
            page.keyboard.type(a.live)
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            page.get_by_role("button", name="조사 시작").click()
            page.wait_for_timeout(15000)
            page.screenshot(path=str(OUT / "00_live_progress.png"))
            print("저장", OUT / "00_live_progress.png")
            page.get_by_role("tab", name="⑥ 혼자와 비교").wait_for(timeout=240000)
            탭찍기(page, "live_")
        else:
            page.get_by_text("지난 실행 보기 (키 불필요)").click()
            기다림(page, 4000)
            탭찍기(page)
        browser.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
