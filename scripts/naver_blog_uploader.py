"""
네이버 블로그 자동 업로드 모듈 (Selenium)

봇 탐지 회피 전략:
- undetected-chromedriver로 headless Chrome 실행
- 랜덤 딜레이로 자연스러운 사람 행동 모방
- 로그인 실패 시 스크린샷 저장 + 이메일 알림
- 세션 쿠키 캐싱으로 반복 로그인 최소화
"""

import os
import json
import time
import random
import smtplib
import traceback
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


# ── 상수 ──────────────────────────────────────────
NAVER_LOGIN_URL = "https://nid.naver.com/nidlogin.login"
NAVER_BLOG_WRITE_URL = "https://blog.naver.com/PostWriteForm.naver"
COOKIE_FILE = Path("/tmp/naver_cookies.json")
SCREENSHOT_DIR = Path("/tmp/screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)


def human_delay(min_sec: float = 0.8, max_sec: float = 2.5) -> None:
    """사람처럼 보이는 랜덤 딜레이."""
    time.sleep(random.uniform(min_sec, max_sec))


def human_type(element, text: str) -> None:
    """사람처럼 한 글자씩 랜덤 딜레이로 타이핑."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.18))


def make_driver() -> uc.Chrome:
    """봇 탐지 우회 Chrome 드라이버 생성."""
    options = uc.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,768")
    options.add_argument("--lang=ko-KR")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.6099.130 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")

    # 시스템에 설치된 ChromeDriver 경로 명시 (버전 불일치 방지)
    chromedriver_path = "/usr/local/bin/chromedriver"
    if not os.path.exists(chromedriver_path):
        chromedriver_path = None  # 없으면 자동 탐색

    driver = uc.Chrome(
        options=options,
        use_subprocess=True,
        driver_executable_path=chromedriver_path,
    )
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def save_cookies(driver: uc.Chrome) -> None:
    """네이버 쿠키 저장 (다음 실행 시 재사용)."""
    cookies = driver.get_cookies()
    COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
    print("   🍪 쿠키 저장 완료")


def load_cookies(driver: uc.Chrome) -> bool:
    """저장된 쿠키 불러오기. 성공하면 True 반환."""
    if not COOKIE_FILE.exists():
        return False
    try:
        driver.get("https://www.naver.com")
        human_delay(1, 2)
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        for cookie in cookies:
            # 만료 쿠키 건너뜀
            if "expiry" in cookie and cookie["expiry"] < time.time():
                continue
            try:
                driver.add_cookie(cookie)
            except Exception:
                pass
        driver.refresh()
        human_delay(1.5, 2.5)

        # 로그인 상태 확인
        if _is_logged_in(driver):
            print("   🍪 쿠키로 로그인 성공")
            return True
    except Exception as e:
        print(f"   쿠키 로드 실패: {e}")

    COOKIE_FILE.unlink(missing_ok=True)
    return False


def _is_logged_in(driver: uc.Chrome) -> bool:
    """현재 네이버 로그인 상태 확인."""
    driver.get("https://www.naver.com")
    human_delay(1, 1.5)
    try:
        # 로그인 버튼이 없으면 로그인 상태
        login_btn = driver.find_elements(By.CSS_SELECTOR, ".link_login")
        return len(login_btn) == 0
    except Exception:
        return False


def naver_login(driver: uc.Chrome) -> bool:
    """
    네이버 ID/PW 로그인.
    JavaScript로 입력값 주입 → CAPTCHA 우회율 향상.
    """
    naver_id = os.environ["NAVER_ID"]
    naver_pw = os.environ["NAVER_PW"]

    driver.get(NAVER_LOGIN_URL)
    human_delay(2, 3)

    try:
        wait = WebDriverWait(driver, 15)

        # JavaScript로 입력값 주입 (봇 탐지 우회)
        id_input = wait.until(EC.presence_of_element_located((By.ID, "id")))
        driver.execute_script(
            "arguments[0].value = arguments[1];", id_input, naver_id
        )
        id_input.send_keys(Keys.TAB)  # 포커스 이동으로 이벤트 발생
        human_delay(0.5, 1.2)

        pw_input = driver.find_element(By.ID, "pw")
        driver.execute_script(
            "arguments[0].value = arguments[1];", pw_input, naver_pw
        )
        pw_input.send_keys(Keys.TAB)
        human_delay(0.5, 1.0)

        # 로그인 버튼 클릭
        login_btn = driver.find_element(By.ID, "log.login")
        login_btn.click()
        human_delay(3, 5)

        # CAPTCHA 감지
        if "captcha" in driver.current_url.lower() or "challenge" in driver.page_source.lower():
            _take_screenshot(driver, "captcha_detected")
            print("   ⚠️ CAPTCHA 감지됨")
            return False

        # 2차 인증 감지
        if "二단계" in driver.page_source or "인증" in driver.title:
            _take_screenshot(driver, "2fa_required")
            print("   ⚠️ 2차 인증 필요")
            return False

        if _is_logged_in(driver):
            save_cookies(driver)
            print("   ✅ 네이버 로그인 성공")
            return True
        else:
            _take_screenshot(driver, "login_failed")
            print("   ❌ 로그인 실패 (아이디/비밀번호 확인 필요)")
            return False

    except TimeoutException:
        _take_screenshot(driver, "login_timeout")
        print("   ❌ 로그인 시간 초과")
        return False


def _take_screenshot(driver: uc.Chrome, name: str) -> Path:
    """스크린샷 저장."""
    path = SCREENSHOT_DIR / f"{name}_{int(time.time())}.png"
    driver.save_screenshot(str(path))
    print(f"   📸 스크린샷 저장: {path}")
    return path


def markdown_to_naver_html(markdown_text: str) -> str:
    """
    마크다운을 네이버 블로그 에디터에 맞는 HTML로 변환.
    네이버 스마트에디터는 특정 태그만 허용하므로 단순하게 변환.
    """
    import re

    lines = markdown_text.split("\n")
    html_lines = []

    for line in lines:
        line = line.rstrip()

        # 제목
        if line.startswith("### "):
            html_lines.append(f'<h3 style="font-size:18px;font-weight:bold;margin:16px 0 8px;">{line[4:]}</h3>')
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="font-size:20px;font-weight:bold;margin:20px 0 10px;color:#1a1a1a;">{line[3:]}</h2>')
        elif line.startswith("# "):
            html_lines.append(f'<h1 style="font-size:24px;font-weight:bold;margin:24px 0 12px;color:#111;">{line[2:]}</h1>')
        # 인용구
        elif line.startswith("> "):
            html_lines.append(
                f'<blockquote style="border-left:4px solid #2563eb;margin:12px 0;padding:8px 16px;'
                f'background:#f0f7ff;color:#374151;font-style:italic;">{line[2:]}</blockquote>'
            )
        # 굵게 + 기울임
        elif line.startswith("**") and line.endswith("**"):
            html_lines.append(f'<p style="margin:8px 0;"><strong>{line[2:-2]}</strong></p>')
        # 수평선
        elif line.startswith("---"):
            html_lines.append('<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">')
        # 불릿 리스트
        elif line.startswith("- ") or line.startswith("* "):
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line[2:])
            html_lines.append(f'<p style="margin:4px 0;padding-left:16px;">• {content}</p>')
        # 번호 리스트
        elif re.match(r'^\d+\. ', line):
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', re.sub(r'^\d+\. ', '', line))
            num = re.match(r'^(\d+)\.', line).group(1)
            html_lines.append(f'<p style="margin:6px 0;padding-left:4px;"><strong style="color:#2563eb;">{num}.</strong> {content}</p>')
        # 빈 줄
        elif line == "":
            html_lines.append('<p style="margin:6px 0;">&nbsp;</p>')
        # 일반 텍스트 (인라인 볼드 처리)
        else:
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
            content = re.sub(r'\*(.*?)\*', r'<em>\1</em>', content)
            html_lines.append(f'<p style="margin:8px 0;line-height:1.8;color:#1a1a1a;">{content}</p>')

    return "\n".join(html_lines)


def upload_to_naver_blog(
    driver: uc.Chrome,
    title: str,
    body_markdown: str,
    tags: list[str],
) -> bool:
    """
    네이버 블로그 스마트에디터에 포스팅 업로드.
    iframe 기반 에디터를 JavaScript로 직접 조작.
    """
    print("   📝 블로그 에디터 열기...")
    driver.get(NAVER_BLOG_WRITE_URL)
    human_delay(4, 6)

    wait = WebDriverWait(driver, 30)

    try:
        # ── 제목 입력 ──────────────────────────────
        print("   ✏️  제목 입력 중...")
        title_selectors = [
            "input.se-input-title",
            ".se-title-input",
            "input[placeholder*='제목']",
            "#title",
        ]
        title_input = None
        for sel in title_selectors:
            try:
                title_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                break
            except TimeoutException:
                continue

        if not title_input:
            print("   ❌ 제목 입력창을 찾을 수 없음")
            _take_screenshot(driver, "title_not_found")
            return False

        title_input.click()
        human_delay(0.5, 1)
        title_input.clear()
        human_type(title_input, title)
        human_delay(1, 2)

        # ── 본문 입력 (JavaScript로 에디터에 직접 주입) ──
        print("   📄 본문 입력 중...")
        html_body = markdown_to_naver_html(body_markdown)

        # 네이버 스마트에디터3 (SE3) JavaScript API 사용
        injected = driver.execute_script(
            """
            // SE3 에디터 인스턴스 찾기
            const editors = Object.values(window).filter(
                v => v && typeof v === 'object' && v.getEditor
            );
            if (editors.length > 0) {
                try {
                    editors[0].getEditor().setContent(arguments[0]);
                    return 'se3_success';
                } catch(e) {}
            }

            // contenteditable 방식 시도
            const editables = document.querySelectorAll('[contenteditable="true"]');
            for (const el of editables) {
                const rect = el.getBoundingClientRect();
                if (rect.height > 100) {
                    el.focus();
                    el.innerHTML = arguments[0];
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'contenteditable_success';
                }
            }

            // iframe 내부 에디터 시도
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
                try {
                    const iDoc = iframe.contentDocument || iframe.contentWindow.document;
                    const body = iDoc.querySelector('body[contenteditable]') || iDoc.body;
                    if (body) {
                        body.focus();
                        iDoc.execCommand('selectAll', false, null);
                        iDoc.execCommand('insertHTML', false, arguments[0]);
                        return 'iframe_success';
                    }
                } catch(e) {}
            }
            return 'failed';
            """,
            html_body,
        )
        print(f"   에디터 주입 결과: {injected}")

        if injected == "failed":
            # 폴백: 클립보드로 붙여넣기 시도
            print("   🔄 폴백: 클립보드 방식 시도...")
            driver.execute_script(
                "navigator.clipboard.writeText(arguments[0]).catch(()=>{})", html_body
            )
            body_area = driver.find_element(By.CSS_SELECTOR, "[contenteditable='true']")
            body_area.click()
            human_delay(0.5, 1)
            body_area.send_keys(Keys.CONTROL, "a")
            body_area.send_keys(Keys.CONTROL, "v")

        human_delay(2, 3)

        # ── 태그 입력 ───────────────────────────────
        print("   🏷️  태그 입력 중...")
        tag_selectors = [
            "input.tag_input",
            ".se-tag-input input",
            "input[placeholder*='태그']",
            "#tagInput",
        ]
        tag_input = None
        for sel in tag_selectors:
            try:
                tag_input = driver.find_element(By.CSS_SELECTOR, sel)
                if tag_input.is_displayed():
                    break
            except NoSuchElementException:
                tag_input = None

        if tag_input:
            tag_input.click()
            human_delay(0.3, 0.7)
            for tag in tags[:10]:  # 최대 10개
                tag_clean = tag.replace("#", "").strip()
                human_type(tag_input, tag_clean)
                human_delay(0.2, 0.5)
                tag_input.send_keys(Keys.RETURN)
                human_delay(0.3, 0.6)
        else:
            print("   ⚠️ 태그 입력창 없음 — 건너뜀")

        human_delay(1, 2)

        # ── 공개 설정 확인 (기본값: 전체 공개) ─────────
        try:
            public_options = driver.find_elements(
                By.CSS_SELECTOR, ".se-publish-options, .open_select"
            )
            if public_options:
                # 전체 공개가 기본값이므로 별도 조작 불필요
                print("   🌐 공개 설정: 전체 공개 (기본값)")
        except Exception:
            pass

        # ── 발행 버튼 클릭 ──────────────────────────
        print("   🚀 발행 중...")
        publish_selectors = [
            "button.publish_btn__Y9mxn",  # SE3
            ".btn_publish",
            "button[data-action='publish']",
            "//button[contains(text(),'발행')]",  # XPath
            "//button[contains(text(),'등록')]",
        ]

        published = False
        for sel in publish_selectors:
            try:
                if sel.startswith("//"):
                    btn = driver.find_element(By.XPATH, sel)
                else:
                    btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed() and btn.is_enabled():
                    human_delay(0.5, 1)
                    btn.click()
                    published = True
                    print(f"   ✅ 발행 버튼 클릭: {sel}")
                    break
            except (NoSuchElementException, Exception):
                continue

        if not published:
            _take_screenshot(driver, "publish_btn_not_found")
            print("   ❌ 발행 버튼을 찾을 수 없음")
            return False

        human_delay(3, 5)

        # ── 발행 완료 확인 ─────────────────────────
        current_url = driver.current_url
        if "PostView" in current_url or "blog.naver.com" in current_url:
            print(f"   ✅ 블로그 업로드 완료: {current_url}")
            return True
        else:
            # 추가 확인 대화상자가 있을 수 있음
            try:
                confirm_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(text(),'확인') or contains(text(),'발행')]")
                    )
                )
                confirm_btn.click()
                human_delay(2, 3)
                print(f"   ✅ 최종 확인 후 발행 완료")
                return True
            except TimeoutException:
                _take_screenshot(driver, "post_publish_result")
                # URL 변경으로 성공 여부 재확인
                return "blog.naver.com" in driver.current_url

    except Exception as e:
        _take_screenshot(driver, "upload_error")
        print(f"   ❌ 업로드 오류: {e}")
        traceback.print_exc()
        return False


def send_failure_alert(error_details: str, screenshot_path: Path | None = None) -> None:
    """업로드 실패 시 스크린샷과 함께 이메일 알림 발송."""
    sender = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart()
    msg["Subject"] = "⚠️ 네이버 블로그 자동 업로드 실패"
    msg["From"] = sender
    msg["To"] = recipient

    html = f"""
    <div style="font-family:sans-serif;max-width:500px;">
      <h2 style="color:#dc2626;">⚠️ 블로그 자동 업로드 실패</h2>
      <p>오늘 KOSPI 분석 포스팅 자동 업로드에 실패했습니다.</p>
      <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px;margin:12px 0;">
        <pre style="margin:0;font-size:12px;color:#7f1d1d;white-space:pre-wrap;">{error_details}</pre>
      </div>
      <p style="color:#6b7280;font-size:13px;">
        분석 결과는 이메일로 별도 수신되었습니다.<br>
        네이버 블로그에 수동으로 업로드해 주세요.
      </p>
      <hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;">
      <p style="font-size:11px;color:#9ca3af;">가능한 원인: CAPTCHA / 2차 인증 / 세션 만료</p>
    </div>
    """
    msg.attach(MIMEText(html, "html", "utf-8"))

    # 스크린샷 첨부
    if screenshot_path and screenshot_path.exists():
        with open(screenshot_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", f'attachment; filename="{screenshot_path.name}"'
        )
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print("   📧 실패 알림 이메일 발송 완료")
    except Exception as e:
        print(f"   실패 알림 이메일 발송 오류: {e}")


def post_to_naver_blog(
    title: str,
    body_markdown: str,
    tags: list[str],
) -> bool:
    """
    메인 진입점.
    쿠키 → 로그인 → 업로드 순으로 시도.
    실패 시 이메일 알림 발송.
    """
    driver = None
    try:
        print("🌐 Chrome 드라이버 시작...")
        driver = make_driver()

        # 1. 쿠키로 로그인 시도
        logged_in = load_cookies(driver)

        # 2. 쿠키 실패 시 ID/PW 로그인
        if not logged_in:
            print("🔐 아이디/비밀번호로 로그인 시도...")
            logged_in = naver_login(driver)

        if not logged_in:
            screenshots = sorted(SCREENSHOT_DIR.glob("*.png"))
            latest_shot = screenshots[-1] if screenshots else None
            send_failure_alert(
                "네이버 로그인 실패\n\nCAPTCHA 또는 2차 인증이 필요하거나 아이디/비밀번호가 올바르지 않습니다.",
                latest_shot,
            )
            return False

        # 3. 블로그 업로드
        print("📤 블로그 업로드 시작...")
        success = upload_to_naver_blog(driver, title, body_markdown, tags)

        if not success:
            screenshots = sorted(SCREENSHOT_DIR.glob("*.png"))
            latest_shot = screenshots[-1] if screenshots else None
            send_failure_alert(
                "블로그 에디터 업로드 실패\n\n에디터 구조가 변경되었거나 네이버 점검 중일 수 있습니다.",
                latest_shot,
            )

        return success

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        print(f"❌ 예외 발생: {error_msg}")
        screenshots = sorted(SCREENSHOT_DIR.glob("*.png")) if SCREENSHOT_DIR.exists() else []
        latest_shot = screenshots[-1] if screenshots else None
        send_failure_alert(error_msg, latest_shot)
        return False

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        print("🔚 Chrome 드라이버 종료")
