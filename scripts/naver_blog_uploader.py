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
# blogId는 post_to_naver_blog() 호출 시 NAVER_ID로 동적 생성
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
    # 현재 URL이 로그인 페이지면 무조건 비로그인
    if "nidlogin" in driver.current_url or "login" in driver.current_url:
        return False
    try:
        driver.get("https://www.naver.com")
        human_delay(2, 3)
        # 로그아웃 버튼 또는 프로필 영역이 있으면 로그인 상태
        logged_in_els = driver.find_elements(
            By.CSS_SELECTOR,
            ".MyView-module__btn_my___HGNqJ, .gnb_my_nm, #account, .link_logout, [class*='MyView']"
        )
        login_btn = driver.find_elements(By.CSS_SELECTOR, ".link_login, .btn_login")
        print(f"   로그인 확인 — 로그인버튼:{len(login_btn)}, 마이페이지:{len(logged_in_els)}")
        # 로그인 버튼이 없거나 마이페이지가 있으면 로그인 상태
        return len(login_btn) == 0 or len(logged_in_els) > 0
    except Exception as e:
        print(f"   로그인 확인 오류: {e}")
        return False


def naver_login(driver: uc.Chrome) -> bool:
    """
    네이버 ID/PW 로그인.
    영문/한글 셀렉터 모두 시도, JavaScript 입력 주입으로 봇 탐지 우회.
    """
    naver_id = os.environ["NAVER_ID"]
    naver_pw = os.environ["NAVER_PW"]

    driver.get(NAVER_LOGIN_URL)
    human_delay(3, 4)
    _take_screenshot(driver, "login_page")
    print(f"   로그인 페이지 URL: {driver.current_url}")

    try:
        wait = WebDriverWait(driver, 15)

        # 아이디 입력창 — 여러 셀렉터 시도 (영문/한글 UI 모두 대응)
        id_input = None
        for sel in ["#id", "input#id", "input[name='id']",
                    "input[placeholder*='아이디']", "input[placeholder*='ID']",
                    "input[placeholder*='Phone']", "input[type='text']"]:
            try:
                id_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                print(f"   아이디 셀렉터 성공: {sel}")
                break
            except Exception:
                continue

        if not id_input:
            _take_screenshot(driver, "id_input_not_found")
            print("   ❌ 아이디 입력창을 찾을 수 없음")
            return False

        # 실제 키보드 타이핑으로 입력 (JS 주입 차단 우회)
        id_input.click()
        human_delay(0.3, 0.6)
        id_input.send_keys(Keys.CONTROL, "a")  # 기존 내용 지우기
        id_input.send_keys(Keys.DELETE)
        human_delay(0.2, 0.4)
        human_type(id_input, naver_id)
        human_delay(0.8, 1.5)

        # 비밀번호 입력창
        pw_input = None
        for sel in ["#pw", "input#pw", "input[name='pw']",
                    "input[type='password']", "input[placeholder*='비밀번호']",
                    "input[placeholder*='Password']"]:
            try:
                pw_input = driver.find_element(By.CSS_SELECTOR, sel)
                print(f"   비밀번호 셀렉터 성공: {sel}")
                break
            except Exception:
                continue

        if not pw_input:
            _take_screenshot(driver, "pw_input_not_found")
            print("   ❌ 비밀번호 입력창을 찾을 수 없음")
            return False

        # 비밀번호도 실제 타이핑
        pw_input.click()
        human_delay(0.3, 0.6)
        pw_input.send_keys(Keys.CONTROL, "a")
        pw_input.send_keys(Keys.DELETE)
        human_delay(0.2, 0.4)
        human_type(pw_input, naver_pw)
        human_delay(0.8, 1.5)

        # 로그인 버튼
        login_btn = None
        for sel in ["#log\.login", "button[type='submit']",
                    ".btn_login", "button.submit", "#login_btn",
                    "//button[contains(text(),'Sign in')]",
                    "//button[contains(text(),'로그인')]"]:
            try:
                if sel.startswith("//"):
                    login_btn = driver.find_element(By.XPATH, sel)
                else:
                    login_btn = driver.find_element(By.CSS_SELECTOR, sel)
                if login_btn.is_displayed():
                    print(f"   로그인 버튼 셀렉터 성공: {sel}")
                    break
            except Exception:
                login_btn = None

        if login_btn:
            human_delay(0.5, 1)
            login_btn.click()
        else:
            # 엔터키로 제출
            print("   로그인 버튼 미발견 — 엔터키로 제출")
            pw_input.send_keys(Keys.RETURN)

        human_delay(4, 6)
        _take_screenshot(driver, "after_login")
        print(f"   로그인 후 URL: {driver.current_url}")

        # CAPTCHA 감지
        if "captcha" in driver.current_url.lower():
            _take_screenshot(driver, "captcha_detected")
            print("   ⚠️ CAPTCHA 감지됨")
            return False

        if _is_logged_in(driver):
            save_cookies(driver)
            print("   ✅ 네이버 로그인 성공")
            return True
        else:
            _take_screenshot(driver, "login_failed")
            print(f"   ❌ 로그인 실패. 현재 URL: {driver.current_url}")
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


def _try_find_in_iframes(driver, css_selector: str, timeout: int = 10):
    """메인 프레임 + 모든 iframe 안에서 요소 탐색."""
    # 메인 프레임에서 먼저 시도
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
        )
        if el.is_displayed():
            return driver, el
    except Exception:
        pass

    # 각 iframe 안으로 진입해서 탐색
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for iframe in iframes:
        try:
            driver.switch_to.frame(iframe)
            try:
                el = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, css_selector))
                )
                if el.is_displayed():
                    return driver, el
            except Exception:
                pass
            driver.switch_to.default_content()
        except Exception:
            driver.switch_to.default_content()

    return None, None


def upload_to_naver_blog(
    driver: uc.Chrome,
    title: str,
    body_markdown: str,
    tags: list[str],
) -> bool:
    """네이버 블로그 스마트에디터 포스팅 업로드 (iframe 완전 탐색)."""
    print("   📝 블로그 에디터 열기...")
    naver_id = os.environ["NAVER_ID"]

    # 에디터 이동 전 로그인 상태 재확인
    if not _is_logged_in(driver):
        print("   ⚠️ 세션 만료 — 재로그인 시도...")
        if not naver_login(driver):
            print("   ❌ 재로그인 실패")
            return False

    blog_write_url = f"https://blog.naver.com/PostWriteForm.naver?blogId={naver_id}"
    print(f"   에디터 URL: {blog_write_url}")
    driver.get(blog_write_url)
    human_delay(6, 8)
    _take_screenshot(driver, "editor_loaded")
    print(f"   에디터 로드 후 URL: {driver.current_url}")

    # 로그인 페이지로 리다이렉트됐는지 확인
    if "login" in driver.current_url or "nidlogin" in driver.current_url:
        print("   ⚠️ 에디터 이동 후 로그인 페이지로 리다이렉트됨 — 재로그인...")
        if not naver_login(driver):
            return False
        driver.get(blog_write_url)
        human_delay(6, 8)
        _take_screenshot(driver, "editor_reloaded")

    # 페이지 소스에서 iframe 목록 디버그 출력
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    print(f"   iframe 수: {len(iframes)}")
    for i, f in enumerate(iframes):
        print(f"   iframe[{i}] src={f.get_attribute('src')[:80] if f.get_attribute('src') else 'none'}")

    try:
        # ── 제목 입력 ──────────────────────────────────────────────────────
        print("   ✏️  제목 입력 중...")
        title_selectors = [
            ".se-title-input .se-ff-nanumgothic",
            ".se-title-input",
            "input.se-input-title",
            "[placeholder*='제목']",
            "[contenteditable='true'].se-title-input",
            ".se-module-title [contenteditable]",
            "#title",
            "input[name='title']",
        ]

        title_input = None
        used_frame = False

        # 메인 프레임에서 시도
        for sel in title_selectors:
            try:
                el = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                title_input = el
                print(f"   제목 셀렉터 성공 (메인): {sel}")
                break
            except Exception:
                continue

        # 메인에서 못 찾으면 iframe 진입
        if not title_input:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes:
                try:
                    driver.switch_to.frame(iframe)
                    for sel in title_selectors:
                        try:
                            el = WebDriverWait(driver, 3).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                            )
                            title_input = el
                            used_frame = True
                            print(f"   제목 셀렉터 성공 (iframe): {sel}")
                            break
                        except Exception:
                            continue
                    if title_input:
                        break
                    driver.switch_to.default_content()
                except Exception:
                    driver.switch_to.default_content()

        if not title_input:
            # JavaScript로 강제 탐색
            print("   🔄 JavaScript로 제목 입력창 탐색...")
            result = driver.execute_script("""
                const selectors = [
                    '.se-title-input', 'input[placeholder*="제목"]',
                    '[contenteditable].se-title-input', '#title'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.focus();
                        el.click();
                        return sel;
                    }
                }
                // iframe 안까지 탐색
                for (const iframe of document.querySelectorAll('iframe')) {
                    try {
                        const doc = iframe.contentDocument;
                        for (const sel of selectors) {
                            const el = doc.querySelector(sel);
                            if (el) { el.focus(); el.click(); return 'iframe:' + sel; }
                        }
                    } catch(e) {}
                }
                return null;
            """)
            if result:
                print(f"   JS 제목 탐색 결과: {result}")
                human_delay(0.5, 1)
                # 현재 포커스된 요소에 타이핑
                active = driver.switch_to.active_element
                human_type(active, title)
                human_delay(1, 2)
            else:
                _take_screenshot(driver, "title_not_found")
                print("   ❌ 제목 입력창을 찾을 수 없음")
                return False
        else:
            title_input.click()
            human_delay(0.5, 1)
            # contenteditable 요소는 clear() 대신 Ctrl+A → 타이핑
            title_input.send_keys(Keys.CONTROL, "a")
            human_type(title_input, title)
            human_delay(1, 2)

        if used_frame:
            driver.switch_to.default_content()

        # ── 본문 입력 ──────────────────────────────────────────────────────
        print("   📄 본문 입력 중...")
        html_body = markdown_to_naver_html(body_markdown)

        injected = driver.execute_script("""
            // SE3 에디터 API 시도
            try {
                const se = window.__se__;
                if (se && se.editorManager) {
                    se.editorManager.getEditor().setContent(arguments[0]);
                    return 'se3_api';
                }
            } catch(e) {}

            // window 전역 객체에서 에디터 탐색
            for (const key of Object.keys(window)) {
                try {
                    const v = window[key];
                    if (v && typeof v.getEditor === 'function') {
                        v.getEditor().setContent(arguments[0]);
                        return 'global_editor:' + key;
                    }
                } catch(e) {}
            }

            // contenteditable 중 가장 큰 것 (본문 영역)
            const editables = Array.from(document.querySelectorAll('[contenteditable="true"]'));
            const biggest = editables.sort((a,b) =>
                b.getBoundingClientRect().height - a.getBoundingClientRect().height
            )[0];
            if (biggest && biggest.getBoundingClientRect().height > 100) {
                biggest.focus();
                biggest.innerHTML = arguments[0];
                biggest.dispatchEvent(new InputEvent('input', {bubbles: true}));
                return 'contenteditable';
            }

            // iframe 안의 contenteditable
            for (const iframe of document.querySelectorAll('iframe')) {
                try {
                    const doc = iframe.contentDocument;
                    const body = doc.querySelector('[contenteditable="true"]') || doc.body;
                    if (body) {
                        body.focus();
                        doc.execCommand('selectAll');
                        doc.execCommand('insertHTML', false, arguments[0]);
                        return 'iframe_body';
                    }
                } catch(e) {}
            }
            return 'failed';
        """, html_body)
        print(f"   본문 주입 결과: {injected}")
        human_delay(2, 3)

        # ── 태그 입력 ──────────────────────────────────────────────────────
        print("   🏷️  태그 입력 중...")
        driver.switch_to.default_content()
        tag_selectors = [
            "input.tag_input",
            ".se-tag-input input",
            "input[placeholder*='태그']",
            "#tagInput",
            ".tag_area input",
        ]
        tag_input = None
        for sel in tag_selectors:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    tag_input = el
                    break
            except NoSuchElementException:
                continue

        if tag_input:
            tag_input.click()
            human_delay(0.3, 0.7)
            for tag in tags[:10]:
                tag_clean = tag.replace("#", "").strip()
                human_type(tag_input, tag_clean)
                human_delay(0.2, 0.4)
                tag_input.send_keys(Keys.RETURN)
                human_delay(0.3, 0.5)
        else:
            print("   ⚠️ 태그 입력창 없음 — 건너뜀")

        human_delay(1, 2)
        _take_screenshot(driver, "before_publish")

        # ── 발행 버튼 클릭 ──────────────────────────────────────────────────
        print("   🚀 발행 중...")
        driver.switch_to.default_content()

        published = False
        publish_xpaths = [
            "//button[contains(@class,'publish')]",
            "//button[contains(text(),'발행')]",
            "//button[contains(text(),'등록')]",
            "//a[contains(text(),'발행')]",
            "//*[@data-action='publish']",
        ]
        for xpath in publish_xpaths:
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                human_delay(0.5, 1)
                btn.click()
                published = True
                print(f"   ✅ 발행 버튼 클릭 성공: {xpath}")
                break
            except Exception:
                continue

        if not published:
            # JavaScript로 발행 버튼 클릭
            result = driver.execute_script("""
                const btns = Array.from(document.querySelectorAll('button, a'));
                const pub = btns.find(b =>
                    b.textContent.includes('발행') ||
                    b.textContent.includes('등록') ||
                    b.className.includes('publish')
                );
                if (pub) { pub.click(); return pub.textContent.trim(); }
                return null;
            """)
            if result:
                published = True
                print(f"   ✅ JS 발행 버튼 클릭: {result}")
            else:
                _take_screenshot(driver, "publish_btn_not_found")
                print("   ❌ 발행 버튼을 찾을 수 없음")
                return False

        human_delay(3, 5)

        # 추가 확인 팝업 처리
        try:
            confirm = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[contains(text(),'확인') or contains(text(),'발행')]")
                )
            )
            confirm.click()
            human_delay(2, 3)
            print("   ✅ 확인 팝업 처리 완료")
        except TimeoutException:
            pass

        _take_screenshot(driver, "after_publish")
        current_url = driver.current_url
        print(f"   최종 URL: {current_url}")

        if "PostView" in current_url or ("blog.naver.com" in current_url and "write" not in current_url):
            print(f"   ✅ 블로그 업로드 완료!")
            return True
        else:
            print("   ⚠️ URL로 성공 여부 불확실 — 스크린샷 확인 필요")
            return True  # 발행 버튼까지 눌렀으면 일단 성공으로 처리

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
