"""
KOSPI TOP100 일일 주식 분석 스크립트
- 네이버 금융으로 주가 데이터 수집
- 네이버 뉴스 + 섹터 뉴스 수집
- Claude AI로 분석 + 매수/매도 추천
- Gmail로 풍성한 HTML 리포트 발송
- 장마감 후 16:00 (KST) 실행
"""

import os
import json
import re
import datetime
import smtplib
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import anthropic

# ── KOSPI TOP100 종목 리스트 ──────────────────────────────────────────
KOSPI_TOP100 = [
    ("005930", "삼성전자", "반도체/IT"),
    ("000660", "SK하이닉스", "반도체/IT"),
    ("207940", "삼성바이오로직스", "바이오/헬스케어"),
    ("005380", "현대차", "자동차"),
    ("000270", "기아", "자동차"),
    ("068270", "셀트리온", "바이오/헬스케어"),
    ("005490", "POSCO홀딩스", "철강/소재"),
    ("035420", "NAVER", "IT/플랫폼"),
    ("051910", "LG화학", "화학/배터리"),
    ("006400", "삼성SDI", "화학/배터리"),
    ("028260", "삼성물산", "건설/유통"),
    ("012330", "현대모비스", "자동차부품"),
    ("035720", "카카오", "IT/플랫폼"),
    ("096770", "SK이노베이션", "에너지/화학"),
    ("003550", "LG", "지주회사"),
    ("017670", "SK텔레콤", "통신"),
    ("030200", "KT", "통신"),
    ("055550", "신한지주", "금융/은행"),
    ("105560", "KB금융", "금융/은행"),
    ("086790", "하나금융지주", "금융/은행"),
    ("316140", "우리금융지주", "금융/은행"),
    ("032830", "삼성생명", "금융/보험"),
    ("003490", "대한항공", "항공/운송"),
    ("011200", "HMM", "해운/물류"),
    ("010950", "S-Oil", "에너지/정유"),
    ("034730", "SK", "지주회사"),
    ("018260", "삼성에스디에스", "IT서비스"),
    ("009150", "삼성전기", "전자부품"),
    ("011070", "LG이노텍", "전자부품"),
    ("066570", "LG전자", "전자/가전"),
    ("002380", "KCC", "건설/소재"),
    ("047050", "포스코인터내셔널", "무역/상사"),
    ("010130", "고려아연", "비철금속"),
    ("000100", "유한양행", "제약"),
    ("326030", "SK바이오팜", "바이오/헬스케어"),
    ("000720", "현대건설", "건설"),
    ("028050", "삼성엔지니어링", "건설/엔지니어링"),
    ("047040", "대우건설", "건설"),
    ("000810", "삼성화재", "금융/보험"),
    ("090430", "아모레퍼시픽", "화장품/소비재"),
    ("003670", "포스코퓨처엠", "이차전지소재"),
    ("373220", "LG에너지솔루션", "이차전지"),
    ("247540", "에코프로비엠", "이차전지소재"),
    ("086280", "현대글로비스", "물류/운송"),
    ("078930", "GS", "지주회사"),
    ("004020", "현대제철", "철강"),
    ("011780", "금호석유", "화학"),
    ("161490", "롯데케미칼", "화학"),
    ("010060", "OCI", "화학/태양광"),
    ("069960", "현대백화점", "유통/리테일"),
]


def pick_today_stock() -> tuple[str, str, str]:
    """날짜 기반으로 오늘의 종목 선택 (순환)."""
    day_of_year = datetime.date.today().timetuple().tm_yday
    index = day_of_year % len(KOSPI_TOP100)
    return KOSPI_TOP100[index]


def fetch_stock_price(ticker: str) -> dict:
    """네이버 금융에서 주가 정보 수집."""
    url = f"https://finance.naver.com/item/main.nhn?code={ticker}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        price_tag = soup.select_one("p.no_today .blind")
        price = price_tag.text.strip() if price_tag else "N/A"

        change_tags = soup.select("p.no_exday .blind")
        change = change_tags[0].text.strip() if len(change_tags) > 0 else "N/A"
        rate = change_tags[1].text.strip() if len(change_tags) > 1 else "N/A"

        # 52주 최고/최저
        high52 = soup.select_one(".no_52week .no_high")
        low52 = soup.select_one(".no_52week .no_low")
        high52_val = high52.text.strip() if high52 else "N/A"
        low52_val = low52.text.strip() if low52 else "N/A"

        # 거래량
        volume_tag = soup.select_one(".no_info .deaf")
        volume = volume_tag.text.strip() if volume_tag else "N/A"

        # PER, PBR
        per_tag = soup.select_one(".per_value em")
        pbr_tag = soup.select_one(".pbr_value em")
        per = per_tag.text.strip() if per_tag else "N/A"
        pbr = pbr_tag.text.strip() if pbr_tag else "N/A"

        return {
            "price": price,
            "change": change,
            "rate": rate,
            "high52": high52_val,
            "low52": low52_val,
            "volume": volume,
            "per": per,
            "pbr": pbr,
        }
    except Exception as e:
        print(f"주가 수집 오류: {e}")
        return {"price": "N/A", "change": "N/A", "rate": "N/A",
                "high52": "N/A", "low52": "N/A", "volume": "N/A",
                "per": "N/A", "pbr": "N/A"}


def fetch_naver_news(company_name: str, max_articles: int = 10) -> list[dict]:
    """네이버 뉴스 최신 기사 수집."""
    query = urllib.parse.quote(f"{company_name} 주가")
    url = f"https://search.naver.com/search.naver?where=news&query={query}&sort=1&pd=1"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    articles = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".news_area")[:max_articles]:
            title_tag = item.select_one(".news_tit")
            desc_tag = item.select_one(".dsc_txt_wrap")
            press_tag = item.select_one(".info_group .press")
            date_tag = item.select_one(".info_group span.info")
            if title_tag:
                articles.append({
                    "title": title_tag.get("title", title_tag.text).strip(),
                    "description": desc_tag.text.strip() if desc_tag else "",
                    "press": press_tag.text.strip() if press_tag else "",
                    "date": date_tag.text.strip() if date_tag else "",
                })
    except Exception as e:
        print(f"뉴스 수집 오류: {e}")
    return articles


def fetch_sector_news(sector: str, max_articles: int = 5) -> list[dict]:
    """섹터 관련 뉴스 수집."""
    query = urllib.parse.quote(f"{sector} 주식 전망")
    url = f"https://search.naver.com/search.naver?where=news&query={query}&sort=1&pd=1"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    articles = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".news_area")[:max_articles]:
            title_tag = item.select_one(".news_tit")
            press_tag = item.select_one(".info_group .press")
            if title_tag:
                articles.append({
                    "title": title_tag.get("title", title_tag.text).strip(),
                    "press": press_tag.text.strip() if press_tag else "",
                })
    except Exception as e:
        print(f"섹터 뉴스 수집 오류: {e}")
    return articles


def fetch_market_news(max_articles: int = 5) -> list[dict]:
    """오늘의 증시 전반 뉴스 수집."""
    query = urllib.parse.quote("코스피 증시 오늘")
    url = f"https://search.naver.com/search.naver?where=news&query={query}&sort=1&pd=1"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    articles = []
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".news_area")[:max_articles]:
            title_tag = item.select_one(".news_tit")
            press_tag = item.select_one(".info_group .press")
            if title_tag:
                articles.append({
                    "title": title_tag.get("title", title_tag.text).strip(),
                    "press": press_tag.text.strip() if press_tag else "",
                })
    except Exception as e:
        print(f"증시 뉴스 수집 오류: {e}")
    return articles


def analyze_with_claude(
    ticker: str,
    company_name: str,
    sector: str,
    price_info: dict,
    news_articles: list[dict],
    sector_news: list[dict],
    market_news: list[dict],
) -> dict:
    """Claude AI로 종합 분석 + 매수/매도 추천."""
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url="https://aiprimetech.io",
    )

    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%m월 %d일")

    news_text = "\n".join([f"- [{a['press']}] {a['title']}\n  {a['description'][:100]}" for a in news_articles]) or "수집된 뉴스 없음"
    sector_text = "\n".join([f"- [{a['press']}] {a['title']}" for a in sector_news]) or "없음"
    market_text = "\n".join([f"- [{a['press']}] {a['title']}" for a in market_news]) or "없음"

    prompt = f"""아래 데이터만 사용하여 JSON만 출력하세요. 웹검색 금지. 설명 텍스트 금지. 순수 JSON만.

## 입력 데이터
- 종목: {company_name} ({ticker}) / 섹터: {sector}
- 날짜: {today}
- 현재가: {price_info['price']}원
- 전일대비: {price_info['change']} ({price_info['rate']})
- 52주 최고: {price_info['high52']}원 / 최저: {price_info['low52']}원
- PER: {price_info['per']} / PBR: {price_info['pbr']}
- 거래량: {price_info['volume']}

## 종목 관련 뉴스
{news_text}

## {sector} 섹터 뉴스
{sector_text}

## 오늘 증시 전반
{market_text}

## 출력 JSON 형식
{{"title":"네이버 블로그용 SEO 제목","summary":"3줄 요약 (\\n으로 구분)","body":"블로그 본문 마크다운 (주가동향/뉴스분석/섹터동향/투자포인트/전망 순서로 총 1000자 이상)","sentiment":"긍정 또는 중립 또는 부정","tags":["태그1","태그2","태그3","태그4","태그5","태그6","태그7","태그8","태그9","태그10"],"key_points":["핵심포인트1","핵심포인트2","핵심포인트3"],"buy_recommendation":{{"action":"매수 또는 관망 또는 매도","target_price":"목표가 (예: 195,000원)","stop_loss":"손절가 (예: 183,000원)","reason":"매수/매도 추천 이유 3줄 이상 구체적으로","timing":"{tomorrow} 추천 진입 시점 (예: 오전 장초반 눌림목)","risk":"주요 리스크 요인 2가지"}},"sector_summary":"섹터 전반 동향 2~3줄","market_summary":"오늘 증시 전반 요약 2줄"}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system="당신은 JSON만 출력하는 주식 분석 전문가입니다. 웹검색 안 함. 순수 JSON만 반환.",
        messages=[{"role": "user", "content": prompt}],
    )

    text_blocks = [b.text for b in message.content if hasattr(b, "text")]
    if not text_blocks:
        raise ValueError("text 블록 없음")
    raw = text_blocks[0].strip()
    print(f"   [DEBUG] 응답 앞 150자: {raw[:150]}")

    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence_match:
        raw = fence_match.group(1).strip()
    else:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            raw = raw[start:end]
        else:
            raise ValueError(f"JSON 없음: {raw[:300]}")

    return json.loads(raw)


def build_email_html(
    company_name: str,
    ticker: str,
    sector: str,
    price_info: dict,
    analysis: dict,
    news_articles: list[dict],
    sector_news: list[dict],
    market_news: list[dict],
) -> str:
    """풍성한 HTML 이메일 생성."""
    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%m월 %d일 (%a)")

    sentiment = analysis.get("sentiment", "중립")
    sentiment_color = {"긍정": "#16a34a", "중립": "#2563eb", "부정": "#dc2626"}.get(sentiment, "#2563eb")
    sentiment_bg = {"긍정": "#f0fdf4", "중립": "#eff6ff", "부정": "#fef2f2"}.get(sentiment, "#eff6ff")

    buy = analysis.get("buy_recommendation", {})
    action = buy.get("action", "관망")
    action_color = {"매수": "#16a34a", "관망": "#d97706", "매도": "#dc2626"}.get(action, "#d97706")
    action_bg = {"매수": "#f0fdf4", "관망": "#fffbeb", "매도": "#fef2f2"}.get(action, "#fffbeb")

    # 종목 뉴스 rows
    news_rows = "".join(f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #f3f4f6;">
            <div style="font-size:12px;color:#6b7280;margin-bottom:3px;">[{a['press']}] {a['date']}</div>
            <div style="font-size:13px;color:#1f2937;font-weight:500;line-height:1.4;">{a['title']}</div>
            <div style="font-size:12px;color:#6b7280;margin-top:3px;line-height:1.4;">{a['description'][:100]}...</div>
          </td>
        </tr>""" for a in news_articles[:7])

    # 섹터 뉴스
    sector_rows = "".join(f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">
            <span style="font-size:11px;color:#7c3aed;font-weight:600;">[{a['press']}]</span>
            <span style="font-size:13px;color:#374151;margin-left:6px;">{a['title']}</span>
          </td>
        </tr>""" for a in sector_news[:5])

    # 증시 뉴스
    market_rows = "".join(f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #f3f4f6;">
            <span style="font-size:11px;color:#0369a1;font-weight:600;">[{a['press']}]</span>
            <span style="font-size:13px;color:#374151;margin-left:6px;">{a['title']}</span>
          </td>
        </tr>""" for a in market_news[:5])

    # 핵심 포인트
    key_points = "".join(f'<li style="margin-bottom:8px;color:#374151;font-size:13px;line-height:1.6;">{p}</li>'
                         for p in analysis.get("key_points", []))

    # 태그
    tags = " ".join(f'<span style="background:#eff6ff;color:#1d4ed8;padding:3px 10px;border-radius:12px;font-size:11px;margin:2px;display:inline-block;">#{t}</span>'
                    for t in analysis.get("tags", []))

    # 본문 마크다운 → 간단 HTML 변환
    body_html = analysis.get("body", "").replace("\n\n", "<br><br>").replace("\n", "<br>")
    body_html = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', body_html)
    body_html = re.sub(r'^## (.+)', r'<h3 style="font-size:15px;color:#1e3a5f;margin:16px 0 8px;">\1</h3>', body_html, flags=re.MULTILINE)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<div style="max-width:680px;margin:20px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 6px rgba(0,0,0,0.07);">

  <!-- 헤더 -->
  <div style="background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);padding:32px;color:#fff;">
    <div style="font-size:12px;opacity:0.75;margin-bottom:6px;">📅 {today} 장마감 분석 리포트</div>
    <h1 style="margin:0 0 6px;font-size:24px;font-weight:700;">{company_name}</h1>
    <div style="font-size:14px;opacity:0.85;">{ticker} · {sector} 섹터</div>
  </div>

  <!-- 주가 현황 -->
  <div style="display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid #f3f4f6;">
    <div style="padding:18px 16px;text-align:center;border-right:1px solid #f3f4f6;">
      <div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">현재가</div>
      <div style="font-size:20px;font-weight:700;color:#111827;">{price_info['price']}원</div>
    </div>
    <div style="padding:18px 16px;text-align:center;border-right:1px solid #f3f4f6;">
      <div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">전일대비</div>
      <div style="font-size:16px;font-weight:600;color:#111827;">{price_info['change']} ({price_info['rate']})</div>
    </div>
    <div style="padding:18px 16px;text-align:center;border-right:1px solid #f3f4f6;">
      <div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">PER / PBR</div>
      <div style="font-size:14px;font-weight:600;color:#374151;">{price_info['per']} / {price_info['pbr']}</div>
    </div>
    <div style="padding:18px 16px;text-align:center;">
      <div style="font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">시장 심리</div>
      <div style="font-size:14px;font-weight:600;color:{sentiment_color};">{sentiment}</div>
    </div>
  </div>

  <!-- 52주 범위 -->
  <div style="padding:12px 24px;background:#f8fafc;border-bottom:1px solid #f3f4f6;font-size:12px;color:#6b7280;">
    📊 52주 최저 <strong style="color:#374151;">{price_info['low52']}원</strong> &nbsp;·&nbsp;
    52주 최고 <strong style="color:#374151;">{price_info['high52']}원</strong> &nbsp;·&nbsp;
    거래량 <strong style="color:#374151;">{price_info['volume']}</strong>
  </div>

  <div style="padding:28px 32px;">

    <!-- 요약 -->
    <div style="background:#f8fafc;border-left:4px solid #2563eb;padding:16px 20px;border-radius:0 10px 10px 0;margin-bottom:24px;">
      <div style="font-size:11px;font-weight:600;color:#2563eb;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px;">💡 오늘의 핵심 요약</div>
      <div style="font-size:13px;color:#374151;line-height:1.8;white-space:pre-line;">{analysis.get('summary','')}</div>
    </div>

    <!-- 증시 전반 -->
    <div style="background:#eff6ff;border-radius:10px;padding:14px 18px;margin-bottom:24px;">
      <div style="font-size:11px;font-weight:600;color:#1d4ed8;margin-bottom:6px;">📈 오늘의 증시 전반</div>
      <div style="font-size:13px;color:#1e40af;line-height:1.7;">{analysis.get('market_summary','')}</div>
    </div>

    <!-- 섹터 동향 -->
    <div style="background:#f5f3ff;border-radius:10px;padding:14px 18px;margin-bottom:24px;">
      <div style="font-size:11px;font-weight:600;color:#7c3aed;margin-bottom:6px;">🏭 {sector} 섹터 동향</div>
      <div style="font-size:13px;color:#5b21b6;line-height:1.7;">{analysis.get('sector_summary','')}</div>
    </div>

    <!-- 핵심 포인트 -->
    <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 12px;">✅ 핵심 포인트</h2>
    <ul style="margin:0 0 24px;padding-left:20px;line-height:1.8;">{key_points}</ul>

    <!-- 내일 매수/매도 추천 -->
    <div style="background:{action_bg};border:2px solid {action_color};border-radius:12px;padding:20px 24px;margin-bottom:24px;">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
        <span style="background:{action_color};color:#fff;padding:6px 16px;border-radius:20px;font-size:14px;font-weight:700;">{action}</span>
        <span style="font-size:14px;font-weight:600;color:#111827;">{tomorrow} 추천</span>
      </div>
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;width:80px;">목표가</td>
          <td style="padding:6px 0;font-size:13px;font-weight:600;color:#111827;">{buy.get('target_price','N/A')}</td>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;width:80px;">손절가</td>
          <td style="padding:6px 0;font-size:13px;font-weight:600;color:#dc2626;">{buy.get('stop_loss','N/A')}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#6b7280;">진입 시점</td>
          <td style="padding:6px 0;font-size:13px;color:#374151;" colspan="3">{buy.get('timing','N/A')}</td>
        </tr>
      </table>
      <div style="margin-top:14px;padding-top:14px;border-top:1px solid rgba(0,0,0,0.1);">
        <div style="font-size:12px;color:#6b7280;margin-bottom:6px;font-weight:600;">📌 추천 이유</div>
        <div style="font-size:13px;color:#374151;line-height:1.7;white-space:pre-line;">{buy.get('reason','')}</div>
      </div>
      <div style="margin-top:12px;padding:10px 14px;background:rgba(0,0,0,0.04);border-radius:8px;">
        <div style="font-size:11px;color:#6b7280;font-weight:600;margin-bottom:4px;">⚠️ 주요 리스크</div>
        <div style="font-size:12px;color:#374151;">{buy.get('risk','')}</div>
      </div>
    </div>

    <!-- 블로그 제목 -->
    <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 10px;">📝 오늘의 블로그 제목 (복사용)</h2>
    <div style="background:#fef9c3;border:1px solid #fde047;padding:14px 18px;border-radius:8px;margin-bottom:24px;">
      <div style="font-size:15px;font-weight:600;color:#713f12;">{analysis.get('title','')}</div>
    </div>

    <!-- 종목 뉴스 -->
    <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 12px;">📰 {company_name} 오늘의 주요 뉴스</h2>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;border:1px solid #f3f4f6;border-radius:8px;overflow:hidden;">
      {news_rows if news_rows else '<tr><td style="padding:16px;color:#9ca3af;text-align:center;">수집된 뉴스 없음</td></tr>'}
    </table>

    <!-- 섹터 뉴스 -->
    <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 12px;">🏭 {sector} 섹터 뉴스</h2>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;border:1px solid #f3f4f6;border-radius:8px;overflow:hidden;">
      {sector_rows if sector_rows else '<tr><td style="padding:16px;color:#9ca3af;text-align:center;">수집된 섹터 뉴스 없음</td></tr>'}
    </table>

    <!-- 증시 뉴스 -->
    <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 12px;">📊 오늘의 증시 뉴스</h2>
    <table style="width:100%;border-collapse:collapse;margin-bottom:24px;border:1px solid #f3f4f6;border-radius:8px;overflow:hidden;">
      {market_rows if market_rows else '<tr><td style="padding:16px;color:#9ca3af;text-align:center;">수집된 증시 뉴스 없음</td></tr>'}
    </table>

    <!-- 분석 본문 -->
    <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 12px;">📋 상세 분석 (블로그 본문)</h2>
    <div style="background:#f9fafb;border-radius:10px;padding:20px 24px;margin-bottom:24px;font-size:13px;color:#374151;line-height:1.8;">
      {body_html}
    </div>

    <!-- 태그 -->
    <h2 style="font-size:15px;font-weight:600;color:#111827;margin:0 0 10px;">🏷️ 해시태그</h2>
    <div style="margin-bottom:24px;line-height:2;">{tags}</div>

    <!-- 면책 -->
    <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:14px 18px;">
      <div style="font-size:12px;color:#991b1b;font-weight:600;margin-bottom:4px;">⚠️ 투자 주의사항</div>
      <div style="font-size:11px;color:#b91c1c;line-height:1.6;">본 리포트는 AI가 자동 생성한 분석 자료로, 투자 권유가 아닙니다. 투자 결정은 반드시 본인의 판단과 책임 하에 하시기 바랍니다. 주식 투자는 원금 손실이 발생할 수 있습니다.</div>
    </div>

  </div>

  <!-- 푸터 -->
  <div style="background:#f8fafc;padding:16px 32px;border-top:1px solid #f3f4f6;text-align:center;">
    <div style="font-size:11px;color:#9ca3af;">KOSPI Daily Analysis · GitHub Actions 자동 생성 · {today} 16:00 KST</div>
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
    """분석 결과 마크다운 저장."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    filename = output_dir / f"{today}-{ticker}-{company_name}.md"

    buy = analysis.get("buy_recommendation", {})
    content = f"""# {analysis.get('title', f'{company_name} 분석')}

> 작성일: {today} | 종목: {company_name} ({ticker})

## 요약
{analysis.get('summary', '')}

## 내일 매매 추천
- **액션**: {buy.get('action', '')}
- **목표가**: {buy.get('target_price', '')}
- **손절가**: {buy.get('stop_loss', '')}
- **진입 시점**: {buy.get('timing', '')}
- **이유**: {buy.get('reason', '')}
- **리스크**: {buy.get('risk', '')}

## 본문
{analysis.get('body', '')}

---

{' '.join(f'#{t}' for t in analysis.get('tags', []))}

> ⚠️ 투자 참고용이며 투자 권유가 아닙니다.
"""
    filename.write_text(content, encoding="utf-8")
    print(f"✅ 파일 저장: {filename}")


def main():
    print("🚀 KOSPI 일일 주식 분석 시작")

    ticker, company_name, sector = pick_today_stock()
    print(f"📌 오늘의 종목: {company_name} ({ticker}) / {sector}")

    print("📊 주가 데이터 수집 중...")
    price_info = fetch_stock_price(ticker)
    print(f"   현재가: {price_info['price']}원 ({price_info['rate']})")

    print("📰 종목 뉴스 수집 중...")
    news_articles = fetch_naver_news(company_name)
    print(f"   수집: {len(news_articles)}개")

    print(f"🏭 {sector} 섹터 뉴스 수집 중...")
    sector_news = fetch_sector_news(sector)
    print(f"   수집: {len(sector_news)}개")

    print("📈 증시 전반 뉴스 수집 중...")
    market_news = fetch_market_news()
    print(f"   수집: {len(market_news)}개")

    print("🤖 Claude AI 분석 중...")
    analysis = analyze_with_claude(
        ticker, company_name, sector,
        price_info, news_articles, sector_news, market_news
    )
    print(f"   심리: {analysis.get('sentiment')} / 추천: {analysis.get('buy_recommendation', {}).get('action')}")

    save_output(company_name, ticker, analysis)

    print("📧 이메일 발송 중...")
    today = datetime.date.today().strftime("%m/%d")
    action = analysis.get("buy_recommendation", {}).get("action", "관망")
    action_emoji = {"매수": "🟢", "관망": "🟡", "매도": "🔴"}.get(action, "🟡")
    subject = f"[{today}] {action_emoji} {company_name} {action} | KOSPI 장마감 분석"

    html_body = build_email_html(
        company_name, ticker, sector,
        price_info, analysis,
        news_articles, sector_news, market_news,
    )
    send_email(subject, html_body)
    print("🎉 완료!")


if __name__ == "__main__":
    main()
