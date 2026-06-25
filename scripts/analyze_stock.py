"""
KOSPI TOP100 일일 주식 분석 스크립트
- 네이버 금융 API로 주가 데이터 및 뉴스 수집
- Claude API로 블로그용 분석 콘텐츠 생성
- 네이버 블로그 자동 업로드 (Selenium)
- Gmail로 HTML 리포트 이메일 발송
"""

import os
import json
import datetime
import smtplib
import urllib.request
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import anthropic

# 네이버 블로그 자동 업로드 모듈
# NAVER_ID / NAVER_PW 환경변수가 있을 때만 자동 업로드 활성화
BLOG_AUTO_UPLOAD = bool(os.environ.get("NAVER_ID") and os.environ.get("NAVER_PW"))
if BLOG_AUTO_UPLOAD:
    from naver_blog_uploader import post_to_naver_blog

# ──────────────────────────────────────────────
# KOSPI TOP100 종목 리스트 (시가총액 기준 상위 100개)
# 실제 운영 시 네이버 금융에서 주기적으로 갱신 권장
# ──────────────────────────────────────────────
KOSPI_TOP100 = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("207940", "삼성바이오로직스"),
    ("005380", "현대차"),
    ("000270", "기아"),
    ("068270", "셀트리온"),
    ("005490", "POSCO홀딩스"),
    ("035420", "NAVER"),
    ("051910", "LG화학"),
    ("006400", "삼성SDI"),
    ("028260", "삼성물산"),
    ("012330", "현대모비스"),
    ("035720", "카카오"),
    ("096770", "SK이노베이션"),
    ("003550", "LG"),
    ("017670", "SK텔레콤"),
    ("030200", "KT"),
    ("055550", "신한지주"),
    ("105560", "KB금융"),
    ("086790", "하나금융지주"),
    ("316140", "우리금융지주"),
    ("032830", "삼성생명"),
    ("003490", "대한항공"),
    ("011200", "HMM"),
    ("010950", "S-Oil"),
    ("034730", "SK"),
    ("018260", "삼성에스디에스"),
    ("009150", "삼성전기"),
    ("011070", "LG이노텍"),
    ("066570", "LG전자"),
    ("002380", "KCC"),
    ("047050", "포스코인터내셔널"),
    ("010130", "고려아연"),
    ("000100", "유한양행"),
    ("326030", "SK바이오팜"),
    ("091990", "셀트리온헬스케어"),
    ("000720", "현대건설"),
    ("028050", "삼성엔지니어링"),
    ("047040", "대우건설"),
    ("000810", "삼성화재"),
    ("090430", "아모레퍼시픽"),
    ("161490", "롯데케미칼"),
    ("010060", "OCI"),
    ("003670", "포스코퓨처엠"),
    ("373220", "LG에너지솔루션"),
    ("247540", "에코프로비엠"),
    ("086280", "현대글로비스"),
    ("078930", "GS"),
    ("004020", "현대제철"),
    ("011780", "금호석유"),
]  # 상위 50개만 예시 — 필요 시 100개로 확장


def pick_today_stock() -> tuple[str, str]:
    """날짜 기반으로 오늘의 종목 선택 (순환)."""
    day_of_year = datetime.date.today().timetuple().tm_yday
    index = day_of_year % len(KOSPI_TOP100)
    return KOSPI_TOP100[index]


def fetch_stock_price(ticker: str) -> dict:
    """네이버 금융에서 주가 정보 수집."""
    url = f"https://finance.naver.com/item/main.nhn?code={ticker}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 현재가
        price_tag = soup.select_one("p.no_today .blind")
        price = price_tag.text.strip() if price_tag else "N/A"

        # 전일 대비
        change_tag = soup.select_one("p.no_exday .blind")
        change = change_tag.text.strip() if change_tag else "N/A"

        # 등락률
        rate_tag = soup.select_one(".rate_info .no_exday em .blind")
        rate = rate_tag.text.strip() if rate_tag else "N/A"

        return {"price": price, "change": change, "rate": rate}
    except Exception as e:
        print(f"주가 수집 오류: {e}")
        return {"price": "N/A", "change": "N/A", "rate": "N/A"}


def fetch_naver_news(company_name: str, max_articles: int = 8) -> list[dict]:
    """네이버 뉴스 검색 API로 최신 기사 수집."""
    # 네이버 검색 페이지 크롤링 (API 키 없이)
    query = urllib.parse.quote(company_name)
    url = f"https://search.naver.com/search.naver?where=news&query={query}&sort=1&pd=4"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    articles = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for item in soup.select(".news_area")[:max_articles]:
            title_tag = item.select_one(".news_tit")
            desc_tag = item.select_one(".dsc_txt_wrap")
            press_tag = item.select_one(".info_group .press")
            date_tag = item.select_one(".info_group span.info")

            if title_tag:
                articles.append(
                    {
                        "title": title_tag.get("title", title_tag.text).strip(),
                        "description": desc_tag.text.strip() if desc_tag else "",
                        "press": press_tag.text.strip() if press_tag else "",
                        "date": date_tag.text.strip() if date_tag else "",
                    }
                )
    except Exception as e:
        print(f"뉴스 수집 오류: {e}")

    return articles


def analyze_with_claude(
    ticker: str,
    company_name: str,
    price_info: dict,
    news_articles: list[dict],
) -> dict:
    """Claude API로 주식 분석 및 블로그 콘텐츠 생성."""
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url="https://aiprimetech.io",
    )

    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    news_text = "\n".join(
        [
            f"- [{a['press']}] {a['title']}\n  {a['description']}"
            for a in news_articles
        ]
    )

    prompt = f"""당신은 주식 투자 분석 전문가입니다. 아래 데이터를 바탕으로 네이버 블로그에 올릴 수 있는 주식 분석 글을 작성해 주세요.

## 분석 대상
- 종목: {company_name} ({ticker})
- 날짜: {today}
- 현재가: {price_info['price']}원
- 전일 대비: {price_info['change']} ({price_info['rate']})

## 최신 뉴스
{news_text if news_text else "수집된 뉴스 없음"}

---

다음 형식으로 블로그 포스팅을 작성해 주세요. 마크다운 형식으로 작성하되, 네이버 블로그 독자를 대상으로 친근하고 이해하기 쉽게 써주세요.

### 출력 형식

**블로그 제목**: [SEO에 최적화된 클릭률 높은 제목]

**요약 (3줄)**: 핵심 내용을 3줄로 요약

**본문**:
1. 오늘의 주가 동향 (200자)
2. 주요 뉴스 및 호재/악재 분석 (400자)
3. 투자 포인트 및 주의사항 (300자)
4. 단기/중기 전망 (200자)

**태그**: 블로그 해시태그 10개

**면책조항**: 이 글은 투자 권유가 아님을 명시

JSON 형태로 응답해 주세요:
{{
  "title": "블로그 제목",
  "summary": "3줄 요약",
  "body": "본문 마크다운",
  "tags": ["태그1", "태그2", ...],
  "sentiment": "긍정/중립/부정",
  "key_points": ["핵심 포인트 1", "핵심 포인트 2", "핵심 포인트 3"]
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    # ThinkingBlock을 건너뛰고 text 블록만 추출
    raw = next(
        block.text for block in message.content
        if hasattr(block, "text")
    ).strip()

    # JSON 펜스 제거
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    return json.loads(raw)


def build_email_html(
    company_name: str,
    ticker: str,
    price_info: dict,
    analysis: dict,
    news_articles: list[dict],
    blog_uploaded: bool = False,
) -> str:
    """HTML 이메일 본문 생성."""
    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    sentiment_color = {
        "긍정": "#16a34a",
        "중립": "#2563eb",
        "부정": "#dc2626",
    }.get(analysis.get("sentiment", "중립"), "#2563eb")

    news_rows = "".join(
        f"""<tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;font-size:13px;color:#374151;">
            <b>[{a['press']}]</b> {a['title']}<br>
            <span style="color:#6b7280;font-size:12px;">{a['description'][:80]}...</span>
          </td>
        </tr>"""
        for a in news_articles[:5]
    )

    key_points = "".join(
        f'<li style="margin-bottom:6px;color:#374151;">{p}</li>'
        for p in analysis.get("key_points", [])
    )

    tags = " ".join(
        f'<span style="background:#eff6ff;color:#1d4ed8;padding:3px 8px;border-radius:12px;font-size:12px;margin:2px;">#{t}</span>'
        for t in analysis.get("tags", [])
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden;margin-top:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1e3a5f,#2563eb);padding:28px 32px;color:#fff;">
      <p style="margin:0 0 4px;font-size:12px;opacity:0.8;">📅 {today}</p>
      <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;">오늘의 KOSPI 분석</h1>
      <p style="margin:0;font-size:18px;font-weight:600;">{company_name} <span style="opacity:0.7;font-size:14px;">({ticker})</span></p>
    </div>

    <!-- Price Info -->
    <div style="display:flex;gap:0;border-bottom:1px solid #f3f4f6;">
      <div style="flex:1;padding:20px 24px;text-align:center;border-right:1px solid #f3f4f6;">
        <p style="margin:0 0 4px;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">현재가</p>
        <p style="margin:0;font-size:24px;font-weight:700;color:#111827;">{price_info['price']}원</p>
      </div>
      <div style="flex:1;padding:20px 24px;text-align:center;border-right:1px solid #f3f4f6;">
        <p style="margin:0 0 4px;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">전일 대비</p>
        <p style="margin:0;font-size:18px;font-weight:600;color:#111827;">{price_info['change']}</p>
      </div>
      <div style="flex:1;padding:20px 24px;text-align:center;">
        <p style="margin:0 0 4px;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">시장 심리</p>
        <p style="margin:0;font-size:16px;font-weight:600;color:{sentiment_color};">{analysis.get('sentiment','N/A')}</p>
      </div>
    </div>

    <div style="padding:28px 32px;">

      <!-- Summary -->
      <div style="background:#f8fafc;border-left:4px solid #2563eb;padding:16px 20px;border-radius:0 8px 8px 0;margin-bottom:24px;">
        <p style="margin:0 0 6px;font-size:11px;font-weight:600;color:#2563eb;text-transform:uppercase;letter-spacing:0.5px;">💡 오늘의 요약</p>
        <p style="margin:0;font-size:14px;color:#374151;line-height:1.6;white-space:pre-line;">{analysis.get('summary','')}</p>
      </div>

      <!-- Key Points -->
      <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 12px;">✅ 핵심 포인트</h2>
      <ul style="margin:0 0 24px;padding-left:20px;line-height:1.8;">
        {key_points}
      </ul>

      <!-- Blog Content Preview -->
      <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 12px;">📝 블로그 포스팅 제목</h2>
      <div style="background:#fef9c3;border:1px solid #fde047;padding:14px 18px;border-radius:8px;margin-bottom:24px;">
        <p style="margin:0;font-size:15px;font-weight:600;color:#713f12;">{analysis.get('title','')}</p>
      </div>

      <!-- News -->
      <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 12px;">📰 오늘의 주요 뉴스</h2>
      <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
        {news_rows}
      </table>

      <!-- Tags -->
      <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 10px;">🏷️ 추천 해시태그</h2>
      <div style="margin-bottom:28px;line-height:2;">{tags}</div>

      <!-- Blog Upload Status -->
      {'<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px 20px;text-align:center;margin-bottom:12px;"><p style="margin:0;font-size:14px;color:#15803d;font-weight:600;">✅ 네이버 블로그 자동 업로드 완료!</p></div>' if blog_uploaded else '<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:16px 20px;text-align:center;margin-bottom:12px;"><p style="margin:0 0 4px;font-size:13px;color:#92400e;font-weight:600;">⚠️ 자동 업로드 실패 — 아래 내용을 수동으로 업로드해 주세요</p><p style="margin:0;font-size:12px;color:#b45309;">블로그 제목을 복사하여 네이버 블로그에 직접 포스팅하세요</p></div>'}

      <!-- CTA -->
      <div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;padding:16px 20px;text-align:center;">
        <p style="margin:0 0 4px;font-size:13px;color:#0369a1;font-weight:500;">📋 전체 블로그 본문은 GitHub 저장소의 output/ 폴더에서 확인하세요</p>
        <p style="margin:0;font-size:12px;color:#0284c7;">⚠️ 이 분석은 참고용이며 투자 권유가 아닙니다.</p>
      </div>

    </div>

    <!-- Footer -->
    <div style="background:#f9fafb;padding:16px 32px;border-top:1px solid #f3f4f6;text-align:center;">
      <p style="margin:0;font-size:12px;color:#9ca3af;">자동 생성된 리포트 · GitHub Actions · KOSPI Daily Analysis</p>
    </div>

  </div>
</body>
</html>"""


def send_email(subject: str, html_body: str) -> None:
    """Gmail SMTP로 이메일 발송."""
    sender = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"✅ 이메일 발송 완료: {recipient}")


def save_output(company_name: str, ticker: str, analysis: dict) -> None:
    """분석 결과를 마크다운 파일로 저장."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    filename = output_dir / f"{today}-{ticker}-{company_name}.md"
    content = f"""# {analysis.get('title', f'{company_name} 분석')}

> 작성일: {today} | 종목: {company_name} ({ticker})

## 요약
{analysis.get('summary', '')}

## 본문
{analysis.get('body', '')}

---

{' '.join(f'#{t}' for t in analysis.get('tags', []))}

> ⚠️ 이 글은 투자 참고용이며, 투자 권유가 아닙니다.
"""
    filename.write_text(content, encoding="utf-8")
    print(f"✅ 파일 저장 완료: {filename}")


def main():
    print("🚀 KOSPI 일일 주식 분석 시작")

    # 1. 오늘의 종목 선택
    ticker, company_name = pick_today_stock()
    print(f"📌 오늘의 종목: {company_name} ({ticker})")

    # 2. 주가 데이터 수집
    print("📊 주가 데이터 수집 중...")
    price_info = fetch_stock_price(ticker)
    print(f"   현재가: {price_info['price']}원 ({price_info['rate']})")

    # 3. 뉴스 수집
    print("📰 최신 뉴스 수집 중...")
    news_articles = fetch_naver_news(company_name)
    print(f"   수집된 기사: {len(news_articles)}개")

    # 4. Claude API 분석
    print("🤖 Claude AI 분석 중...")
    analysis = analyze_with_claude(ticker, company_name, price_info, news_articles)
    print(f"   심리: {analysis.get('sentiment')}")
    print(f"   제목: {analysis.get('title')}")

    # 5. 결과 저장 (마크다운)
    save_output(company_name, ticker, analysis)

    # 6. 네이버 블로그 자동 업로드
    blog_uploaded = False
    if BLOG_AUTO_UPLOAD:
        print("📤 네이버 블로그 자동 업로드 중...")

        # 면책조항 추가
        body_with_disclaimer = (
            analysis.get("body", "")
            + "\n\n---\n\n"
            + "> ⚠️ **투자 주의사항**: 본 포스팅은 AI가 자동 생성한 분석 자료로, "
            "투자 권유가 아닙니다. 투자 결정은 반드시 본인의 판단과 책임 하에 하시기 바랍니다."
        )

        blog_uploaded = post_to_naver_blog(
            title=analysis.get("title", f"{company_name} 주식 분석"),
            body_markdown=body_with_disclaimer,
            tags=analysis.get("tags", []),
        )
        if blog_uploaded:
            print("   ✅ 네이버 블로그 업로드 성공!")
        else:
            print("   ⚠️ 블로그 업로드 실패 — 이메일로 알림 발송됨")
    else:
        print("ℹ️  NAVER_ID/NAVER_PW 미설정 — 블로그 자동 업로드 건너뜀")

    # 7. 이메일 발송 (분석 리포트 + 업로드 결과 포함)
    print("📧 이메일 리포트 발송 중...")
    today = datetime.date.today().strftime("%m/%d")
    upload_status = "✅ 자동 업로드 완료" if blog_uploaded else (
        "⚠️ 수동 업로드 필요" if BLOG_AUTO_UPLOAD else "ℹ️ 자동 업로드 미설정"
    )
    subject = f"[{today}] 📈 {company_name} | {upload_status}"
    html_body = build_email_html(
        company_name, ticker, price_info, analysis, news_articles,
        blog_uploaded=blog_uploaded,
    )
    send_email(subject, html_body)

    print("🎉 모든 작업 완료!")


if __name__ == "__main__":
    main()
