# 📈 KOSPI 일일 주식 분석 자동화

GitHub Actions + Claude AI + Selenium을 활용한 KOSPI TOP100 종목 일일 분석 및 네이버 블로그 자동 업로드 시스템입니다.

## 동작 방식

매일 오후 4시 (KST)에 자동 실행되며:

1. KOSPI TOP100에서 오늘의 종목 선택 (날짜 기반 순환)
2. 네이버 금융에서 주가 데이터 수집
3. 네이버 뉴스에서 최신 기사 수집
4. Claude AI로 블로그용 분석 콘텐츠 생성
5. **Selenium으로 네이버 블로그에 자동 포스팅**
6. HTML 이메일 리포트 발송 (업로드 성공/실패 결과 포함)
7. 마크다운 파일을 `output/` 폴더에 저장 (GitHub Artifacts, 30일 보관)

---

## 파일 구조

```
your-repo/
├── .github/
│   └── workflows/
│       └── daily-stock-analysis.yml   ← GitHub Actions 워크플로우
├── scripts/
│   ├── analyze_stock.py               ← 핵심 분석 + 이메일 발송
│   ├── naver_blog_uploader.py         ← Selenium 블로그 업로드
│   └── requirements.txt
├── output/                            ← 자동 생성 (분석 마크다운)
└── README.md
```

---

## 설정 방법

### 1단계: GitHub Secrets 설정

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 이름 | 설명 | 필수 여부 |
|---|---|:---:|
| `ANTHROPIC_API_KEY` | Anthropic API 키 ([발급](https://console.anthropic.com)) | ✅ |
| `GMAIL_USER` | Gmail 주소 (발신용) | ✅ |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호 (아래 참고) | ✅ |
| `RECIPIENT_EMAIL` | 분석 리포트 수신 이메일 | ✅ |
| `NAVER_ID` | 네이버 아이디 | 자동 업로드 시 필수 |
| `NAVER_PW` | 네이버 비밀번호 | 자동 업로드 시 필수 |

> `NAVER_ID`와 `NAVER_PW`를 설정하지 않으면 이메일 발송만 진행됩니다.

### 2단계: Gmail 앱 비밀번호 발급

1. Google 계정 → **보안** → **2단계 인증** 활성화
2. **앱 비밀번호** → 앱: 메일, 기기: 기타(직접 입력) → 생성
3. 발급된 16자리 코드를 `GMAIL_APP_PASSWORD`에 입력

---

## CAPTCHA 대응 전략

네이버는 자동 로그인을 감지할 수 있습니다. 이 시스템은 아래 방법으로 우회합니다:

| 전략 | 설명 |
|---|---|
| `undetected-chromedriver` | `webdriver` 속성 숨김, 봇 탐지 우회 |
| JavaScript 입력 주입 | 직접 타이핑 대신 JS로 값 주입 |
| 랜덤 딜레이 | 0.8~2.5초 랜덤 대기로 자연스러운 행동 모방 |
| 쿠키 캐싱 | 로그인 후 쿠키 저장 → 재로그인 최소화 |
| 실패 감지 | CAPTCHA/2차 인증 감지 시 스크린샷 + 이메일 알림 |

**로그인이 계속 실패하는 경우:**
- 네이버 계정에서 한 번 직접 로그인하여 신뢰 기기로 등록
- 네이버 보안 설정에서 "자동 로그인" 허용
- 2차 인증(OTP)이 설정된 경우 임시 비활성화 후 테스트

---

## 수동 실행 및 디버깅

**Actions 탭 → Daily KOSPI Stock Analysis → Run workflow**

실패 시 Actions 탭에서 **selenium-screenshots** artifact를 다운받아 스크린샷 확인 가능

---

## 종목 커스터마이징

`scripts/analyze_stock.py`의 `KOSPI_TOP100` 리스트 수정 또는:

```python
# 특정 종목 고정
def pick_today_stock():
    return ("005930", "삼성전자")
```

---

## 비용 안내

| 항목 | 비용 |
|---|---|
| GitHub Actions | 무료 (월 2,000분, 충분) |
| 네이버 금융 크롤링 | 무료 |
| Gmail SMTP | 무료 |
| Claude API | 약 $0.01~0.03 / 1회 분석 |

> 월 30회 실행 기준 Claude API 비용: 약 **$0.30~0.90** (약 400~1,200원)

---

## 주의사항

- 이 시스템이 생성하는 분석은 **투자 참고용**이며 투자 권유가 아닙니다
- 네이버 서비스 정책 변경 시 크롤링/자동화가 제한될 수 있습니다
- 블로그 자동화는 네이버 이용약관을 준수하는 범위에서 사용하세요
