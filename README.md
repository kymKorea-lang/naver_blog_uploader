# 📈 KOSPI 일일 주식 분석 자동화

GitHub Actions + Claude AI를 활용한 KOSPI TOP50 종목 일일 분석 및 이메일 리포트 자동 발송 시스템입니다.

---

## 📌 주요 기능

- **매일 랜덤 종목 선택** — KOSPI TOP50 중 날짜 기반 랜덤 선택 (같은 날 중복 실행 시 동일 종목 유지)
- **주가 데이터 수집** — 현재가, 전일대비, 52주 최고/최저, PER/PBR, 거래량
- **뉴스 3종 수집** — 종목 뉴스 7개 + 섹터 뉴스 5개 + 증시 전반 뉴스 5개
- **AI 분석** — Claude AI로 시장 심리, 핵심 포인트, 섹터 동향, 블로그 본문 생성
- **매수/매도 추천** — 목표가, 손절가, 진입 시점, 이유, 리스크 포함
- **HTML 이메일 발송** — 풍성한 리포트를 다수 수신자에게 동시 발송
- **평일 16:00 KST 자동 실행** — 장마감(15:30) 후 30분 뒤 발송

---

## 📁 파일 구조

```
your-repo/
├── .github/
│   └── workflows/
│       └── daily-stock-analysis.yml   ← GitHub Actions 워크플로우
├── scripts/
│   ├── analyze_stock.py               ← 핵심 분석 + 이메일 발송
│   └── requirements.txt
├── output/                            ← 자동 생성 (분석 마크다운)
└── README.md
```

---

## ⚙️ 설정 방법

### 1단계: GitHub Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 이름 | 설명 | 필수 |
|---|---|:---:|
| `ANTHROPIC_API_KEY` | aiprimetech.io 또는 Anthropic API 키 | ✅ |
| `GMAIL_USER` | 발신용 Gmail 주소 | ✅ |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 (16자리) | ✅ |
| `RECIPIENT_EMAIL` | 수신 이메일 (여러 명은 쉼표로 구분) | ✅ |

### 2단계: Gmail 앱 비밀번호 발급

1. [myaccount.google.com/security](https://myaccount.google.com/security) 접속
2. **2단계 인증** 활성화
3. **앱 비밀번호** 검색 → 앱 이름 입력 → 생성
4. 발급된 16자리를 `GMAIL_APP_PASSWORD`에 입력

### 3단계: 수동 테스트

저장소 → **Actions 탭** → **Daily KOSPI Stock Analysis** → **Run workflow**

---

## 📧 수신자 여러 명 추가 방법

`RECIPIENT_EMAIL` Secret 값을 쉼표로 구분해서 입력하세요.

```
hong@gmail.com,kim@naver.com,lee@kakao.com
```

---

## 📊 이메일 리포트 구성

| 섹션 | 내용 |
|---|---|
| 주가 현황 | 현재가, 전일대비, PER/PBR, 시장 심리 |
| 52주 범위 | 최고/최저가, 거래량 |
| 핵심 요약 | 3줄 AI 요약 |
| 오늘의 증시 | 증시 전반 동향 |
| 섹터 동향 | 해당 종목 섹터 분석 |
| 핵심 포인트 | AI 분석 포인트 3가지 |
| 매수/매도 추천 | 내일 추천 액션 + 목표가 + 손절가 + 이유 + 리스크 |
| 블로그 제목 | 복사해서 바로 사용 가능한 SEO 제목 |
| 종목 뉴스 | 오늘의 주요 뉴스 7개 |
| 섹터 뉴스 | 섹터 관련 뉴스 5개 |
| 증시 뉴스 | 증시 전반 뉴스 5개 |
| 상세 분석 | 블로그 복붙용 본문 전체 |
| 해시태그 | 블로그용 태그 10개 |

---

## 🕐 실행 스케줄

| 항목 | 설정 |
|---|---|
| 실행 시간 | 평일 16:00 KST (UTC 07:00) |
| 실행 요일 | 월~금 (주말 제외) |
| 종목 선택 | 날짜 기반 랜덤 (매일 다른 종목) |

---

## 💰 비용

| 항목 | 비용 |
|---|---|
| GitHub Actions | 무료 (월 2,000분) |
| 네이버 금융 크롤링 | 무료 |
| Gmail SMTP | 무료 |
| Claude API (aiprimetech.io) | 약 $0.01~0.03 / 1회 |

> 월 22회 실행 기준 API 비용: 약 **$0.22~0.66** (약 300~900원)

---

## ⚠️ 주의사항

- 이 시스템이 생성하는 분석은 **투자 참고용**이며 투자 권유가 아닙니다
- 네이버 서비스 정책 변경 시 크롤링이 제한될 수 있습니다
- 주식 투자는 원금 손실이 발생할 수 있습니다
