import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import sys
import subprocess
import shutil
import glob
import tempfile
import webbrowser
import threading
import queue
import asyncio
import json
import os
import re
import time
import csv
import difflib
import html
import hashlib
from datetime import datetime, timezone
def _ensure_packages():
    """ถ้ายังไม่มี requests / playwright ให้ถามแล้วติดตั้งให้อัตโนมัติ"""
    if getattr(sys, "frozen", False):  # โปรแกรมที่แพ็กแล้ว (.exe/.app) มีทุกอย่างในตัวอยู่แล้ว
        return
    missing = []
    for mod in ("requests", "playwright"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return

    ok = True
    try:
        _r = tk.Tk()
        _r.withdraw()
        ok = messagebox.askyesno(
            "ติดตั้งส่วนประกอบ",
            "ยังไม่มี: " + ", ".join(missing) + "\nให้ติดตั้งให้เลยไหม? (ต้องต่ออินเทอร์เน็ต)",
        )
        _r.destroy()
    except Exception:
        pass
    if not ok:
        sys.exit(1)

    print("Installing:", ", ".join(missing))
    rc = subprocess.call([sys.executable, "-m", "pip", "install", *missing])
    if rc != 0:
        try:
            _r = tk.Tk()
            _r.withdraw()
            messagebox.showerror(
                "ติดตั้งไม่สำเร็จ",
                "ติดตั้งอัตโนมัติไม่ได้\nแนะนำให้เปิดด้วย start_windows.bat / start_mac.command แทน\n"
                "หรือพิมพ์เอง: pip install " + " ".join(missing),
            )
            _r.destroy()
        except Exception:
            pass
        sys.exit(1)

    sys.exit(subprocess.call([sys.executable] + sys.argv))


_ensure_packages()
import requests
from playwright.async_api import async_playwright

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# ทุกไฟล์ที่บอทสร้างจะอยู่ในโฟลเดอร์เดียวกับสคริปต์ (ใช้ได้ทั้ง Windows / macOS)
FROZEN = getattr(sys, "frozen", False)
APP_NAME = "FormBot"
APP_VERSION = "1.4.10"

# Windows build เดิมสามารถฝัง browser ไว้กับโปรแกรมได้
# macOS ไม่บังคับ PLAYWRIGHT_BROWSERS_PATH=0 เพราะ Chromium.app ข้างใน
# ทำให้ PyInstaller/lipo มีโอกาส build ล้มเหลวบน Apple Silicon
if FROZEN and IS_WIN:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")


def _data_dir():
    """ที่เก็บไฟล์ของโปรแกรม: โหมดสคริปต์ = โฟลเดอร์เดียวกับสคริปต์ / โปรแกรมที่แพ็กแล้ว = โฟลเดอร์ข้อมูลผู้ใช้"""
    if not FROZEN:
        return os.path.dirname(os.path.abspath(__file__))
    if IS_WIN:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.path.expanduser("~/.local/share")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


BASE_DIR = _data_dir()
CONFIG_FILE = os.path.join(BASE_DIR, "formbot_config.json")
DONE_FILE = os.path.join(BASE_DIR, "formbot_done.json")
SHOT_DIR = os.path.join(BASE_DIR, "screenshots")
SUMMARY_DIR = os.path.join(BASE_DIR, "summaries")
PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profile")
LOG_FILE = os.path.join(BASE_DIR, "formbot.log")
LEARNED_FILE = os.path.join(BASE_DIR, "formbot_learned_answers.json")
LEARNED_TTL_DAYS = 30  # ความจำ AI แบบถาวรหมดอายุอัตโนมัติ
AI_ENGINE_VERSION = "fast-ai-v3"  # เปลี่ยนรุ่น AI = ไม่ใช้ learned cache รุ่นเก่า

MONO_FONT = "Consolas" if IS_WIN else ("Menlo" if IS_MAC else "DejaVu Sans Mono")
UI_FONT = "Tahoma" if IS_WIN else ("Thonburi" if IS_MAC else "Noto Sans Thai")

# Tk บางรุ่น (เช่น macOS เก่า) ไม่มี ttk.Spinbox
Spin = ttk.Spinbox if hasattr(ttk, "Spinbox") else tk.Spinbox

OLLAMA_WIN_URL = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_MAC_URL = "https://ollama.com/download/Ollama-darwin.zip"
OLLAMA_PAGE = "https://ollama.com/download"

OLLAMA_BASE = "http://127.0.0.1:11434"
OLLAMA_URL = OLLAMA_BASE + "/api/generate"
OLLAMA_TAGS_URL = OLLAMA_BASE + "/api/tags"
OLLAMA_PULL_URL = OLLAMA_BASE + "/api/pull"

GOOGLE_LOGIN_URL = "https://accounts.google.com/ServiceLogin?hl=th"
X_LOGIN_URL = "https://x.com/i/flow/login"
GOOGLE_COOKIES = {"SID", "SAPISID", "__Secure-1PSID", "__Secure-3PSID"}
LOGIN_TIMEOUT = 600  # วินาที

INITIAL_EXTRA_SETS = 10  # เริ่มต้น 10 ชุด แต่เพิ่มได้ไม่จำกัด
ART = 'article[data-testid="tweet"]'

PROFILE_FIELDS = [
    ("first_name", "ชื่อ"),
    ("last_name", "นามสกุล"),
    ("nickname", "ชื่อเล่น"),
    ("phone", "เบอร์โทร"),
    ("email", "อีเมล"),
    ("age", "อายุ"),
    ("birthdate", "วันเกิด (YYYY-MM-DD ค.ศ.)"),
    ("address", "ที่อยู่"),
    ("line_id", "Line ID"),
    ("x_handle", "X / Twitter"),
    ("national_id", "เลขบัตรประชาชน (13 หลัก)"),
    ("account", "บัญชี/Username (เช่น ระบบจองบัตร, เกม, สมาชิก)"),
    ("upload_file", "ไฟล์ที่จะแนบ (ที่อยู่ไฟล์ ใช้กับข้ออัปโหลด)"),
]

NAME_MODES = {
    "อัตโนมัติ (ดูว่ามีช่องนามสกุลแยกไหม)": "auto",
    "ชื่อจริงอย่างเดียว": "first",
    "ชื่อ + นามสกุล": "full",
}
NAME_MODE_LABELS = list(NAME_MODES.keys())

MODEL_SUGGESTIONS = [
    "qwen3:8b",      # แนะนำ - จุดคุ้มสุดสำหรับ RAM 16GB ขึ้นไป
    "qwen3.6",       # ฉลาดสุดในกลุ่มที่รันในเครื่องได้ (ต้องการ RAM/VRAM ~32GB)
    "gemma4:12b",    # ทางเลือกสำหรับเครื่อง RAM 16GB
    "gpt-oss:20b",   # เน้นให้เหตุผล (ต้องการเครื่องแรง)
    "qwen2.5:1.5b",  # เครื่องเบา/RAM 8GB
    "qwen3:1.7b",
    "gemma3:1b",
]

# ---- ผู้ให้บริการ AI ----
PROVIDER_LABELS = [
    "Ollama (ในเครื่อง, ฟรี)",
    "OpenRouter API (มีโมเดลฟรี)",
    "Gemini API (Google)",
    "Claude API (Anthropic)",
    "API อื่น (OpenAI-compatible)",
]
PROVIDER_KEYS = {
    PROVIDER_LABELS[0]: "ollama",
    PROVIDER_LABELS[1]: "openrouter",
    PROVIDER_LABELS[2]: "gemini",
    PROVIDER_LABELS[3]: "anthropic",
    PROVIDER_LABELS[4]: "custom",
}

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5-5"]

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS = [
    "openrouter/free",
    "google/gemma-3-27b-it:free",
    "qwen/qwen3-4b:free",
]
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]
OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"

FORM_PATTERN = re.compile(
    r"(docs\.google\.com/forms|forms\.gle|forms\.google\.com|google\.com/forms)",
    re.I,
)
URL_IN_TEXT = re.compile(
    r"(?:https?://)?(?:forms\.gle|docs\.google\.com/forms)[^\s\"'<>]*", re.I
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SRC_LABEL = {
    "fixed": "📌 กำหนดเอง",
    "profile": "👤 โปรไฟล์",
    "ai": "🤖 AI",
    "skip": "⛔ ข้าม",
}

DEFAULT_ANSWERS = """ชุดของ JUMMO เป็นลายอะไร => 
มือและแขนของ Mr. Saturnworld สีอะไร => 
Paody ถืออะไร => 
NilkNhake, Renjin, King Man ใครเป็นน้องใหม่คนล่าสุด => 
MuvMuv สะพายอะไร => 
น้ำพุ สายรุ้ง มะเขือเทศ หูฟัง อะไรอยู่บนหัวของ Tomafox => 
Guinzly เล่นกีฬาอะไร => 
Yuzu Mumu, Samruay, Wesley, Jummo ใครมี 4 ตา => 
Look Khunnoo มีสัญลักษณ์ ♊️ อยู่ที่อวัยวะใด => 
NilkNhake, Neona, Lunar, Nong Nooong ใครสะพายกระเป๋า => 
ห่วงยางของ Avocean สีอะไร => 
หูฟังของ Permpoon สีอะไร => 
GMMTV FANDOM CHARACTER ใดมีส่วนผสมของผึ้ง => 
ศิลปินใน GMMTV ที่คุณชื่นชอบมากที่สุดคือใคร => 
คุณชื่นชอบ GMMTV FANDOM CHARACTER ใดมากที่สุด => 
"""

NOTFOUND_PHRASES = (
    "ไฟล์ที่คุณร้องขอไม่มีอยู่",
    "file you have requested does not exist",
    "sorry, the file you have requested",
)

NEW_DEFAULT_LINES = [
    "ศิลปินใน GMMTV ที่คุณชื่นชอบมากที่สุดคือใคร => ",
    "คุณชื่นชอบ GMMTV FANDOM CHARACTER ใดมากที่สุด => ",
]

SUCCESS_PHRASES = (
    "บันทึกคำตอบของคุณแล้ว",
    "your response has been recorded",
    "ส่งคำตอบอีกครั้ง",
    "submit another response",
)

ERROR_REQUIRED = (
    "คำถามนี้จำเป็น",
    "this is a required question",
)

# เริ่มว่างเพื่อป้องกันข้อมูลคนละเรื่องไปรบกวนคำตอบ AI
# ใส่เฉพาะข้อเท็จจริงที่เกี่ยวกับฟอร์มจริงในแท็บ "คำถาม-คำตอบ"
DEFAULT_KNOWLEDGE = ""

CLOSED_PHRASES = (
    "no longer accepting",
    "ไม่รับคำตอบ",
    "ไม่ได้รับคำตอบ",
)


def _secret_service_name(provider):
    return f"{APP_NAME}:{provider}"

def keychain_get(provider):
    """macOS: อ่าน API key จาก Keychain. แพลตฟอร์มอื่นคืนค่าว่าง."""
    if not IS_MAC:
        return ""
    try:
        p = subprocess.run(
            ["security", "find-generic-password", "-a", provider, "-s", _secret_service_name(provider), "-w"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""

def keychain_set(provider, value):
    """macOS: บันทึก API key ใน Keychain. ค่าว่าง = ลบ."""
    if not IS_MAC:
        return False
    value = (value or "").strip()
    try:
        if not value:
            subprocess.run(
                ["security", "delete-generic-password", "-a", provider, "-s", _secret_service_name(provider)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
            return True
        subprocess.run(
            [
                "security", "add-generic-password",
                "-U", "-a", provider, "-s", _secret_service_name(provider), "-w", value
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5,
        )
        return True
    except Exception:
        return False


def empty_profile():
    return {k: "" for k, _ in PROFILE_FIELDS}


def norm(s):
    """ทำให้ข้อความเทียบกันง่าย: ตัวเล็ก ตัดช่องว่าง/เครื่องหมาย/เลขข้อ"""
    s = (s or "").lower().strip()
    s = re.sub(r"^\d+\s*[\.\)]\s*", "", s)
    s = re.sub(r"[\s\*\?\.,:;!\"'()\[\]\-_/\\|+=&]", "", s)
    return s


def account_label(url):
    part = url.rstrip("/").split("/")[-1].split("?")[0]
    return part or "X"


class FormRun:
    """ข้อมูลของการกรอก 1 ฟอร์ม (ใช้ทำ log แยกแท็ก + ตารางสรุป)"""

    def __init__(self, app, tag, profile, pname):
        self.app = app
        self.tag = tag
        self.profile = profile
        self.pname = pname
        self.rows = []
        self.section = 1
        self.note = ""
        self.url = ""
        self.status = ""
        self.qfull = ""
        self.form_title = ""
        self.page_has_lastname = False

    def log(self, text):
        for line in str(text).split("\n"):
            if line.strip():
                self.app.log(f"[{self.tag}] {line}")

    def add(self, question, answer, source, note="", req=False):
        self.rows.append(
            {
                "sec": self.section,
                "question": question,
                "answer": answer or note,
                "source": source,
                "req": req,
            }
        )


class MonitorState:
    def __init__(self, done_posts, done_forms, sem):
        self.done_posts = done_posts
        self.done_forms = done_forms
        self.sem = sem
        self.tasks = set()
        self.processed = 0  # จำนวนโพสต์ที่ผ่านตัวกรอง (วันที่/คีย์เวิร์ด) แล้วถูกนำไปกรอกฟอร์ม



class AdaptiveAILimiter:
    """ตัวจำกัด AI concurrency ที่ปรับ limit ระหว่างรันได้อย่างปลอดภัย"""
    def __init__(self, limit=4, min_limit=1, max_limit=64):
        self.limit = max(min_limit, min(max_limit, int(limit)))
        self.min_limit = max(1, int(min_limit))
        self.max_limit = max(self.min_limit, int(max_limit))
        self.active = 0
        self._cond = asyncio.Condition()

    async def acquire(self):
        async with self._cond:
            while self.active >= self.limit:
                await self._cond.wait()
            self.active += 1

    async def release(self):
        async with self._cond:
            self.active = max(0, self.active - 1)
            self._cond.notify_all()

    async def set_limit(self, value):
        value = max(self.min_limit, min(self.max_limit, int(value)))
        async with self._cond:
            changed = value != self.limit
            self.limit = value
            self._cond.notify_all()
            return changed

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.release()


class FormBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} - Google Forms AI Assistant  v{APP_VERSION}")
        # Responsive window: fit the current Mac/Windows screen and remain resizable.
        sw = max(800, int(self.root.winfo_screenwidth()))
        sh = max(600, int(self.root.winfo_screenheight()))
        win_w = min(1040, max(700, int(sw * 0.90)))
        win_h = min(900, max(560, int(sh * 0.88)))
        x = max(0, (sw - win_w) // 2)
        y = max(0, (sh - win_h) // 2)
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.root.minsize(680, 540)
        self.root.resizable(True, True)

        self.profiles = [empty_profile() for _ in range(INITIAL_EXTRA_SETS + 1)]
        self.cur_idx = 0
        self.answers_text = DEFAULT_ANSWERS
        self.stop_event = threading.Event()
        self.browser_closed = False
        self.settings = {}
        self.entries = {}
        self.summaries = []
        self.sum_win = None
        self.installed = []
        self.ollama_ok = None
        self.ai_cache = {}
        self.ai_sem = None  # compatibility กับ config/โค้ดรุ่นเก่า
        self.ai_limiter = None
        self.ai_target_limit = 4
        self.ai_success_streak = 0
        self.ai_inflight = {}
        self.learned_answers = self.load_learned()

        # AI Live Status
        self.ai_live_active = {}
        self.ai_live_last = ""

        # สถานะล็อกอิน: None = ยังไม่รู้/กำลังตรวจ, True/False
        self.login = {"google": None, "x": None}
        self.busy = False      # มีการเปิด Browser อยู่ (ล็อกอิน/ตรวจ/รันบอท)
        self.running = False   # บอทกำลังทำงาน

        self.q = queue.Queue()

        try:
            if os.path.getsize(LOG_FILE) > 2_000_000:
                os.remove(LOG_FILE)
        except Exception:
            pass

        self.setup_ui()
        self.load_config()
        self.update_ui_state()
        self.root.after(60, self.poll_ui)
        self.on_provider_changed()
        self.refresh_models()
        self.refresh_setup()
        self.start_check()

    # =========================================================
    # UI queue (thread-safe)
    # =========================================================

    def ui(self, fn, *a, **k):
        self.q.put((fn, a, k))

    def poll_ui(self):
        try:
            while True:
                fn, a, k = self.q.get_nowait()
                try:
                    fn(*a, **k)
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.root.after(60, self.poll_ui)

    # =========================================================
    # GUI
    # =========================================================

    def setup_ui(self):
        # ============ RESPONSIVE ROOT ============
        # Put the whole interface inside a vertical canvas so smaller Mac screens
        # can scroll instead of cutting off controls.
        self.main_canvas = tk.Canvas(self.root, highlightthickness=0, borderwidth=0)
        self.main_scroll = ttk.Scrollbar(
            self.root, orient="vertical", command=self.main_canvas.yview
        )
        self.main_canvas.configure(yscrollcommand=self.main_scroll.set)
        self.main_scroll.pack(side="right", fill="y")
        self.main_canvas.pack(side="left", fill="both", expand=True)

        self.main_content = ttk.Frame(self.main_canvas)
        self.main_window = self.main_canvas.create_window(
            (0, 0), window=self.main_content, anchor="nw"
        )

        def _sync_scrollregion(_e=None):
            self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

        def _fit_content(event):
            self.main_canvas.itemconfigure(self.main_window, width=max(1, event.width))

        self.main_content.bind("<Configure>", _sync_scrollregion)
        self.main_canvas.bind("<Configure>", _fit_content)

        # Mac trackpad / mouse wheel.
        # ไม่แย่ง scroll จากกล่อง Text / ScrolledText ภายในแท็บ
        def _wheel(event):
            w = getattr(event, "widget", None)
            if isinstance(w, tk.Text):
                return
            if event.delta:
                step = -1 if event.delta > 0 else 1
                self.main_canvas.yview_scroll(step * 3, "units")

        self.main_canvas.bind_all("<MouseWheel>", _wheel, add="+")
        parent = self.main_content

        # ============ LOGIN PANEL ============
        lf = ttk.LabelFrame(parent, text=" 🔐 ล็อกอินบัญชี (Google จำเป็น / X จำเป็นเฉพาะโหมดเฝ้าโพสต์) ", padding=8)
        lf.pack(fill="x", padx=12, pady=(10, 4))

        ttk.Label(lf, text="Google:", width=8).grid(row=0, column=0, sticky="w")
        self.lbl_google = tk.Label(lf, text="⏳ กำลังตรวจ...", anchor="w", width=22)
        self.lbl_google.grid(row=0, column=1, sticky="w")
        self.btn_login_g = ttk.Button(
            lf, text="🔑 ล็อกอิน Google", command=lambda: self.start_login("google")
        )
        self.btn_login_g.grid(row=0, column=2, padx=6, pady=2)

        ttk.Label(lf, text="X:", width=8).grid(row=1, column=0, sticky="w")
        self.lbl_x = tk.Label(lf, text="⏳ กำลังตรวจ...", anchor="w", width=22)
        self.lbl_x.grid(row=1, column=1, sticky="w")
        self.btn_login_x = ttk.Button(
            lf, text="🔑 ล็อกอิน X", command=lambda: self.start_login("x")
        )
        self.btn_login_x.grid(row=1, column=2, padx=6, pady=2)

        self.btn_check = ttk.Button(lf, text="🔄 ตรวจสถานะ", command=self.start_check)
        self.btn_check.grid(row=0, column=3, rowspan=2, padx=6)

        self.lock_hint = ttk.Label(lf, text="", foreground="#b45309")
        self.lock_hint.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(
            lf,
            text="บอทไม่เก็บรหัสผ่าน: ล็อกอินเองในหน้าต่าง Browser ที่เปิดขึ้น (รองรับยืนยัน 2 ขั้นตอน) "
                 "แล้วบอทจะตรวจจับและปิดหน้าต่างให้เอง",
            foreground="gray",
            wraplength=720,
        ).grid(row=3, column=0, columnspan=4, sticky="w")

        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True, padx=12, pady=(4, 4))
        self.nb = nb

        # ============ TAB 1 ============
        t1 = ttk.Frame(nb, padding=10)
        nb.add(t1, text="  X & ฟอร์ม  ")

        x_frame = ttk.LabelFrame(
            t1, text=" X (Twitter) เฝ้าโพสต์ใหม่ - หลายบัญชีได้ บรรทัดละ 1 URL ", padding=8
        )
        x_frame.pack(fill="x")

        self.x_text = tk.Text(x_frame, height=3, wrap="none")
        self.x_text.pack(fill="x", pady=(0, 6))

        row = ttk.Frame(x_frame)
        row.pack(fill="x")

        ttk.Label(row, text="รีเฟรชทุก (วินาที, 2-10):").pack(side="left")
        self.interval_var = tk.IntVar(value=5)
        Spin(row, from_=2, to=10, width=4, textvariable=self.interval_var).pack(
            side="left", padx=6
        )

        ttk.Label(row, text="กรอกพร้อมกันสูงสุด (ฟอร์ม):").pack(side="left", padx=(12, 0))
        self.parallel_var = tk.IntVar(value=3)
        # v1.4.2: ปลดล็อกเพดานเดิม 10 ฟอร์ม
        Spin(row, from_=1, to=999, width=5, textvariable=self.parallel_var).pack(
            side="left", padx=6
        )
        ttk.Label(
            row,
            text="(เกิน 10 ได้ — ยิ่งสูงยิ่งใช้ RAM/CPU มาก)",
            foreground="gray",
        ).pack(side="left")

        row2 = ttk.Frame(x_frame)
        row2.pack(fill="x", pady=(6, 0))
        self.run_latest_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            row2, text="ทำโพสต์ล่าสุดที่ยังไม่เคยทำทันที", variable=self.run_latest_var
        ).pack(side="left")

        ttk.Label(row2, text="อายุโพสต์ไม่เกิน (นาที, 0=ไม่จำกัด):").pack(
            side="left", padx=(16, 0)
        )
        self.max_age_var = tk.IntVar(value=3)
        Spin(row2, from_=0, to=60, width=4, textvariable=self.max_age_var).pack(
            side="left", padx=6
        )

        row3 = ttk.Frame(x_frame)
        row3.pack(fill="x", pady=(6, 0))
        ttk.Label(row3, text="คีย์เวิร์ดในโพสต์ (คั่นด้วย , เว้นว่าง=ทุกโพสต์):").pack(
            side="left"
        )
        self.keyword_entry = ttk.Entry(row3)
        self.keyword_entry.pack(side="left", fill="x", expand=True, padx=8)

        ttk.Label(
            x_frame,
            text="* ครั้งแรกให้ล็อกอิน X ใน Browser ที่บอทเปิด (จำไว้ใน chrome_profile)",
            foreground="gray",
        ).pack(anchor="w", pady=(6, 0))

        key_frame = ttk.LabelFrame(t1, text=" 🔑 คีย์วันงาน & จำกัดจำนวนโพสต์ ", padding=8)
        key_frame.pack(fill="x", pady=(8, 0))

        krow1 = ttk.Frame(key_frame)
        krow1.pack(fill="x")
        ttk.Label(krow1, text="คีย์ที่เปิดใช้งาน (เช่น 01 หรือ 01,02 / เว้นว่าง = ทำทุกวัน):").pack(side="left")
        self.keys_entry = ttk.Entry(krow1)
        self.keys_entry.pack(side="left", fill="x", expand=True, padx=8)

        self.notag_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            key_frame, text="ถ้าโพสต์ไม่มีป้ายวันที่ (เช่น 'วันที่ 01') เลย ให้ทำด้วย",
            variable=self.notag_var,
        ).pack(anchor="w", pady=(4, 0))

        krow2 = ttk.Frame(key_frame)
        krow2.pack(fill="x", pady=(6, 0))
        ttk.Label(krow2, text="จำกัดจำนวนโพสต์ที่ทำต่อการรัน (0 = ไม่จำกัด):").pack(side="left")
        self.post_limit_var = tk.IntVar(value=10)
        Spin(krow2, from_=0, to=9999, width=6, textvariable=self.post_limit_var).pack(
            side="left", padx=8
        )
        self.unlock_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            krow2, text="🔓 ปลดล็อก (ไม่จำกัดจำนวนโพสต์)", variable=self.unlock_var
        ).pack(side="left", padx=(16, 0))

        ttk.Label(
            key_frame,
            text="ระบุตัวอย่าง: โพสต์มีข้อความ 'วันที่ 01' คีย์ 01 จะทำ, คีย์ 02 จะข้าม, คีย์ 01,02 จะทำทั้งคู่ "
                 "นับเฉพาะโพสต์ที่ผ่านตัวกรองวันที่/คีย์เวิร์ดแล้วเท่านั้น",
            foreground="gray", wraplength=650, justify="left",
        ).pack(anchor="w", pady=(6, 0))

        url_frame = ttk.LabelFrame(
            t1, text=" Google Form เดี่ยว (ใช้กับปุ่มทดสอบ / เมื่อไม่ใส่ X URL) ", padding=8
        )
        url_frame.pack(fill="x", pady=(8, 0))
        self.url_entry = ttk.Entry(url_frame)
        self.url_entry.pack(fill="x")

        # ============ TAB 2 ============
        t2 = ttk.Frame(nb, padding=10)
        nb.add(t2, text="  ข้อมูลผู้ตอบ  ")

        self.per_form_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            t2,
            text="ใช้ข้อมูลแยกตามลิงก์ (ลิงก์ 1 → ชุด 1, ลิงก์ 2 → ชุด 2 ...) "
                 "/ ปิด = ชุดหลักทุกฟอร์ม",
            variable=self.per_form_var,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(t2, text="แก้ไขชุดข้อมูล").grid(row=1, column=0, sticky="w")

        names = ["ชุดหลัก"] + [f"ชุด {i}" for i in range(1, len(self.profiles))]
        self.set_combo = ttk.Combobox(t2, values=names, state="readonly")
        self.set_combo.current(0)
        self.set_combo.grid(row=1, column=1, sticky="ew", padx=10, pady=3)
        self.set_combo.bind("<<ComboboxSelected>>", self.on_set_changed)

        set_tools = ttk.Frame(t2)
        set_tools.grid(row=1, column=2, sticky="e", pady=3)
        ttk.Button(
            set_tools, text="＋ เพิ่มชุด", command=self.add_profile_set
        ).pack(side="left")
        ttk.Button(
            set_tools, text="🗑 ลบชุด", command=self.delete_profile_set
        ).pack(side="left", padx=(6, 0))

        lm_frame = ttk.LabelFrame(
            t2, text=" กำหนดชุดข้อมูลต่อ 1 ลิงก์เอง (ไม่บังคับ, ใช้แทนกฎด้านบนได้) ", padding=6
        )
        lm_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(4, 10))

        ttk.Label(
            lm_frame,
            justify="left",
            foreground="gray",
            text=(
                "1 บรรทัดต่อ 1 ลิงก์:   เลขลิงก์ => รายชุดข้อมูล (คั่นด้วย , หรือเขียนช่วงด้วย -)\n"
                "ตัวอย่าง  1 => 1-5   หมายถึง ลิงก์ที่ 1 ให้กรอกซ้ำ 5 รอบด้วยชุดข้อมูล 1,2,3,4,5\n"
                "ใช้ * แทนเลขลิงก์ เพื่อใช้กฎเดียวกันกับทุกลิงก์ที่ไม่ได้ระบุไว้ด้านบน / เว้นว่างทั้งหมด = ใช้กฎด้านบนตามปกติ"
            ),
        ).pack(anchor="w")

        self.link_map_box = tk.Text(lm_frame, height=3, wrap="none")
        self.link_map_box.pack(fill="x", pady=(4, 0))

        r = 3
        for key, label in PROFILE_FIELDS:
            ttk.Label(t2, text=label).grid(row=r, column=0, sticky="w", pady=2)
            e = ttk.Entry(t2)
            e.grid(row=r, column=1, sticky="ew", padx=10, pady=2)
            self.entries[key] = e
            r += 1

        ttk.Label(t2, text="เมื่อฟอร์มถามแค่ 'ชื่อ'").grid(
            row=r, column=0, sticky="w", pady=(10, 2)
        )
        self.name_mode_var = tk.StringVar(value=NAME_MODE_LABELS[0])
        ttk.Combobox(
            t2,
            textvariable=self.name_mode_var,
            values=NAME_MODE_LABELS,
            state="readonly",
        ).grid(row=r, column=1, sticky="ew", padx=10, pady=(6, 2))
        r += 1

        ttk.Label(
            t2,
            text="* เพิ่มชุดข้อมูลได้ไม่จำกัดด้วยปุ่ม ＋ เพิ่มชุด / ชุดที่เว้นว่างทั้งหมดจะใช้ชุดหลักแทนอัตโนมัติ",
            foreground="gray",
        ).grid(row=r, column=0, columnspan=3, sticky="w", pady=(5, 0))
        t2.columnconfigure(1, weight=1)

        # ============ TAB 3 ============
        t3 = ttk.Frame(nb, padding=10)
        nb.add(t3, text="  AI & ตัวเลือก  ")

        provider_row = ttk.Frame(t3)
        provider_row.pack(fill="x")
        ttk.Label(provider_row, text="ผู้ให้บริการ AI:").pack(side="left")
        self.provider_var = tk.StringVar(value=PROVIDER_LABELS[0])
        self.provider_combo = ttk.Combobox(
            provider_row, textvariable=self.provider_var, values=PROVIDER_LABELS, state="readonly"
        )
        self.provider_combo.pack(side="left", fill="x", expand=True, padx=8)
        self.provider_combo.bind("<<ComboboxSelected>>", self.on_provider_changed)

        provider_container = ttk.Frame(t3)
        provider_container.pack(fill="x", pady=(8, 0))
        self.provider_container = provider_container

        ai_frame = ttk.LabelFrame(provider_container, text=" Local AI (Ollama) ", padding=8)

        ttk.Label(ai_frame, text="โมเดล:").grid(row=0, column=0, sticky="w")
        self.model_var = tk.StringVar(value="qwen3:8b")
        self.model_combo = ttk.Combobox(
            ai_frame, textvariable=self.model_var, values=MODEL_SUGGESTIONS
        )
        self.model_combo.grid(row=0, column=1, sticky="ew", padx=8)
        self.model_combo.bind("<<ComboboxSelected>>", self.update_model_status)
        self.model_combo.bind("<FocusOut>", self.update_model_status)

        self.btn_pull = ttk.Button(
            ai_frame, text="⬇️ ดาวน์โหลด", command=self.start_pull
        )
        self.btn_pull.grid(row=0, column=2, padx=2)
        ttk.Button(ai_frame, text="🔄", width=3, command=self.refresh_models).grid(
            row=0, column=3, padx=2
        )

        self.pull_bar = ttk.Progressbar(ai_frame, mode="determinate", maximum=100)
        self.pull_bar.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 2))

        self.ai_status = ttk.Label(ai_frame, text="กำลังตรวจ Ollama...", foreground="gray")
        self.ai_status.grid(row=2, column=0, columnspan=4, sticky="w")
        ai_frame.columnconfigure(1, weight=1)

        # ---------- Claude API ----------
        anthropic_frame = ttk.LabelFrame(provider_container, text=" Claude API (Anthropic) ", padding=8)

        ttk.Label(anthropic_frame, text="API key:").grid(row=0, column=0, sticky="w")
        self.anthropic_key_var = tk.StringVar()
        self.anthropic_key_entry = ttk.Entry(
            anthropic_frame, textvariable=self.anthropic_key_var, show="•"
        )
        self.anthropic_key_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.anthropic_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            anthropic_frame, text="แสดง", variable=self.anthropic_show_var,
            command=lambda: self.toggle_key_visibility(self.anthropic_key_entry, self.anthropic_show_var),
        ).grid(row=0, column=2, padx=4)

        ttk.Label(anthropic_frame, text="โมเดล:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.anthropic_model_var = tk.StringVar(value=ANTHROPIC_MODELS[1])
        ttk.Combobox(
            anthropic_frame, textvariable=self.anthropic_model_var, values=ANTHROPIC_MODELS, state="readonly"
        ).grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 0))

        ttk.Label(
            anthropic_frame,
            text="Haiku = เร็ว/ถูกสุด   ·   Sonnet = สมดุล (แนะนำ)   ·   Opus = ฉลาดสุด (แพงกว่า/ช้ากว่า)",
            foreground="gray",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 6))

        self.anthropic_test_btn = ttk.Button(
            anthropic_frame, text="🔌 ทดสอบการเชื่อมต่อ",
            command=lambda: self.start_test_connection("anthropic"),
        )
        self.anthropic_test_btn.grid(row=3, column=0, sticky="w")
        self.anthropic_status = ttk.Label(anthropic_frame, text="", foreground="gray")
        self.anthropic_status.grid(row=3, column=1, columnspan=2, sticky="w", padx=8)

        ttk.Label(
            anthropic_frame,
            text="สมัคร/ดู API key ได้ที่ console.anthropic.com  ·  บน Mac จะเก็บ key ใน Keychain ของระบบ",
            foreground="#b45309", wraplength=650, justify="left",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        anthropic_frame.columnconfigure(1, weight=1)

        # ---------- OpenRouter API ----------
        openrouter_frame = ttk.LabelFrame(
            provider_container, text=" OpenRouter API (มีโมเดลฟรี) ", padding=8
        )
        ttk.Label(openrouter_frame, text="API key:").grid(row=0, column=0, sticky="w")
        self.openrouter_key_var = tk.StringVar()
        self.openrouter_key_entry = ttk.Entry(
            openrouter_frame, textvariable=self.openrouter_key_var, show="•"
        )
        self.openrouter_key_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.openrouter_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            openrouter_frame, text="แสดง", variable=self.openrouter_show_var,
            command=lambda: self.toggle_key_visibility(
                self.openrouter_key_entry, self.openrouter_show_var
            ),
        ).grid(row=0, column=2, padx=4)

        ttk.Label(openrouter_frame, text="โมเดล:").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.openrouter_model_var = tk.StringVar(value=OPENROUTER_MODELS[0])
        ttk.Combobox(
            openrouter_frame,
            textvariable=self.openrouter_model_var,
            values=OPENROUTER_MODELS,
        ).grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 0))

        self.openrouter_test_btn = ttk.Button(
            openrouter_frame, text="🔌 ทดสอบการเชื่อมต่อ",
            command=lambda: self.start_test_connection("openrouter"),
        )
        self.openrouter_test_btn.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.openrouter_status = ttk.Label(openrouter_frame, text="", foreground="gray")
        self.openrouter_status.grid(row=2, column=1, columnspan=2, sticky="w", padx=8)
        ttk.Label(
            openrouter_frame,
            text="เหมาะกับการใช้ API ภายนอกแบบเร็ว ไม่ต้องรันโมเดลบน Mac เอง",
            foreground="gray", wraplength=680, justify="left",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        openrouter_frame.columnconfigure(1, weight=1)

        # ---------- Gemini API ----------
        gemini_frame = ttk.LabelFrame(
            provider_container, text=" Gemini API (Google) ", padding=8
        )
        ttk.Label(gemini_frame, text="API key:").grid(row=0, column=0, sticky="w")
        self.gemini_key_var = tk.StringVar()
        self.gemini_key_entry = ttk.Entry(
            gemini_frame, textvariable=self.gemini_key_var, show="•"
        )
        self.gemini_key_entry.grid(row=0, column=1, sticky="ew", padx=8)
        self.gemini_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            gemini_frame, text="แสดง", variable=self.gemini_show_var,
            command=lambda: self.toggle_key_visibility(
                self.gemini_key_entry, self.gemini_show_var
            ),
        ).grid(row=0, column=2, padx=4)

        ttk.Label(gemini_frame, text="โมเดล:").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.gemini_model_var = tk.StringVar(value=GEMINI_MODELS[0])
        ttk.Combobox(
            gemini_frame,
            textvariable=self.gemini_model_var,
            values=GEMINI_MODELS,
        ).grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 0))

        self.gemini_test_btn = ttk.Button(
            gemini_frame, text="🔌 ทดสอบการเชื่อมต่อ",
            command=lambda: self.start_test_connection("gemini"),
        )
        self.gemini_test_btn.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.gemini_status = ttk.Label(gemini_frame, text="", foreground="gray")
        self.gemini_status.grid(row=2, column=1, columnspan=2, sticky="w", padx=8)
        ttk.Label(
            gemini_frame,
            text="แนะนำ: gemini-3.5-flash-lite สำหรับงานฟอร์มที่ต้องการความเร็ว/จำนวนมาก",
            foreground="gray",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        gemini_frame.columnconfigure(1, weight=1)

        # ---------- Custom / OpenAI-compatible API ----------
        custom_frame = ttk.LabelFrame(provider_container, text=" API อื่น (OpenAI-compatible เช่น OpenAI / Groq) ", padding=8)

        ttk.Label(custom_frame, text="Base URL:").grid(row=0, column=0, sticky="w")
        self.custom_base_var = tk.StringVar(value=OPENAI_DEFAULT_BASE)
        ttk.Entry(custom_frame, textvariable=self.custom_base_var).grid(
            row=0, column=1, sticky="ew", padx=8
        )

        ttk.Label(custom_frame, text="API key:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.custom_key_var = tk.StringVar()
        self.custom_key_entry = ttk.Entry(custom_frame, textvariable=self.custom_key_var, show="•")
        self.custom_key_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 0))
        self.custom_show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            custom_frame, text="แสดง", variable=self.custom_show_var,
            command=lambda: self.toggle_key_visibility(self.custom_key_entry, self.custom_show_var),
        ).grid(row=1, column=2, padx=4, pady=(6, 0))

        ttk.Label(custom_frame, text="ชื่อโมเดล:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.custom_model_var = tk.StringVar()
        ttk.Entry(custom_frame, textvariable=self.custom_model_var).grid(
            row=2, column=1, sticky="ew", padx=8, pady=(6, 0)
        )
        ttk.Label(custom_frame, text="เช่น gpt-4o-mini", foreground="gray").grid(
            row=2, column=2, sticky="w", pady=(6, 0)
        )

        self.custom_test_btn = ttk.Button(
            custom_frame, text="🔌 ทดสอบการเชื่อมต่อ",
            command=lambda: self.start_test_connection("custom"),
        )
        self.custom_test_btn.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.custom_status = ttk.Label(custom_frame, text="", foreground="gray")
        self.custom_status.grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=(6, 0))

        ttk.Label(
            custom_frame,
            text="ใส่ Base URL และชื่อโมเดลให้ตรงกับผู้ให้บริการนั้นๆ  ·  บน Mac จะเก็บ key ใน Keychain ของระบบ",
            foreground="#b45309", wraplength=650, justify="left",
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        custom_frame.columnconfigure(1, weight=1)

        self.provider_frames = {
            "ollama": ai_frame,
            "openrouter": openrouter_frame,
            "gemini": gemini_frame,
            "anthropic": anthropic_frame,
            "custom": custom_frame,
        }
        ai_frame.pack(fill="x")

        opt = ttk.LabelFrame(t3, text=" ตัวเลือก ", padding=8)
        opt.pack(fill="x", pady=(8, 0))

        self.headless_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="ซ่อน Browser", variable=self.headless_var).pack(
            side="left"
        )
        self.shot_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="เก็บภาพหน้าจอ", variable=self.shot_var).pack(
            side="left", padx=12
        )

        sub = ttk.LabelFrame(t3, text=" การส่งฟอร์ม & AI ", padding=8)
        sub.pack(fill="x", pady=(8, 0))

        self.auto_submit_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            sub,
            text="กดส่งอัตโนมัติเมื่อกรอกครบ (v1.4.7 จะลองกดซ้ำ/force click ถ้าปุ่มส่งมีปัญหา)",
            variable=self.auto_submit_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(sub, text="หน่วงก่อนกดส่ง (วินาที):").grid(row=1, column=0, sticky="w", pady=4)
        self.submit_delay_var = tk.IntVar(value=2)
        Spin(sub, from_=0, to=30, width=4, textvariable=self.submit_delay_var).grid(
            row=1, column=1, sticky="w", padx=6
        )
        ttk.Label(sub, text="(กดหยุดเพื่อยกเลิกก่อนส่งได้)", foreground="gray").grid(
            row=1, column=2, sticky="w"
        )

        self.ai_all_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            sub,
            text="เปิดใช้ AI สำหรับคำถามที่ยังไม่มีคำตอบ",
            variable=self.ai_all_var,
        ).grid(row=2, column=0, columnspan=3, sticky="w")

        # คงตัวแปรเดิมไว้เพื่อให้ config รุ่นเก่าเปิดได้ แต่ v1.2 ใช้ Smart AI เสมอ:
        # คำตอบที่กำหนด = ส่งเป็นข้อมูลอ้างอิงให้ AI, โปรไฟล์ = กรอกตรง, ข้อไม่รู้ = AI อ่านก่อนตอบ
        self.ai_read_every_var = tk.BooleanVar(value=True)
        ttk.Label(
            sub,
            text="⚡ Smart AI: ส่งคำถาม+บริบท+คำตอบอ้างอิงให้ AI วิเคราะห์ | ถ้ารอบแรกต่างกันให้ Judge เลือกคำตอบสุดท้าย",
            foreground="#15803d",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(3, 0))

        self.ai_verify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            sub,
            text="⚡ v1.4.10 Fast AI + Submit Detector V2",
            variable=self.ai_verify_var,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(3, 0))

        ai_mode_row = ttk.Frame(sub)
        ai_mode_row.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(ai_mode_row, text="โหมด AI:").pack(side="left")
        self.ai_mode_var = tk.StringVar(value="⚡ Fast (แนะนำ)")
        ttk.Combobox(
            ai_mode_row,
            textvariable=self.ai_mode_var,
            values=["⚡ Fast (แนะนำ)", "🛡️ Accurate"],
            state="readonly",
            width=20,
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            ai_mode_row,
            text="Fast = 1 รอบก่อน / Judge เฉพาะเมื่อจำเป็น",
            foreground="gray",
        ).pack(side="left", padx=(8, 0))

        ai_perf_row = ttk.Frame(sub)
        ai_perf_row.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(ai_perf_row, text="AI พร้อมกันสูงสุด:").pack(side="left")
        self.ai_concurrency_var = tk.IntVar(value=12)
        Spin(
            ai_perf_row,
            from_=1,
            to=64,
            width=4,
            textvariable=self.ai_concurrency_var,
        ).pack(side="left", padx=(6, 10))
        self.ai_auto_tune_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ai_perf_row,
            text="ปรับอัตโนมัติเมื่อ 429 / timeout",
            variable=self.ai_auto_tune_var,
        ).pack(side="left")
        ttk.Label(
            ai_perf_row,
            text="(เช่น 12 → 9 → 6 และค่อยเพิ่มกลับเมื่อ API เสถียร)",
            foreground="gray",
        ).pack(side="left", padx=(8, 0))

        tools = ttk.Frame(t3)
        tools.pack(fill="x", pady=(8, 0))
        ttk.Button(
            tools, text="✏️ ไปแท็บ คำถาม-คำตอบ", command=self.open_answers_editor
        ).pack(side="left")
        ttk.Button(
            tools, text="🗑️ ล้างประวัติที่ทำแล้ว", command=self.clear_history
        ).pack(side="left", padx=8)
        ttk.Button(
            tools, text="🧠 ล้างความจำ AI", command=self.clear_learned_answers
        ).pack(side="left")
        ttk.Button(tools, text="💾 บันทึกข้อมูล", command=self.save_config).pack(
            side="right"
        )

        # ============ TAB 4 : คำถาม-คำตอบ ============
        t4 = ttk.Frame(nb, padding=10)
        nb.add(t4, text="  คำถาม-คำตอบ  ")
        self.tab_qa = t4

        ttk.Label(
            t4,
            justify="left",
            text=(
                "ตั้งคำตอบล่วงหน้า 1 บรรทัดต่อ 1 คำถาม:   คำถาม => คำตอบ\n"
                "• ถ้ามีคำตอบด้านล่าง บอทจะส่ง คำถาม + คำตอบอ้างอิง ให้ AI อ่านก่อน แล้วค่อยตอบ\n"
                "• ข้อตัวเลือกให้พิมพ์ข้อความตัวเลือก / ติ๊กหลายข้อคั่นด้วย |   "
                "• ย่อคำถามเหลือคำสำคัญได้"
            ),
        ).pack(anchor="w")

        self.answers_box = scrolledtext.ScrolledText(
            t4, wrap="word", font=(UI_FONT, 10), height=9
        )
        self.answers_box.pack(fill="both", expand=True, pady=6)
        self.answers_box.insert("1.0", self.answers_text)

        kb_frame = ttk.LabelFrame(
            t4, text=" ความรู้พื้นฐานสำหรับ AI เช่น เรื่อง GMMTV (ไม่บังคับ) ", padding=6
        )
        kb_frame.pack(fill="x", pady=(0, 6))
        ttk.Label(
            kb_frame, foreground="gray", justify="left",
            text="ข้อมูลพื้นฐาน/ข้อเท็จจริงที่ AI ควรรู้ไว้ล่วงหน้า (คนละส่วนกับคำถาม-คำตอบด้านบน) "
                 "AI จะใช้ประกอบการตอบข้อที่ไม่ได้กำหนดคำตอบไว้ ใส่เฉพาะสิ่งที่มั่นใจว่าถูกต้อง เพราะถ้าผิดจะทำให้ตอบฟอร์มผิดไปด้วย",
        ).pack(anchor="w")
        self.knowledge_box = scrolledtext.ScrolledText(
            kb_frame, wrap="word", font=(UI_FONT, 10), height=6
        )
        self.knowledge_box.pack(fill="x", pady=(4, 0))
        self.knowledge_box.insert("1.0", DEFAULT_KNOWLEDGE)

        tf = ttk.Frame(t4)
        tf.pack(fill="x")
        ttk.Label(tf, text="ทดสอบจับคู่:").pack(side="left")
        self.qa_test_entry = ttk.Entry(tf)
        self.qa_test_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(tf, text="ทดสอบ", command=self.test_qa_match).pack(side="left")
        self.qa_result = ttk.Label(t4, text="", justify="left", wraplength=700, foreground="gray")
        self.qa_result.pack(anchor="w", pady=(4, 0))

        # ============ TAB 5 : ติดตั้ง / ตรวจระบบ ============
        t5 = ttk.Frame(nb, padding=10)
        nb.add(t5, text="  ติดตั้ง/ตรวจระบบ  ")

        self.setup_state = {"browser": None, "ollama": None, "model": None}
        self.setup_data = None
        self.setup_lbls = {}

        def setup_row(r, title, key, btn_text, cmd):
            ttk.Label(t5, text=title, width=16).grid(row=r, column=0, sticky="w", pady=4)
            lbl = tk.Label(t5, text="⏳ กำลังตรวจ...", anchor="w", width=44)
            lbl.grid(row=r, column=1, sticky="w")
            self.setup_lbls[key] = lbl
            b = ttk.Button(t5, text=btn_text, command=cmd)
            b.grid(row=r, column=2, padx=6, sticky="ew")
            return b

        self.btn_inst_browser = setup_row(
            0, "Browser", "browser", "🧰 ติดตั้ง Browser", self.install_browser
        )
        self.btn_ollama = setup_row(
            1, "Ollama (AI)", "ollama", "🛠️ ติดตั้ง/เปิด Ollama", self.install_ollama
        )
        self.btn_model_setup = setup_row(
            2, "โมเดล AI", "model", "⬇️ ดาวน์โหลดโมเดล", self.start_pull
        )

        ttk.Label(t5, text="ล็อกอิน Google / X", width=16).grid(row=3, column=0, sticky="w", pady=4)
        self.lbl_setup_login = tk.Label(t5, text="", anchor="w", width=44)
        self.lbl_setup_login.grid(row=3, column=1, sticky="w")
        ttk.Button(t5, text="🔍 ตรวจความพร้อมทั้งหมด", command=self.refresh_setup).grid(
            row=3, column=2, padx=6, sticky="ew"
        )

        self.setup_bar = ttk.Progressbar(t5, mode="determinate", maximum=100)
        self.setup_bar.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 2))
        self.setup_status = ttk.Label(t5, text="", foreground="gray", wraplength=700, justify="left")
        self.setup_status.grid(row=5, column=0, columnspan=3, sticky="w")
        self.setup_summary = ttk.Label(t5, text="", wraplength=700, justify="left")
        self.setup_summary.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        t5.columnconfigure(1, weight=1)

        # ============ AI LIVE STATUS ============
        ai_live_frame = ttk.LabelFrame(parent, text=" 🤖 AI Live ", padding=8)
        ai_live_frame.pack(fill="x", padx=12, pady=(6, 2))

        self.ai_live_title = tk.Label(
            ai_live_frame,
            text="⚪ AI ว่าง — ยังไม่มีคำถามที่ต้องใช้ AI",
            anchor="w",
            justify="left",
            font=(UI_FONT, 10, "bold"),
            fg="#6b7280",
        )
        self.ai_live_title.pack(fill="x")

        self.ai_live_detail = tk.Label(
            ai_live_frame,
            text="ข้อที่ต้องใช้ AI จะขึ้นตรงนี้ว่า AI กำลังตอบอะไรอยู่",
            anchor="w",
            justify="left",
            wraplength=900,
            fg="#6b7280",
        )
        self.ai_live_detail.pack(fill="x", pady=(3, 0))

        # ============ Buttons ============
        btns = ttk.Frame(parent)
        btns.pack(pady=6)

        self.btn_start = ttk.Button(btns, text="▶️ เริ่มทำงาน", command=self.start_bot_thread)
        self.btn_start.pack(side="left", padx=4)

        self.btn_dry = ttk.Button(
            btns, text="🧪 ทดสอบ (Dry run)", command=self.start_dry_run
        )
        self.btn_dry.pack(side="left", padx=4)

        self.btn_stop = ttk.Button(
            btns, text="⏹️ หยุด", command=self.stop_bot, state="disabled"
        )
        self.btn_stop.pack(side="left", padx=4)

        ttk.Button(
            btns, text="📊 ดูสรุป", command=lambda: self.show_summary(True)
        ).pack(side="left", padx=4)

        # ============ Log ============
        log_frame = ttk.LabelFrame(parent, text=" Log ", padding=8)
        log_frame.pack(fill="both", expand=True, padx=12, pady=6)

        self.log_area = scrolledtext.ScrolledText(
            log_frame, wrap="word", height=7, state="disabled", font=(MONO_FONT, 9)
        )
        self.log_area.pack(fill="both", expand=True)

    # =========================================================
    # AI LIVE STATUS
    # =========================================================

    def _refresh_ai_live_ui(self):
        if not hasattr(self, "ai_live_title"):
            return

        active = list(self.ai_live_active.values())
        if active:
            count = len(active)
            self.ai_live_title.config(
                text=f"🤖 AI กำลังตอบ {count} ข้อ...",
                fg="#b45309",
            )
            shown = active[-6:]
            lines = []
            for item in shown:
                tag = item.get("tag") or "ฟอร์ม"
                kind = item.get("kind") or "AI"
                q = (item.get("question") or "").strip()
                if len(q) > 160:
                    q = q[:157] + "..."
                lines.append(f"• [{tag}] {kind}: {q}")
            if count > len(shown):
                lines.insert(0, f"… และอีก {count - len(shown)} ข้อ")
            self.ai_live_detail.config(
                text="\n".join(lines),
                fg="#92400e",
            )
            return

        if self.ai_live_last:
            self.ai_live_title.config(
                text="✅ AI ทำงานเสร็จแล้ว",
                fg="#15803d",
            )
            self.ai_live_detail.config(
                text=self.ai_live_last,
                fg="#166534",
            )
        else:
            self.ai_live_title.config(
                text="⚪ AI ว่าง — ยังไม่มีคำถามที่ต้องใช้ AI",
                fg="#6b7280",
            )
            self.ai_live_detail.config(
                text="ข้อที่ต้องใช้ AI จะขึ้นตรงนี้ว่า AI กำลังตอบอะไรอยู่",
                fg="#6b7280",
            )

    def _ai_live_start_ui(self, key, tag, question, kind):
        self.ai_live_active[key] = {
            "tag": tag,
            "question": question,
            "kind": kind,
        }
        self._refresh_ai_live_ui()

    def _ai_live_finish_ui(self, key, question, answer, ok, note):
        self.ai_live_active.pop(key, None)
        q = (question or "").strip()
        if len(q) > 140:
            q = q[:137] + "..."

        if ok and answer:
            a = str(answer).strip().replace("\n", " ")
            if len(a) > 140:
                a = a[:137] + "..."
            self.ai_live_last = f"คำถาม: {q}\nคำตอบ AI: {a}"
        else:
            n = (note or "AI ไม่ได้คำตอบที่มั่นใจพอ").strip().replace("\n", " ")
            if len(n) > 150:
                n = n[:147] + "..."
            self.ai_live_last = f"คำถาม: {q}\nไม่ได้กรอก: {n}"

        self._refresh_ai_live_ui()

    def ai_live_start(self, run, question, kind="คำถาม"):
        key = f"{getattr(run, 'tag', 'form')}:{time.time_ns()}"
        self.ui(
            self._ai_live_start_ui,
            key,
            getattr(run, "tag", "ฟอร์ม"),
            question,
            kind,
        )
        return key

    def ai_live_finish(self, key, question, answer="", ok=False, note=""):
        self.ui(
            self._ai_live_finish_ui,
            key,
            question,
            answer,
            ok,
            note,
        )

    # =========================================================
    # PROFILE SETS
    # =========================================================

    def commit_current_profile(self):
        self.profiles[self.cur_idx] = {
            k: self.entries[k].get() for k, _ in PROFILE_FIELDS
        }

    def show_profile(self, idx):
        p = self.profiles[idx]
        for k, _ in PROFILE_FIELDS:
            self.entries[k].delete(0, tk.END)
            self.entries[k].insert(0, p.get(k, ""))

    def refresh_profile_combo(self, select_idx=None):
        """รีเฟรชรายชื่อชุดข้อมูลตามจำนวนจริงใน self.profiles"""
        names = ["ชุดหลัก"] + [f"ชุด {i}" for i in range(1, len(self.profiles))]
        self.set_combo["values"] = names
        if select_idx is None:
            select_idx = min(self.cur_idx, len(self.profiles) - 1)
        select_idx = max(0, min(select_idx, len(self.profiles) - 1))
        self.set_combo.current(select_idx)

    def add_profile_set(self):
        """เพิ่มชุดข้อมูลใหม่ได้เรื่อย ๆ โดยไม่มีเพดานตายตัว"""
        self.commit_current_profile()
        self.profiles.append(empty_profile())
        self.cur_idx = len(self.profiles) - 1
        self.refresh_profile_combo(self.cur_idx)
        self.show_profile(self.cur_idx)

    def delete_profile_set(self):
        """ลบได้เฉพาะชุดท้ายสุด เพื่อไม่ให้เลขชุด/mapping ของชุดอื่นเลื่อนผิดคน"""
        idx = self.set_combo.current()
        if idx <= 0:
            messagebox.showinfo("ข้อมูลผู้ตอบ", "ชุดหลักลบไม่ได้")
            return
        self.commit_current_profile()

        last_idx = len(self.profiles) - 1
        if idx != last_idx:
            messagebox.showwarning(
                "ป้องกันเลขชุดเลื่อน",
                f"ลบชุด {idx} ตรงกลางไม่ได้ เพราะจะทำให้ชุด {idx + 1} เป็นต้นไปเลื่อนเลข\n"
                "ถ้าต้องการยกเลิกชุดนี้ ให้ล้างข้อมูลในชุดนี้แทน หรือเลือกลบชุดท้ายสุด",
            )
            return

        del self.profiles[idx]
        self.cur_idx = len(self.profiles) - 1
        self.refresh_profile_combo(self.cur_idx)
        self.show_profile(self.cur_idx)

    def on_set_changed(self, _event=None):
        self.commit_current_profile()
        self.cur_idx = self.set_combo.current()
        self.show_profile(self.cur_idx)

    @staticmethod
    def profile_is_empty(p):
        return not any((v or "").strip() for v in p.values())

    def pick_profile(self, link_no, settings):
        """link_no เริ่มจาก 1"""
        profiles = settings["profiles"]
        main = profiles[0]

        if not settings["per_form"]:
            return main, "ชุดหลัก"

        if 1 <= link_no < len(profiles):
            p = profiles[link_no]
            if not self.profile_is_empty(p):
                return p, f"ชุด {link_no}"

        return main, "ชุดหลัก"

    @staticmethod
    def parse_keys(text):
        """แปลงข้อความคีย์ เช่น '01,02' เป็นเซตตัวเลข {1, 2}"""
        keys = set()
        for part in re.split(r"[,\s]+", (text or "").strip()):
            if part.isdigit():
                keys.add(int(part))
        return keys

    @staticmethod
    def extract_post_day(text):
        """หาป้ายวันที่ในข้อความโพสต์ เช่น 'วันที่ 01' หรือ 'Day 1' คืนเป็นเลข หรือ None ถ้าไม่พบ"""
        m = re.search(r"(?:วันที่|วัน|day)\s*0*([0-9]{1,3})\b", text or "", re.I)
        return int(m.group(1)) if m else None

    @staticmethod
    def parse_link_map(text):
        """แปลงข้อความ 'เลขลิงก์ => รายชุดข้อมูล' เป็น dict {เลขลิงก์หรือ None(=*): [เลขชุด, ...]}"""
        result = {}
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or "=>" not in line:
                continue
            key_s, val_s = line.split("=>", 1)
            key_s = key_s.strip()

            key = None if key_s in ("*", "") else None
            if key_s not in ("*", ""):
                m = re.match(r"^\d+$", key_s)
                if not m:
                    continue
                key = int(key_s)

            sets = []
            for part in re.split(r"[,\s]+", val_s.strip()):
                if not part:
                    continue
                m = re.match(r"^(\d+)-(\d+)$", part)
                if m:
                    a, b = int(m.group(1)), int(m.group(2))
                    step = 1 if b >= a else -1
                    sets.extend(range(a, b + step, step))
                elif part.isdigit():
                    sets.append(int(part))

            if sets:
                result[key] = sets

        return result

    def resolve_set(self, idx, settings):
        """คืนชุดที่มีอยู่จริงเท่านั้น; explicit mapping ที่ผิดจะไม่ fallback เป็นชุดหลัก"""
        profiles = settings["profiles"]
        if idx == 0:
            return profiles[0], "ชุดหลัก"
        if 1 <= idx < len(profiles):
            p = profiles[idx]
            if not self.profile_is_empty(p):
                return p, f"ชุด {idx}"
            return None
        return None

    def get_link_profiles(self, link_no, settings):
        """คืน list ของ (profile, label) ที่ใช้กรอกลิงก์นี้"""
        link_map = settings.get("link_map") or {}

        sets = link_map.get(link_no)
        if sets is None:
            sets = link_map.get(None)  # กฎ '*'

        if sets:
            resolved = []
            for idx in sets:
                item = self.resolve_set(idx, settings)
                if item is None:
                    self.log(f"⚠️ mapping ลิงก์ {link_no}: ชุด {idx} ไม่มี/ว่าง → ข้ามชุดนี้")
                    continue
                resolved.append(item)
            return resolved

        return [self.pick_profile(link_no, settings)]

    # =========================================================
    # LOGIN (Google / X)
    # =========================================================

    @staticmethod
    def cookie_status(cookies):
        google = any(
            c.get("name") in GOOGLE_COOKIES and "google." in c.get("domain", "")
            for c in cookies
        )
        x = any(
            c.get("name") == "auth_token"
            and ("x.com" in c.get("domain", "") or "twitter.com" in c.get("domain", ""))
            for c in cookies
        )
        return {"google": google, "x": x}

    async def launch_context(self, p, headless):
        """เปิด Browser ด้วยโปรไฟล์เดียวกันทุกครั้ง (ใช้ Chrome จริงถ้ามี เพื่อให้ Google ยอมให้ล็อกอิน)"""
        if headless:
            win_args = []
        elif IS_MAC:
            win_args = ["--window-size=1400,900", "--window-position=40,40"]
        else:
            win_args = ["--start-maximized"]

        kwargs = dict(
            user_data_dir=PROFILE_DIR,
            headless=headless,
            viewport=None,
            args=win_args + ["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        try:
            return await p.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except Exception:
            return await p.chromium.launch_persistent_context(**kwargs)

    async def check_flow(self):
        async with async_playwright() as p:
            context = await self.launch_context(p, headless=True)
            try:
                return self.cookie_status(await context.cookies())
            finally:
                try:
                    await context.close()
                except Exception:
                    pass

    async def login_flow(self, service):
        url = GOOGLE_LOGIN_URL if service == "google" else X_LOGIN_URL
        name = "Google" if service == "google" else "X"

        async with async_playwright() as p:
            context = await self.launch_context(p, headless=False)
            closed = {"v": False}
            context.on("close", lambda *_: closed.__setitem__("v", True))

            last = None
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                self.log(f"🔑 เปิดหน้าล็อกอิน {name} แล้ว กรุณาล็อกอินให้เสร็จในหน้าต่าง Browser")
                self.log("   (บอทจะตรวจจับเองแล้วปิดหน้าต่างให้ / รอสูงสุด 10 นาที)")

                deadline = time.time() + LOGIN_TIMEOUT
                while time.time() < deadline and not closed["v"]:
                    if not context.pages:  # ผู้ใช้ปิดหน้าต่างแล้ว (macOS ไม่ปิดโปรแกรม Chrome)
                        break
                    try:
                        last = self.cookie_status(await context.cookies())
                    except Exception:
                        break
                    if last.get(service):
                        self.log(f"✅ ตรวจพบการล็อกอิน {name} แล้ว กำลังบันทึก...")
                        await asyncio.sleep(3)  # ให้คุกกี้ถูกบันทึกลงโปรไฟล์
                        try:
                            last = self.cookie_status(await context.cookies())
                        except Exception:
                            pass
                        break
                    await asyncio.sleep(1.5)
                else:
                    if not closed["v"]:
                        self.log(f"⏱️ หมดเวลารอล็อกอิน {name}")
            finally:
                try:
                    await context.close()
                except Exception:
                    pass

            return last

    def start_login(self, service):
        if self.busy:
            return
        self.busy = True
        self.login[service] = None
        self.render_login_labels()
        self.update_ui_state()

        def work():
            res = None
            try:
                res = asyncio.run(self.login_flow(service))
                if not res:
                    res = asyncio.run(self.check_flow())
            except Exception as e:
                self.log(f"❌ ล็อกอินผิดพลาด: {e}")
                try:
                    res = asyncio.run(self.check_flow())
                except Exception:
                    res = {"google": False, "x": False}
            finally:
                self.ui(self.set_login_status, res or {"google": False, "x": False})
                self.ui(self.finish_browser_op)

        threading.Thread(target=work, daemon=True).start()

    def start_check(self):
        if self.busy:
            return
        self.busy = True
        self.login = {"google": None, "x": None}
        self.render_login_labels()
        self.update_ui_state()

        def work():
            res = {"google": False, "x": False}
            try:
                res = asyncio.run(self.check_flow())
            except Exception as e:
                self.log(f"⚠️ ตรวจสถานะล็อกอินไม่สำเร็จ: {e}  (ถ้ายังไม่มี Browser ไปแท็บ ติดตั้ง/ตรวจระบบ)")
            finally:
                self.ui(self.set_login_status, res)
                self.ui(self.finish_browser_op)

        threading.Thread(target=work, daemon=True).start()

    def set_login_status(self, status):
        self.login.update(status)
        self.render_login_labels()
        self.update_ui_state()
        self.render_setup_summary()

    def finish_browser_op(self):
        self.busy = False
        self.running = False
        self.update_ui_state()

    def render_login_labels(self):
        for key, lbl in (("google", self.lbl_google), ("x", self.lbl_x)):
            v = self.login[key]
            if v is None:
                lbl.config(text="⏳ กำลังตรวจ/รอล็อกอิน...", fg="#6b7280")
            elif v:
                lbl.config(text="✅ ล็อกอินแล้ว", fg="#15803d")
            else:
                lbl.config(text="❌ ยังไม่ได้ล็อกอิน", fg="#b91c1c")

    def update_ui_state(self):
        idle = not self.busy
        g, x = self.login["google"], self.login["x"]

        has_x_urls = bool(self.get_x_urls())
        can_start = idle and bool(g) and (bool(x) if has_x_urls else True)
        self.btn_start.config(state="normal" if can_start else "disabled")
        self.btn_dry.config(state="normal" if (idle and g) else "disabled")
        self.btn_stop.config(state="normal" if self.running else "disabled")

        st = "normal" if idle else "disabled"
        for b in (self.btn_inst_browser, self.btn_ollama, self.btn_model_setup):
            b.config(state=st)
        self.btn_login_g.config(state=st)
        self.btn_login_x.config(state=st)
        self.btn_check.config(state=st)

        if self.busy and not self.running:
            hint = "⏳ กำลังใช้ Browser อยู่ กรุณารอสักครู่..."
        elif not idle:
            hint = ""
        elif g is False or (has_x_urls and x is False):
            missing = []
            if g is False:
                missing.append("Google")
            if has_x_urls and x is False:
                missing.append("X")
            hint = f"🔒 ยังกดเริ่มไม่ได้: ต้องล็อกอิน {' และ '.join(missing)} ก่อน"
        else:
            hint = ""
        self.lock_hint.config(text=hint)

    # =========================================================
    # SETUP / INSTALLER
    # =========================================================

    @staticmethod
    def find_chrome():
        cands = []
        if IS_WIN:
            for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(env)
                if base:
                    cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        elif IS_MAC:
            cands += [
                "/Applications/Google Chrome.app",
                os.path.expanduser("~/Applications/Google Chrome.app"),
            ]
        else:
            for n in ("google-chrome", "google-chrome-stable"):
                w = shutil.which(n)
                if w:
                    cands.append(w)
        for c in cands:
            if os.path.exists(c):
                return c
        return None

    @staticmethod
    def playwright_chromium_installed():
        roots = []
        env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if env and env != "0":
            roots.append(env)
        if IS_WIN:
            roots.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"))
        elif IS_MAC:
            roots.append(os.path.expanduser("~/Library/Caches/ms-playwright"))
        else:
            roots.append(os.path.expanduser("~/.cache/ms-playwright"))

        # PLAYWRIGHT_BROWSERS_PATH=0: browser อยู่ข้างในแพ็กเกจ playwright เอง
        # (ทั้งกรณีฝังไว้ตอน build และกรณีดาวน์โหลดทีหลังผ่านปุ่มติดตั้งของโปรแกรม)
        try:
            import playwright as _pw

            roots.append(os.path.dirname(_pw.__file__))
        except Exception:
            pass

        for r in roots:
            if glob.glob(os.path.join(r, "**", "chromium-*"), recursive=True) or glob.glob(
                os.path.join(r, "**", "chromium_headless_shell-*"), recursive=True
            ):
                return True
        return False

    @staticmethod
    def find_ollama():
        p = shutil.which("ollama")
        if p:
            return p
        cands = []
        if IS_WIN:
            local = os.environ.get("LOCALAPPDATA", "")
            cands.append(os.path.join(local, "Programs", "Ollama", "ollama.exe"))
        elif IS_MAC:
            cands += [
                "/Applications/Ollama.app/Contents/Resources/ollama",
                os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama"),
                "/usr/local/bin/ollama",
                "/opt/homebrew/bin/ollama",
            ]
        else:
            cands += ["/usr/local/bin/ollama", "/usr/bin/ollama"]
        for c in cands:
            if os.path.exists(c):
                return c
        return None

    @staticmethod
    def find_mac_ollama_app():
        if not IS_MAC:
            return None
        for c in ("/Applications/Ollama.app", os.path.expanduser("~/Applications/Ollama.app")):
            if os.path.exists(c):
                return c
        return None

    @staticmethod
    def ollama_api_up():
        try:
            requests.get(OLLAMA_TAGS_URL, timeout=2).raise_for_status()
            return True
        except Exception:
            return False

    def refresh_setup(self):
        def work():
            d = {
                "chrome": self.find_chrome(),
                "pw": self.playwright_chromium_installed(),
                "exe": self.find_ollama() or self.find_mac_ollama_app(),
                "api": False,
                "names": [],
            }
            try:
                r = requests.get(OLLAMA_TAGS_URL, timeout=3)
                r.raise_for_status()
                d["names"] = [m["name"] for m in r.json().get("models", [])]
                d["api"] = True
            except Exception:
                pass
            self.ui(self.render_setup, d)

        threading.Thread(target=work, daemon=True).start()

    def render_setup(self, d):
        self.setup_data = d

        if d["chrome"]:
            b_txt, b_ok = "✅ Google Chrome", True
        elif d["pw"]:
            b_txt, b_ok = "✅ Chromium (แนะนำให้ลง Google Chrome เพิ่ม)", True
        else:
            b_txt, b_ok = "❌ ยังไม่มี Browser", False

        provider = self.current_provider_key()

        if provider != "ollama":
            self.set_models(d["names"] if d["api"] else None)
            cfg = self.collect_ai_config()
            ok, msg = self.ai_provider_ready(cfg)
            label = "Claude API" if provider == "anthropic" else "API ภายนอก"
            o_txt, o_ok = f"✅ ใช้ {label} แทน (ไม่ต้องใช้ Ollama)", True
            m_txt, m_ok = (msg, ok)
            for b in (self.btn_ollama, self.btn_model_setup):
                b.config(state="disabled")
        else:
            for b in (self.btn_ollama, self.btn_model_setup):
                b.config(state="normal" if not self.busy else "disabled")

            if d["api"]:
                o_txt, o_ok = "✅ ติดตั้งแล้วและกำลังทำงาน", True
            elif d["exe"]:
                o_txt, o_ok = "⚠️ ติดตั้งแล้ว แต่ยังไม่ได้เปิด (กดปุ่มเพื่อเปิด)", False
            else:
                o_txt, o_ok = "❌ ยังไม่ได้ติดตั้ง (ไม่จำเป็น ถ้ากำหนดคำตอบเองครบ)", False

            self.set_models(d["names"] if d["api"] else None)
            model = self.model_var.get().strip()
            if not d["api"]:
                m_txt, m_ok = "— (ต้องเปิด Ollama ก่อน)", False
            elif self.model_installed(model):
                m_txt, m_ok = f"✅ มีโมเดล {model} แล้ว", True
            else:
                m_txt, m_ok = f"⬇️ ยังไม่มีโมเดล {model}", False

        self.setup_state = {"browser": b_ok, "ollama": o_ok, "model": m_ok}

        for key, txt, ok in (
            ("browser", b_txt, b_ok),
            ("ollama", o_txt, o_ok),
            ("model", m_txt, m_ok),
        ):
            self.setup_lbls[key].config(text=txt, fg="#15803d" if ok else "#b91c1c")

        self.render_setup_summary()

    def render_setup_summary(self):
        if not self.setup_data:
            return

        g, x = self.login["google"], self.login["x"]

        def mark(v):
            return "⏳" if v is None else ("✅" if v else "❌")

        self.lbl_setup_login.config(
            text=f"Google {mark(g)}    X {mark(x)}",
            fg="#15803d" if (g and x) else "#b91c1c",
        )

        need = []
        if not self.setup_state.get("browser"):
            need.append("Browser")
        if g is False:
            need.append("ล็อกอิน Google")
        if x is False:
            need.append("ล็อกอิน X")

        ai_ok = self.setup_state.get("ollama") and self.setup_state.get("model")
        ai_note = "" if ai_ok else "\n(AI ยังไม่พร้อม: ข้อที่ไม่ได้กำหนดคำตอบเองจะถูกข้าม)"

        if need:
            self.setup_summary.config(text="🔴 ยังขาด: " + ", ".join(need) + ai_note, foreground="#b91c1c")
        else:
            self.setup_summary.config(text="🟢 พร้อมใช้งาน" + ai_note, foreground="#15803d")

    def setup_progress(self, pct, text):
        if pct is not None:
            self.setup_bar["value"] = pct
        self.setup_status.config(text=text)

    # ---------- helpers ----------

    def download_file(self, url, dest, label):
        last = -10.0
        with requests.get(url, stream=True, timeout=(10, None)) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100.0 / total
                        self.ui(self.setup_progress, pct, f"{label} {pct:.0f}%")
                        if pct - last >= 10:
                            self.log(f"   {label} {pct:.0f}%")
                            last = pct

    def run_cmd_stream(self, cmd, label, env=None):
        self.log(f"🧰 {label}: {' '.join(cmd)}")
        kw = {}
        if IS_WIN:
            kw["creationflags"] = 0x08000000  # ไม่เปิดหน้าต่างดำ
        p = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kw,
        )
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            self.ui(self.setup_progress, None, line[:120])
            if "%" not in line:
                self.log("   " + line[:160])
        return p.wait()

    def begin_setup_task(self):
        if self.busy:
            return False
        self.busy = True
        self.update_ui_state()
        self.ui(self.setup_progress, 0, "")
        return True

    # ---------- Browser ----------

    @staticmethod
    def playwright_install_cmd(browser="chromium"):
        """คำสั่งติดตั้ง Browser ของ Playwright (โปรแกรมที่แพ็กแล้วต้องเรียกผ่านไดรเวอร์ในตัว ไม่ใช่ python -m)"""
        if not FROZEN:
            return [sys.executable, "-m", "playwright", "install", browser], None

        from playwright._impl._driver import compute_driver_executable, get_driver_env

        drv = compute_driver_executable()
        base = [str(x) for x in drv] if isinstance(drv, (tuple, list)) else [str(drv)]
        env = {**os.environ, **get_driver_env()}
        return base + ["install", browser], env

    def install_browser(self):
        if not self.begin_setup_task():
            return

        def work():
            try:
                cmd, env = self.playwright_install_cmd("chromium")
                rc = self.run_cmd_stream(cmd, "ติดตั้ง Chromium", env=env)
                if rc == 0:
                    self.log("✅ ติดตั้ง Browser เสร็จแล้ว")
                    if not self.find_chrome():
                        self.log("💡 แนะนำให้ติดตั้ง Google Chrome ด้วย (ล็อกอิน Google ผ่านง่ายกว่า)")
                else:
                    self.log(f"❌ ติดตั้ง Browser ไม่สำเร็จ (รหัส {rc}) ตรวจอินเทอร์เน็ตแล้วลองใหม่")
            except Exception as e:
                self.log(f"❌ ติดตั้ง Browser ไม่สำเร็จ: {e}")
            finally:
                self.ui(self.finish_browser_op)
                self.ui(self.refresh_setup)

        threading.Thread(target=work, daemon=True).start()

    # ---------- Ollama ----------

    def start_ollama(self, exe, mac_app):
        if IS_MAC and mac_app:
            subprocess.Popen(["open", "-a", mac_app])
            return
        if IS_WIN:
            app = os.path.join(os.path.dirname(exe), "ollama app.exe") if exe else None
            flags = 0x08000000 | 0x00000008  # NO_WINDOW | DETACHED
            if app and os.path.exists(app):
                cmd = [app]
            else:
                cmd = [exe, "serve"]
            subprocess.Popen(
                cmd,
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            return
        subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def wait_ollama_api(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.ollama_api_up():
                return True
            time.sleep(1)
        return False

    def download_and_install_ollama(self):
        if IS_WIN:
            dest = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
            self.log("⬇️ กำลังดาวน์โหลด Ollama สำหรับ Windows...")
            self.download_file(OLLAMA_WIN_URL, dest, "ดาวน์โหลด Ollama")
            self.log("📦 กำลังติดตั้ง Ollama (รอสักครู่ อาจมีหน้าต่างตัวติดตั้งขึ้นมา)...")
            rc = subprocess.run(
                [dest, "/SILENT", "/NORESTART"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            if rc != 0 and not self.find_ollama():
                self.log(f"❌ ตัวติดตั้งจบด้วยรหัส {rc}")
                return False
            return True

        if IS_MAC:
            dest = os.path.join(tempfile.gettempdir(), "Ollama-darwin.zip")
            self.log("⬇️ กำลังดาวน์โหลด Ollama สำหรับ Mac...")
            self.download_file(OLLAMA_MAC_URL, dest, "ดาวน์โหลด Ollama")

            tmpdir = tempfile.mkdtemp()
            subprocess.run(["ditto", "-x", "-k", dest, tmpdir], check=True)
            apps = glob.glob(os.path.join(tmpdir, "*.app"))
            if not apps:
                self.log("❌ แตกไฟล์ Ollama แล้วไม่พบตัวโปรแกรม")
                return False

            root = "/Applications" if os.access("/Applications", os.W_OK) else os.path.expanduser("~/Applications")
            os.makedirs(root, exist_ok=True)
            target = os.path.join(root, "Ollama.app")
            if os.path.exists(target):
                shutil.rmtree(target, ignore_errors=True)
            subprocess.run(["ditto", apps[0], target], check=True)
            self.log(f"📦 ติดตั้ง Ollama ที่ {target}")
            return True

        self.log("ℹ️ Linux: ติดตั้งด้วยคำสั่ง  curl -fsSL https://ollama.com/install.sh | sh")
        webbrowser.open(OLLAMA_PAGE)
        return False

    def install_ollama(self):
        if self.busy:
            return
        if not messagebox.askyesno(
            "ติดตั้ง / เปิด Ollama",
            "บอทจะดาวน์โหลดและติดตั้ง Ollama จาก ollama.com (ไฟล์ประมาณ 1 GB)\n"
            "ถ้าติดตั้งอยู่แล้ว จะแค่เปิดโปรแกรมให้\n\nดำเนินการต่อไหม?",
        ):
            return
        if not self.begin_setup_task():
            return

        def work():
            try:
                if self.ollama_api_up():
                    self.log("✅ Ollama กำลังทำงานอยู่แล้ว")
                    return

                exe = self.find_ollama()
                mac_app = self.find_mac_ollama_app()

                if not exe and not mac_app:
                    if not self.download_and_install_ollama():
                        self.log(f"ℹ️ ติดตั้งเองได้ที่ {OLLAMA_PAGE}")
                        webbrowser.open(OLLAMA_PAGE)
                        return
                    exe = self.find_ollama()
                    mac_app = self.find_mac_ollama_app()

                if not self.ollama_api_up():
                    self.log("🚀 กำลังเปิด Ollama...")
                    if exe or mac_app:
                        self.start_ollama(exe, mac_app)

                if not self.wait_ollama_api(60):
                    self.log("⚠️ Ollama ยังไม่ตอบสนอง ลองเปิดโปรแกรม Ollama เอง แล้วกด 🔍 ตรวจความพร้อม")
                    return

                self.log("✅ Ollama พร้อมใช้งาน")

                # ถ้ายังไม่มีโมเดลที่เลือก ให้ดาวน์โหลดต่อเลย
                model = self.model_var.get().strip()
                try:
                    r = requests.get(OLLAMA_TAGS_URL, timeout=4)
                    self.installed = [m["name"] for m in r.json().get("models", [])]
                except Exception:
                    pass
                if model and not self.model_installed(model):
                    self.log(f"⬇️ ดาวน์โหลดโมเดล {model} ต่อให้เลย...")
                    self.ui(self.start_pull)
            except Exception as e:
                self.log(f"❌ ติดตั้ง/เปิด Ollama ไม่สำเร็จ: {e}")
                self.log(f"ℹ️ ติดตั้งเองได้ที่ {OLLAMA_PAGE}")
            finally:
                self.ui(self.finish_browser_op)
                self.ui(self.refresh_setup)

        threading.Thread(target=work, daemon=True).start()

    # =========================================================
    # AI PROVIDER (Ollama / Claude API / API อื่น)
    # =========================================================

    @staticmethod
    def toggle_key_visibility(entry, show_var):
        entry.config(show="" if show_var.get() else "•")

    def on_provider_changed(self, _e=None):
        key = PROVIDER_KEYS.get(self.provider_var.get(), "ollama")
        for k, frame in self.provider_frames.items():
            frame.pack_forget()
        self.provider_frames[key].pack(fill="x")
        self.refresh_setup()

    def current_provider_key(self):
        return PROVIDER_KEYS.get(self.provider_var.get(), "ollama")

    def collect_ai_config(self):
        """อ่านค่าตั้งค่า AI ปัจจุบันจากหน้าจอ (ใช้ทั้งตอนเริ่มบอทจริงและตอนกดทดสอบการเชื่อมต่อ)"""
        return {
            "provider": self.current_provider_key(),
            "model": self.model_var.get().strip(),
            "openrouter_key": self.openrouter_key_var.get().strip(),
            "openrouter_model": self.openrouter_model_var.get().strip() or OPENROUTER_MODELS[0],
            "gemini_key": self.gemini_key_var.get().strip(),
            "gemini_model": self.gemini_model_var.get().strip() or GEMINI_MODELS[0],
            "anthropic_key": self.anthropic_key_var.get().strip(),
            "anthropic_model": self.anthropic_model_var.get().strip() or ANTHROPIC_MODELS[1],
            "custom_base": self.custom_base_var.get().strip() or OPENAI_DEFAULT_BASE,
            "custom_key": self.custom_key_var.get().strip(),
            "custom_model": self.custom_model_var.get().strip(),
        }

    def ai_provider_ready(self, cfg):
        """คืน (พร้อมไหม, ข้อความสถานะ)"""
        p = cfg["provider"]
        if p == "ollama":
            return True, ""  # เช็กแยกผ่าน Ollama tags อยู่แล้วใน render_setup
        if p == "openrouter":
            if not cfg.get("openrouter_key"):
                return False, "❌ ยังไม่ได้ใส่ OpenRouter API key"
            return True, f"✅ ใช้ OpenRouter ({cfg.get('openrouter_model')})"
        if p == "gemini":
            if not cfg.get("gemini_key"):
                return False, "❌ ยังไม่ได้ใส่ Gemini API key"
            return True, f"✅ ใช้ Gemini ({cfg.get('gemini_model')})"
        if p == "anthropic":
            if not cfg["anthropic_key"]:
                return False, "❌ ยังไม่ได้ใส่ Anthropic API key"
            return True, f"✅ ใช้ Claude API ({cfg['anthropic_model']})"
        if p == "custom":
            if not cfg["custom_model"]:
                return False, "❌ ยังไม่ได้ใส่ชื่อโมเดล"
            return True, f"✅ ใช้ API ภายนอก ({cfg['custom_model']})"
        return False, "❌ ไม่รู้จักผู้ให้บริการ"

    def start_test_connection(self, provider):
        cfg = self.collect_ai_config()
        cfg["provider"] = provider
        widget_map = {
            "openrouter": (self.openrouter_status, self.openrouter_test_btn),
            "gemini": (self.gemini_status, self.gemini_test_btn),
            "anthropic": (self.anthropic_status, self.anthropic_test_btn),
            "custom": (self.custom_status, self.custom_test_btn),
        }
        lbl, btn = widget_map.get(provider, (self.custom_status, self.custom_test_btn))

        ok, msg = self.ai_provider_ready(cfg)
        if not ok:
            lbl.config(text=msg, foreground="#b91c1c")
            return

        btn.config(state="disabled")
        lbl.config(text="⏳ กำลังทดสอบ...", foreground="gray")

        async def work():
            reply = await self.call_ai(self.log, cfg, "ตอบคำเดียวสั้นๆ ว่า พร้อมใช้งาน", 20)
            return reply

        def run_thread():
            try:
                reply = asyncio.run(work())
            except Exception as e:
                reply = ""
                self.log(f"❌ ทดสอบเชื่อมต่อ AI ไม่สำเร็จ: {e}")

            if reply:
                preview = reply.strip().replace("\n", " ")[:60]
                self.ui(lbl.config, text=f"✅ เชื่อมต่อสำเร็จ: {preview}", foreground="#15803d")
            else:
                self.ui(lbl.config, text="❌ เชื่อมต่อไม่สำเร็จ ดู Log ประกอบ", foreground="#b91c1c")
            self.ui(btn.config, state="normal")

        threading.Thread(target=run_thread, daemon=True).start()

    async def _ai_feedback_success(self, log):
        """ค่อย ๆ เพิ่ม concurrency กลับ เมื่อ API เสถียรหลายคำขอติดต่อกัน"""
        if not self.settings.get("ai_auto_tune", True):
            return
        limiter = self.ai_limiter
        if limiter is None:
            return

        self.ai_success_streak += 1
        if self.ai_success_streak < 12:
            return

        self.ai_success_streak = 0
        target = max(1, int(self.ai_target_limit or 1))
        if limiter.limit < target:
            old = limiter.limit
            new = min(target, old + 1)
            if await limiter.set_limit(new):
                log(f"📈 AI concurrency ฟื้นตัว: {old} → {new}")

    async def _ai_feedback_failure(self, log, exc):
        """ลด concurrency เฉพาะ error ที่สัมพันธ์กับโหลด/rate limit/เครือข่าย"""
        if not self.settings.get("ai_auto_tune", True):
            return
        limiter = self.ai_limiter
        if limiter is None:
            return

        msg = str(exc or "").lower()
        rate_hit = any(k in msg for k in (
            "429", "rate limit", "too many requests", "จำกัดอัตรา",
            "resource_exhausted", "temporarily unavailable",
        ))
        timeout_hit = any(k in msg for k in (
            "timeout", "timed out", "read timed out", "connect timeout",
            "connectionerror", "connection error", "502", "503", "504",
        ))

        if not (rate_hit or timeout_hit):
            return

        self.ai_success_streak = 0
        old = limiter.limit
        if old <= 1:
            return

        factor = 0.72 if rate_hit else 0.82
        new = max(1, int(old * factor))
        if new >= old:
            new = old - 1

        if await limiter.set_limit(new):
            reason = "429/rate limit" if rate_hit else "timeout/network"
            log(f"📉 ลด AI concurrency อัตโนมัติ ({reason}): {old} → {new}")

    async def call_ai(self, log, cfg, prompt, num_predict):
        """เรียก AI ตามผู้ให้บริการที่ตั้งไว้ log คือฟังก์ชันบันทึก log (run.log หรือ self.log)"""
        provider = cfg.get("provider", "ollama")

        async def _run_post(fn):
            # ตอนกด "ทดสอบการเชื่อมต่อ" ยังไม่มี limiter → เรียกตรง
            limiter = self.ai_limiter
            if limiter is None:
                return await asyncio.to_thread(fn)

            try:
                async with limiter:
                    result = await asyncio.to_thread(fn)
            except Exception as e:
                await self._ai_feedback_failure(log, e)
                raise
            else:
                await self._ai_feedback_success(log)
                return result

        try:
            if provider == "ollama":
                model = cfg.get("model") or "qwen3:8b"

                def _post():
                    r = requests.post(
                        OLLAMA_URL,
                        json={
                            "model": model,
                            "prompt": "/no_think\n" + prompt,
                            "stream": False,
                            "think": False,
                            "keep_alive": "30m",
                            "options": {"temperature": 0.1, "num_predict": num_predict},
                        },
                        timeout=120,
                    )
                    r.raise_for_status()
                    return r.json()["response"]

                raw = await _run_post(_post)
                return re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()

            if provider == "openrouter":
                key = cfg.get("openrouter_key", "").strip()
                model = cfg.get("openrouter_model") or OPENROUTER_MODELS[0]
                if not key:
                    log("❌ ยังไม่ได้ใส่ OpenRouter API key")
                    return ""

                def _post():
                    r = requests.post(
                        f"{OPENROUTER_BASE}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model,
                            "temperature": 0.1,
                            "max_tokens": max(64, num_predict * 2),
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=60,
                    )
                    if r.status_code == 401:
                        raise RuntimeError("OpenRouter API key ไม่ถูกต้อง")
                    if r.status_code == 429:
                        raise RuntimeError("OpenRouter ถูกจำกัดอัตราการเรียก")
                    r.raise_for_status()
                    return r.json()["choices"][0]["message"]["content"]

                return (await _run_post(_post)).strip()

            if provider == "gemini":
                key = cfg.get("gemini_key", "").strip()
                model = cfg.get("gemini_model") or GEMINI_MODELS[0]
                if not key:
                    log("❌ ยังไม่ได้ใส่ Gemini API key")
                    return ""

                def _post():
                    url = f"{GEMINI_BASE}/models/{model}:generateContent"
                    last_exc = None

                    # รอบแรกสั้นเพื่อความเร็ว; timeout/เน็ตสะดุดจึง retry อีกครั้ง
                    for attempt, read_timeout in enumerate((30, 45), start=1):
                        try:
                            r = requests.post(
                                url,
                                headers={
                                    "Content-Type": "application/json",
                                    "x-goog-api-key": key,
                                },
                                json={
                                    "contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {
                                        "maxOutputTokens": max(32, num_predict),
                                    },
                                },
                                timeout=(8, read_timeout),
                            )

                            if r.status_code in (400, 401, 403, 404):
                                try:
                                    detail = r.json().get("error", {}).get("message", "")
                                except Exception:
                                    detail = ""
                                if r.status_code == 404:
                                    msg = f"ไม่พบโมเดล Gemini '{model}' หรือโมเดลนี้ใช้กับ generateContent ไม่ได้"
                                else:
                                    msg = "Gemini API key/โปรเจกต์/สิทธิ์ใช้งานไม่ถูกต้อง"
                                if detail:
                                    msg += f": {detail[:220]}"
                                raise RuntimeError(msg)

                            if r.status_code == 429:
                                raise RuntimeError("Gemini ถูกจำกัดอัตราการเรียกหรือโควตาหมด (rate limit/quota)")

                            r.raise_for_status()
                            data = r.json()
                            cands = data.get("candidates") or []
                            if not cands:
                                return ""
                            parts = cands[0].get("content", {}).get("parts", [])
                            return "".join(p.get("text", "") for p in parts)

                        except (
                            requests.exceptions.ReadTimeout,
                            requests.exceptions.ConnectTimeout,
                            requests.exceptions.ConnectionError,
                        ) as e:
                            last_exc = e
                            if attempt < 2:
                                log("⏱️ Gemini ตอบช้า/เน็ตสะดุด → retry อัตโนมัติ 1 ครั้ง")
                                time.sleep(0.5)
                                continue
                            raise RuntimeError(
                                "Gemini timeout หลัง retry แล้ว — บอทจะข้ามไปใช้ fallback/Judge ถ้ามี"
                            ) from e

                    if last_exc:
                        raise last_exc
                    return ""

                return (await _run_post(_post)).strip()

            if provider == "anthropic":
                key = cfg.get("anthropic_key", "").strip()
                model = cfg.get("anthropic_model") or ANTHROPIC_MODELS[1]
                if not key:
                    log("❌ ยังไม่ได้ใส่ Anthropic API key (แท็บ AI & ตัวเลือก)")
                    return ""

                def _post():
                    r = requests.post(
                        ANTHROPIC_API_URL,
                        headers={
                            "x-api-key": key,
                            "anthropic-version": ANTHROPIC_VERSION,
                            "content-type": "application/json",
                        },
                        json={
                            "model": model,
                            "max_tokens": max(64, num_predict * 2),
                            "temperature": 0.2,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=60,
                    )
                    if r.status_code == 401:
                        raise RuntimeError("API key ไม่ถูกต้องหรือหมดอายุ")
                    if r.status_code == 429:
                        raise RuntimeError("ถูกจำกัดอัตราการเรียก (rate limit) รอสักครู่แล้วลองใหม่")
                    r.raise_for_status()
                    data = r.json()
                    return "".join(
                        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
                    )

                return (await _run_post(_post)).strip()

            if provider == "custom":
                key = cfg.get("custom_key", "").strip()
                base = (cfg.get("custom_base") or OPENAI_DEFAULT_BASE).rstrip("/")
                model = cfg.get("custom_model", "").strip()
                if not model:
                    log("❌ ยังไม่ได้ใส่ชื่อโมเดลของ API ภายนอก (แท็บ AI & ตัวเลือก)")
                    return ""

                def _post():
                    headers = {"Content-Type": "application/json"}
                    if key:
                        headers["Authorization"] = f"Bearer {key}"
                    r = requests.post(
                        f"{base}/chat/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "temperature": 0.2,
                            "max_tokens": max(64, num_predict * 2),
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=60,
                    )
                    if r.status_code == 401:
                        raise RuntimeError("API key ไม่ถูกต้องหรือหมดอายุ")
                    if r.status_code == 429:
                        raise RuntimeError("ถูกจำกัดอัตราการเรียก (rate limit) รอสักครู่แล้วลองใหม่")
                    r.raise_for_status()
                    return r.json()["choices"][0]["message"]["content"]

                return (await _run_post(_post)).strip()

            log(f"❌ ไม่รู้จักผู้ให้บริการ AI: {provider}")
            return ""

        except Exception as e:
            # ป้องกัน API key หลุดใน Log แม้ library/HTTP exception จะพิมพ์ request details
            err = str(e)
            for secret_name in (
                "gemini_key", "openrouter_key", "anthropic_key", "custom_key"
            ):
                secret = str(cfg.get(secret_name, "") or "").strip()
                if secret:
                    err = err.replace(secret, "***REDACTED***")
            log(f"❌ เรียก AI ไม่สำเร็จ ({provider}): {err}")
            return ""

    # =========================================================
    # OLLAMA MODEL MANAGEMENT
    # =========================================================

    def refresh_models(self):
        def work():
            try:
                r = requests.get(OLLAMA_TAGS_URL, timeout=4)
                r.raise_for_status()
                names = [m["name"] for m in r.json().get("models", [])]
                self.ui(self.set_models, names)
            except Exception:
                self.ui(self.set_models, None)

        threading.Thread(target=work, daemon=True).start()

    def set_models(self, names):
        if names is None:
            self.ollama_ok = False
            self.installed = []
        else:
            self.ollama_ok = True
            self.installed = names

        values = list(dict.fromkeys(self.installed + MODEL_SUGGESTIONS))
        self.model_combo["values"] = values
        self.update_model_status()

    def model_installed(self, name):
        name = name.strip()
        if not name:
            return False
        for m in self.installed:
            if m == name or m == name + ":latest":
                return True
            if ":" not in name and m.split(":")[0] == name:
                return True
        return False

    def update_model_status(self, _e=None):
        if self.current_provider_key() != "ollama":
            return
        if self.ollama_ok is None:
            text = "กำลังตรวจ Ollama..."
        elif not self.ollama_ok:
            text = "⚠️ เชื่อมต่อ Ollama ไม่ได้ (เปิดโปรแกรม Ollama ก่อน แล้วกด 🔄)"
        elif self.model_installed(self.model_var.get()):
            text = "✅ โมเดลนี้ติดตั้งแล้ว"
        else:
            text = "⬇️ ยังไม่ได้ดาวน์โหลดโมเดลนี้ กดปุ่ม ดาวน์โหลด"
        self.ai_status.config(text=text)

    def pull_progress(self, pct, text):
        if pct is not None:
            self.pull_bar["value"] = pct
        self.ai_status.config(text=text)

    def start_pull(self):
        if self.current_provider_key() != "ollama":
            return
        name = self.model_var.get().strip()
        if not name:
            messagebox.showwarning("แจ้งเตือน", "กรุณาใส่ชื่อโมเดล")
            return

        self.btn_pull.config(state="disabled")
        self.pull_bar["value"] = 0

        def work():
            self.log(f"⬇️ เริ่มดาวน์โหลดโมเดล {name} (อาจใช้เวลาหลายนาที)")
            last = -10.0
            try:
                with requests.post(
                    OLLAMA_PULL_URL,
                    json={"model": name, "name": name, "stream": True},
                    stream=True,
                    timeout=(10, None),
                ) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line:
                            continue
                        d = json.loads(line)
                        if "error" in d:
                            raise RuntimeError(d["error"])

                        status = d.get("status", "")
                        total = d.get("total")
                        comp = d.get("completed")

                        if total and comp is not None:
                            pct = comp * 100.0 / total
                            self.ui(self.pull_progress, pct, f"{status} {pct:.0f}%")
                            if pct - last >= 10:
                                self.log(f"   {status} {pct:.0f}%")
                                last = pct
                            if pct >= 99.9:
                                last = -10.0
                        else:
                            self.ui(self.pull_progress, None, status)

                self.log(f"✅ ดาวน์โหลด {name} เสร็จแล้ว")
            except Exception as e:
                self.log(f"❌ ดาวน์โหลดไม่สำเร็จ: {e}")
            finally:
                self.ui(self.btn_pull.config, state="normal")
                self.refresh_models()
                self.ui(self.refresh_setup)

        threading.Thread(target=work, daemon=True).start()

    def check_ai_ready(self, s):
        if not s.get("ai_all", True):
            return

        provider = s.get("provider", "ollama")

        if provider == "ollama":
            model = s.get("model", "qwen3:8b")
            try:
                r = requests.get(OLLAMA_TAGS_URL, timeout=4)
                names = [m["name"] for m in r.json().get("models", [])]
                self.installed = names
                if not self.model_installed(model):
                    self.log(
                        f"⚠️ ยังไม่ได้ดาวน์โหลดโมเดล '{model}' "
                        "(ข้อที่ไม่ได้กำหนดคำตอบจะตอบไม่ได้) ไปที่แท็บ AI แล้วกดดาวน์โหลด"
                    )
            except Exception:
                self.log("⚠️ เชื่อมต่อ Ollama ไม่ได้ ข้อที่ต้องใช้ AI จะถูกข้าม")
            return

        if provider == "openrouter" and not s.get("openrouter_key"):
            self.log("⚠️ ยังไม่ได้ใส่ OpenRouter API key (ข้อที่ต้องใช้ AI จะถูกข้าม)")
        elif provider == "gemini" and not s.get("gemini_key"):
            self.log("⚠️ ยังไม่ได้ใส่ Gemini API key (ข้อที่ต้องใช้ AI จะถูกข้าม)")
        elif provider == "anthropic" and not s.get("anthropic_key"):
            self.log("⚠️ ยังไม่ได้ใส่ Claude API key (ข้อที่ต้องใช้ AI จะถูกข้าม)")
        elif provider == "custom" and not s.get("custom_model"):
            self.log("⚠️ ยังไม่ได้ใส่ชื่อโมเดลของ API ภายนอก (ข้อที่ต้องใช้ AI จะถูกข้าม)")

    # =========================================================
    # LEARNED ANSWERS (AI consensus ที่ผ่านการตรวจแล้ว)
    # =========================================================

    @staticmethod
    def load_learned():
        try:
            with open(LEARNED_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def save_learned(data):
        try:
            with open(LEARNED_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def is_volatile_question(question):
        """คำถามที่คำตอบเปลี่ยนตามเวลา ห้ามจำถาวร"""
        q = (question or "").lower()
        return bool(re.search(
            r"วันนี้|ตอนนี้|ล่าสุด|ปัจจุบัน|ขณะนี้|พรุ่งนี้|เมื่อวาน|"
            r"วันที่เท่าไร|กี่โมง|เวลาเท่าไร|ปีนี้|เดือนนี้|สัปดาห์นี้|"
            r"\btoday\b|\bnow\b|\blatest\b|\bcurrent\b|\btomorrow\b|"
            r"\byesterday\b|\bthis\s+(year|month|week)\b|what\s+(time|date)",
            q,
            re.I,
        ))

    def learned_key(self, kind, run, question, choices=None):
        """ผูกความจำกับฟอร์มจริง + URL + บริบท + provider/model"""
        context = norm(getattr(run, "qfull", "") or "")[:1800]
        knowledge = (self.settings.get("knowledge") or "").strip()
        knowledge_sig = hashlib.sha256(knowledge.encode("utf-8")).hexdigest()[:16]
        base = {
            "kind": kind,
            "ai_engine": AI_ENGINE_VERSION,
            "url": (getattr(run, "url", "") or "").strip(),
            "form": norm(getattr(run, "form_title", "") or ""),
            "question": norm(question or ""),
            "context": context,
            "choices": [norm(c) for c in (choices or [])],
            "provider": self.settings.get("provider", "ollama"),
            "model": self._ai_model_cache_id(),
            "knowledge": knowledge_sig,
        }
        raw = json.dumps(base, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_learned(self, kind, run, question, choices=None):
        if self.is_volatile_question(question):
            return None

        k = self.learned_key(kind, run, question, choices)
        item = self.learned_answers.get(k)
        if not item:
            return None

        # v1.3 ไม่มี saved_ts และ key คนละรูปแบบอยู่แล้ว:
        # ถ้าไม่มี timestamp ให้ถือว่าเก่าเพื่อความปลอดภัย
        try:
            saved_ts = float(item.get("saved_ts") or 0)
        except Exception:
            saved_ts = 0

        max_age = LEARNED_TTL_DAYS * 86400
        if not saved_ts or (time.time() - saved_ts) > max_age:
            self.learned_answers.pop(k, None)
            self.save_learned(self.learned_answers)
            return None

        return item

    def put_learned(self, kind, run, question, answer, choices=None):
        if not answer or self.is_volatile_question(question):
            return

        k = self.learned_key(kind, run, question, choices)
        self.learned_answers[k] = {
            "answer": answer,
            "url": getattr(run, "url", "") or "",
            "form": getattr(run, "form_title", "") or "",
            "question": question,
            "context": (getattr(run, "qfull", "") or "")[:1000],
            "choices": list(choices or []),
            "provider": self.settings.get("provider", "ollama"),
            "model": self._ai_model_cache_id(),
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "saved_ts": time.time(),
        }
        self.save_learned(self.learned_answers)

    def clear_learned_answers(self):
        if not messagebox.askyesno(
            "ล้างความจำ AI",
            "ลบคำตอบ AI ที่เคยจำไว้ทั้งหมดหรือไม่?\nคำตอบที่กำหนดเองในแท็บ คำถาม-คำตอบ จะไม่ถูกลบ",
        ):
            return
        self.learned_answers = {}
        self.ai_cache = {}
        try:
            if os.path.exists(LEARNED_FILE):
                os.remove(LEARNED_FILE)
        except Exception:
            pass
        self.log("🧠 ล้างความจำ AI แล้ว")
        messagebox.showinfo("สำเร็จ", "ล้างความจำ AI เรียบร้อย")

    # =========================================================
    # FIXED ANSWERS
    # =========================================================

    @staticmethod
    def parse_fixed(text):
        rules = []
        for line in (text or "").splitlines():
            if "=>" not in line:
                continue
            q, a = line.split("=>", 1)
            qn = norm(q)
            if len(qn) >= 4:
                rules.append((qn, a.strip(), q.strip()))
        return rules

    @staticmethod
    def find_fixed(question, rules):
        """จับคำถามแบบระมัดระวัง เพื่อลดการเอาคำตอบของข้อคล้ายกันมาใส่ผิดข้อ"""
        fq = norm(question)
        if not fq:
            return False, "", "", 0.0

        # 1) ตรงแบบ normalized = เชื่อถือได้ที่สุด
        exact = [(ans, raw) for qn, ans, raw in rules if qn == fq]
        if exact:
            ans, raw = exact[0]
            return True, ans, raw, 1.0

        scored = []
        for qn, ans, raw in rules:
            score = 0.0

            # อนุญาตการย่อคำถามเป็น keyword แต่ต้องยาวพอและกินสัดส่วนข้อความพอสมควร
            if len(qn) >= 6 and (qn in fq or fq in qn):
                shorter = min(len(qn), len(fq))
                longer = max(len(qn), len(fq))
                ratio_len = shorter / max(longer, 1)
                if ratio_len >= 0.45:
                    score = 0.95

            if score == 0.0:
                sim = difflib.SequenceMatcher(None, qn, fq).ratio()
                if sim >= 0.90:
                    score = sim

            if score > 0:
                scored.append((score, ans, raw))

        if not scored:
            return False, "", "", 0.0

        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0]

        # ถ้ามี 2 กฎใกล้กันมากแต่คำตอบต่างกัน ถือว่ากำกวม → ไม่เดา
        if len(scored) > 1:
            second = scored[1]
            if abs(best[0] - second[0]) < 0.025 and norm(best[1]) != norm(second[1]):
                return False, "", best[2], best[0]

        return True, best[1], best[2], best[0]

    def open_answers_editor(self):
        self.nb.select(self.tab_qa)

    def commit_answers(self):
        try:
            self.answers_text = self.answers_box.get("1.0", "end").rstrip("\n") + "\n"
        except Exception:
            pass

    def test_qa_match(self):
        rules = self.parse_fixed(self.answers_box.get("1.0", "end"))
        found, ans, raw, score = self.find_fixed(self.qa_test_entry.get(), rules)

        if found and ans:
            text = f"✅ ตรงกับ: {raw}\n→ คำตอบ: {ans}  (ความคล้าย {score:.0%})"
        elif found:
            text = f"⚠️ ตรงกับ: {raw} แต่ยังไม่ได้ใส่คำตอบ → AI จะอ่านแล้วตอบเอง"
        else:
            text = f"❌ ไม่อยู่ในรายการ (ใกล้สุด {score:.0%}) → AI จะอ่านแล้วตอบเอง"

        self.qa_result.config(text=text)

    # =========================================================
    # LOG / NOTIFY
    # =========================================================

    def _log_now(self, text):
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {text}\n")
        except Exception:
            pass
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, text + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")

    def log(self, text):
        self.ui(self._log_now, text)

    @staticmethod
    def _beep_worker():
        try:
            if IS_WIN:
                import winsound

                for _ in range(3):
                    winsound.Beep(1000, 180)
            elif IS_MAC:
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
        except Exception:
            pass

    def play_alert(self):
        threading.Thread(target=self._beep_worker, daemon=True).start()
        if not (IS_WIN or IS_MAC):
            try:
                self.root.bell()
            except Exception:
                pass

    def notify(self, msg):
        self.log(msg)

        def _n():
            self.play_alert()

            try:
                self.root.deiconify()
                self.root.lift()
                self.root.attributes("-topmost", True)
                self.root.after(1500, lambda: self.root.attributes("-topmost", False))
            except Exception:
                pass

        self.ui(_n)

    # =========================================================
    # CONFIG / HISTORY
    # =========================================================

    def get_x_urls(self):
        return [
            l.strip()
            for l in self.x_text.get("1.0", "end").splitlines()
            if l.strip()
        ]

    def save_config(self, silent=False):
        self.commit_current_profile()

        self.commit_answers()

        # macOS: พยายามเก็บ API keys ใน Keychain
        # ถ้า Keychain ใช้งานไม่ได้ จะคง key ใน config ไว้ก่อนเพื่อไม่ให้ข้อมูลหาย
        _secret_ok = {}
        if IS_MAC:
            for _provider, _value in (
                ("openrouter", self.openrouter_key_var.get()),
                ("gemini", self.gemini_key_var.get()),
                ("anthropic", self.anthropic_key_var.get()),
                ("custom", self.custom_key_var.get()),
            ):
                _secret_ok[_provider] = keychain_set(_provider, _value)
                if _value.strip() and not _secret_ok[_provider]:
                    self.log(f"⚠️ บันทึก {_provider} API key ลง Keychain ไม่สำเร็จ → เก็บใน config ชั่วคราว")

        data = {
            "auto_submit": self.auto_submit_var.get(),
            "submit_delay": self.submit_delay_var.get(),
            "ai_all": self.ai_all_var.get(),
            "ai_read_every": True,
            "ai_verify": self.ai_verify_var.get(),
            "ai_mode": self.ai_mode_var.get(),
            "ai_concurrency": max(1, int(self.ai_concurrency_var.get())),
            "ai_auto_tune": self.ai_auto_tune_var.get(),
            "name_mode_label": self.name_mode_var.get(),
            "answers_version": 2,
            "profiles": self.profiles,
            "model": self.model_var.get(),
            "provider_label": self.provider_var.get(),
            "openrouter_key": "" if (IS_MAC and _secret_ok.get("openrouter")) else self.openrouter_key_var.get(),
            "openrouter_model": self.openrouter_model_var.get(),
            "gemini_key": "" if (IS_MAC and _secret_ok.get("gemini")) else self.gemini_key_var.get(),
            "gemini_model": self.gemini_model_var.get(),
            "anthropic_key": "" if (IS_MAC and _secret_ok.get("anthropic")) else self.anthropic_key_var.get(),
            "anthropic_model": self.anthropic_model_var.get(),
            "custom_base": self.custom_base_var.get(),
            "custom_key": "" if (IS_MAC and _secret_ok.get("custom")) else self.custom_key_var.get(),
            "custom_model": self.custom_model_var.get(),
            "x_urls": self.get_x_urls(),
            "interval": self.interval_var.get(),
            "max_age": self.max_age_var.get(),
            "parallel": self.parallel_var.get(),
            "per_form": self.per_form_var.get(),
            "link_map_text": self.link_map_box.get("1.0", "end").rstrip("\n"),
            "run_latest": self.run_latest_var.get(),
            "keywords": self.keyword_entry.get(),
            "answers_text": self.answers_text,
            "knowledge_text": self.knowledge_box.get("1.0", "end").rstrip("\n"),
            "keys_text": self.keys_entry.get(),
            "notag_process": self.notag_var.get(),
            "post_limit": self.post_limit_var.get(),
            "unlock": self.unlock_var.get(),
            "screenshot": self.shot_var.get(),
            "form_url": self.url_entry.get(),
        }

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            if not silent:
                messagebox.showinfo("สำเร็จ", "บันทึกข้อมูลเรียบร้อย")

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "profiles" in data:
                saved_profiles = data.get("profiles") or []
                if saved_profiles:
                    self.profiles = [
                        {**empty_profile(), **p} for p in saved_profiles
                    ]
                    # อย่างน้อยคงชุดหลักไว้ 1 ชุด
                    if not self.profiles:
                        self.profiles = [empty_profile()]
                    self.cur_idx = 0
                    self.refresh_profile_combo(0)
            else:
                self.profiles[0] = {
                    **empty_profile(),
                    "first_name": data.get("first_name", ""),
                    "last_name": data.get("last_name", ""),
                    "phone": data.get("phone", ""),
                }

            self.show_profile(0)
            self.model_var.set(data.get("model", "qwen3:8b"))
            self.provider_var.set(
                data.get("provider_label")
                if data.get("provider_label") in PROVIDER_LABELS
                else PROVIDER_LABELS[0]
            )
            if IS_MAC:
                _migrated = False
                _loaded_keys = {}
                for _provider, _field in (
                    ("openrouter", "openrouter_key"),
                    ("gemini", "gemini_key"),
                    ("anthropic", "anthropic_key"),
                    ("custom", "custom_key"),
                ):
                    _kc = keychain_get(_provider)
                    _old = str(data.get(_field, "") or "").strip()

                    if not _kc and _old:
                        # migration ครั้งเดียวจาก config รุ่นเก่า → Keychain
                        if keychain_set(_provider, _old):
                            _kc = _old
                            data[_field] = ""
                            _migrated = True
                            self.log(f"🔐 ย้าย {_provider} API key เข้า macOS Keychain แล้ว")
                        else:
                            # Keychain fail: ยังใช้ key เก่าได้ และไม่ลบจาก config
                            _kc = _old
                            self.log(f"⚠️ ย้าย {_provider} API key เข้า Keychain ไม่สำเร็จ → ยังใช้จาก config เดิม")

                    elif _kc and _old:
                        # มีใน Keychain แล้ว ล้าง plaintext เก่าออกจาก config
                        data[_field] = ""
                        _migrated = True

                    _loaded_keys[_provider] = _kc

                if _migrated:
                    try:
                        with open(CONFIG_FILE, "w", encoding="utf-8") as _f:
                            json.dump(data, _f, ensure_ascii=False, indent=2)
                    except Exception as _e:
                        self.log(f"⚠️ ล้าง API key เก่าจาก config ไม่สำเร็จ: {_e}")
            else:
                _loaded_keys = {
                    "openrouter": data.get("openrouter_key", ""),
                    "gemini": data.get("gemini_key", ""),
                    "anthropic": data.get("anthropic_key", ""),
                    "custom": data.get("custom_key", ""),
                }

            self.openrouter_key_var.set(_loaded_keys.get("openrouter", ""))
            self.openrouter_model_var.set(data.get("openrouter_model", OPENROUTER_MODELS[0]))
            self.gemini_key_var.set(_loaded_keys.get("gemini", ""))
            self.gemini_model_var.set(data.get("gemini_model", GEMINI_MODELS[0]))
            self.anthropic_key_var.set(_loaded_keys.get("anthropic", ""))
            self.anthropic_model_var.set(data.get("anthropic_model", ANTHROPIC_MODELS[1]))
            self.custom_base_var.set(data.get("custom_base", OPENAI_DEFAULT_BASE))
            self.custom_key_var.set(_loaded_keys.get("custom", ""))
            self.custom_model_var.set(data.get("custom_model", ""))

            urls = data.get("x_urls")
            if urls is None and data.get("x_url"):
                urls = [data["x_url"]]
            self.x_text.insert("1.0", "\n".join(urls or []))

            self.interval_var.set(data.get("interval", 5))
            self.max_age_var.set(data.get("max_age", 3))
            self.parallel_var.set(data.get("parallel", 3))
            self.per_form_var.set(data.get("per_form", False))
            self.link_map_box.delete("1.0", "end")
            self.link_map_box.insert("1.0", data.get("link_map_text", ""))
            self.run_latest_var.set(data.get("run_latest", False))
            self.keyword_entry.insert(0, data.get("keywords", ""))
            self.shot_var.set(data.get("screenshot", True))
            self.ai_read_every_var.set(True)
            self.ai_verify_var.set(data.get("ai_verify", True))
            self.url_entry.insert(0, data.get("form_url", ""))
            text = data.get("answers_text", DEFAULT_ANSWERS) or DEFAULT_ANSWERS
            if data.get("answers_version", 1) < 2:
                have = {norm(l.split("=>", 1)[0]) for l in text.splitlines() if "=>" in l}
                for line in NEW_DEFAULT_LINES:
                    if norm(line.split("=>", 1)[0]) not in have:
                        text = text.rstrip("\n") + "\n" + line + "\n"
            self.answers_text = text
            self.answers_box.delete("1.0", "end")
            self.answers_box.insert("1.0", self.answers_text)

            self.knowledge_box.delete("1.0", "end")
            _kb = data.get("knowledge_text", DEFAULT_KNOWLEDGE) or ""
            _old_default = 'คู่จิ้น (ศิลปิน 2 คนที่แสดงคู่กันบ่อย) ที่อยู่กับ GMMTV มายาวนานที่สุดคู่หนึ่งคือ คริส-สิงโต (คริส พีรวัส แสงโพธิรัตน์ และ สิงโต ปราชญา เรืองโรจน์) เริ่มมีชื่อเสียงจากซีรีส์ SOTUS ปี 2559-2560 และยังร่วมงานกับ GMMTV ต่อเนื่องถึงปัจจุบัน (2568)'
            if _kb.strip() == _old_default.strip():
                _kb = ""
            self.knowledge_box.insert("1.0", _kb)
            self.keys_entry.insert(0, data.get("keys_text", ""))
            self.notag_var.set(data.get("notag_process", True))
            self.post_limit_var.set(data.get("post_limit", 10))
            self.unlock_var.set(data.get("unlock", False))

            self.auto_submit_var.set(data.get("auto_submit", True))
            self.submit_delay_var.set(data.get("submit_delay", 2))
            self.ai_all_var.set(data.get("ai_all", True))
            self.ai_mode_var.set(data.get("ai_mode", "⚡ Fast (แนะนำ)"))
            self.ai_concurrency_var.set(max(1, int(data.get("ai_concurrency", 12))))
            self.ai_auto_tune_var.set(bool(data.get("ai_auto_tune", True)))
            lab = data.get("name_mode_label", NAME_MODE_LABELS[0])
            self.name_mode_var.set(lab if lab in NAME_MODES else NAME_MODE_LABELS[0])

        except Exception:
            pass

    @staticmethod
    def load_done():
        try:
            with open(DONE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            return set(d.get("posts", [])), set(d.get("forms", []))
        except Exception:
            return set(), set()

    @staticmethod
    def save_done(posts, forms):
        try:
            with open(DONE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {"posts": sorted(posts), "forms": sorted(forms)},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass

    def clear_history(self):
        if messagebox.askyesno(
            "ยืนยัน", "ล้างประวัติโพสต์/ฟอร์มที่ทำแล้วทั้งหมด?\n(มีผลเมื่อกดเริ่มครั้งถัดไป)"
        ):
            try:
                if os.path.exists(DONE_FILE):
                    os.remove(DONE_FILE)
                self.log("🗑️ ล้างประวัติแล้ว")
            except Exception as e:
                messagebox.showerror("Error", str(e))

    # =========================================================
    # SUMMARY
    # =========================================================

    def add_summary(self, run):
        item = {
            "title": f"{run.tag} · {run.pname}",
            "url": run.url,
            "status": run.status,
            "rows": list(run.rows),
        }
        self.summaries.append(item)

        # บันทึก CSV อัตโนมัติ
        try:
            os.makedirs(SUMMARY_DIR, exist_ok=True)
            safe = re.sub(r"[^\w\-]+", "_", run.tag)
            path = os.path.join(SUMMARY_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{safe}.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["section", "question", "answer", "source"])
                for r in run.rows:
                    w.writerow([r["sec"], r["question"], r["answer"], SRC_LABEL[r["source"]]])
        except Exception:
            pass

        self.ui(self.refresh_summary_window)

    def show_summary(self, lift=False):
        if not self.summaries:
            if lift:
                messagebox.showinfo("สรุป", "ยังไม่มีข้อมูลสรุป")
            return

        if self.sum_win is None or not self.sum_win.winfo_exists():
            self.build_summary_window()

        self.refresh_summary_window(select_last=True)

        if lift:
            self.sum_win.deiconify()
            self.sum_win.lift()

    def build_summary_window(self):
        win = tk.Toplevel(self.root)
        win.title("สรุปคำตอบ")
        win.geometry("980x560")
        self.sum_win = win

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text="ฟอร์ม:").pack(side="left")
        self.sum_combo = ttk.Combobox(top, state="readonly", width=60)
        self.sum_combo.pack(side="left", padx=8)
        self.sum_combo.bind("<<ComboboxSelected>>", lambda e: self.render_summary())

        self.sum_info = ttk.Label(win, text="", foreground="gray")
        self.sum_info.pack(anchor="w", padx=12)

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=8)

        cols = ("sec", "q", "a", "src")
        self.sum_tree = ttk.Treeview(frame, columns=cols, show="headings")
        self.sum_tree.heading("sec", text="หน้า")
        self.sum_tree.heading("q", text="คำถาม")
        self.sum_tree.heading("a", text="คำตอบ")
        self.sum_tree.heading("src", text="แหล่งที่มา")
        self.sum_tree.column("sec", width=50, anchor="center")
        self.sum_tree.column("q", width=380)
        self.sum_tree.column("a", width=340)
        self.sum_tree.column("src", width=120)

        self.sum_tree.tag_configure("ai", background="#fff3c4")
        self.sum_tree.tag_configure("skip", background="#ffd6d6")
        self.sum_tree.tag_configure("fixed", background="#dff5e0")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.sum_tree.yview)
        self.sum_tree.configure(yscrollcommand=vsb.set)
        self.sum_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        ttk.Label(
            win,
            text="เหลือง = AI ที่ผ่าน consensus/ตรวจซ้ำ   แดง = ข้าม/ไม่ได้กรอก   เขียว = ใช้คำตอบที่กำหนดเอง   "
                 "| ไฟล์ CSV ถูกบันทึกไว้ในโฟลเดอร์ summaries",
            foreground="gray",
        ).pack(anchor="w", padx=12, pady=(0, 8))

    def refresh_summary_window(self, select_last=False):
        if self.sum_win is None or not self.sum_win.winfo_exists():
            return

        titles = [f"{i + 1}. {s['title']}" for i, s in enumerate(self.summaries)]
        cur = self.sum_combo.current()
        self.sum_combo["values"] = titles

        if select_last or cur < 0:
            self.sum_combo.current(len(titles) - 1)
        else:
            self.sum_combo.current(cur)

        self.render_summary()

    def render_summary(self):
        idx = self.sum_combo.current()
        if idx < 0 or idx >= len(self.summaries):
            return

        item = self.summaries[idx]
        for i in self.sum_tree.get_children():
            self.sum_tree.delete(i)

        counts = {"fixed": 0, "profile": 0, "ai": 0, "skip": 0}
        for r in item["rows"]:
            counts[r["source"]] += 1
            self.sum_tree.insert(
                "",
                "end",
                values=(r["sec"], r["question"] + (" *" if r.get("req") else ""), r["answer"], SRC_LABEL[r["source"]]),
                tags=(r["source"],),
            )

        self.sum_info.config(
            text=(
                f"สถานะ: {item['status'] or '-'}   |   กำหนดเอง {counts['fixed']}  "
                f"โปรไฟล์ {counts['profile']}  AI {counts['ai']}  ข้าม {counts['skip']}   |   {item['url']}"
            )
        )

    # =========================================================
    # LOCAL AI
    # =========================================================

    @staticmethod
    def clean_answer(text, long=False):
        """ตัดคำนำหน้า เช่น 'ตอบ:' 'คำตอบ:' เครื่องหมายคำพูด (long=True เก็บหลายบรรทัดต่อกันเป็นย่อหน้า)"""
        t = (text or "").strip()
        t = re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()

        lines = [l.strip() for l in t.splitlines() if l.strip()]
        t = " ".join(lines)[:500] if long else (lines[0] if lines else "")

        for _ in range(3):
            t2 = re.sub(r"^\s*(คำตอบ|ตอบ|answer)\s*[:：\-–]\s*", "", t, flags=re.I)
            if t2 == t:
                break
            t = t2

        return t.strip().strip("\"'“”‘’`*").strip()

    @staticmethod
    def build_detail(run, title, choices=None):
        """คำอธิบายเพิ่มเติมของข้อ (ตัดชื่อคำถามและตัวเลือกออก)"""
        skip = {norm(title), "ตอบ", "คำตอบของคุณ", "youranswer", "answer"} | {
            norm(c) for c in (choices or [])
        }
        lines = [l.strip() for l in (run.qfull or "").splitlines() if l.strip()]
        extra = [l for l in lines if l != "*" and norm(l) not in skip]
        return "\n".join(extra)[:500]

    async def _generate(self, run, prompt, num_predict):
        """SingleFlight: คำถาม/prompt เดียวกันที่มาพร้อมกัน ใช้ API request เดียว"""
        provider = self.settings.get("provider", "ollama")
        model = self._ai_model_cache_id()
        raw_key = f"{provider}|{model}|{num_predict}|{prompt}"
        key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        existing = self.ai_inflight.get(key)
        if existing is not None:
            run.log("🔗 AI SingleFlight: คำถามเดียวกันกำลังตอบอยู่ → รอผลร่วมกัน")
            return await asyncio.shield(existing)

        task = asyncio.create_task(
            self.call_ai(run.log, self.settings, prompt, num_predict)
        )
        self.ai_inflight[key] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self.ai_inflight.get(key) is task:
                self.ai_inflight.pop(key, None)

    def _ai_model_cache_id(self):
        p = self.settings.get("provider", "ollama")
        if p == "openrouter":
            return self.settings.get("openrouter_model", "")
        if p == "gemini":
            return self.settings.get("gemini_model", "")
        if p == "anthropic":
            return self.settings.get("anthropic_model", "")
        if p == "custom":
            return self.settings.get("custom_model", "")
        return self.settings.get("model", "")

    def _ai_context_key(self, run):
        """กัน cache คำถามชื่อเหมือนกันแต่คนละฟอร์ม/คนละคำอธิบาย"""
        return (
            norm(getattr(run, "form_title", "") or ""),
            norm(getattr(run, "qfull", "") or ""),
            norm((self.settings.get("knowledge") or "")[:1500]),
        )

    @staticmethod
    def _ai_no_answer(raw):
        t = (raw or "").strip().upper().replace(" ", "")
        return t in {
            "__NO_ANSWER__", "NOANSWER", "NO_ANSWER", "UNSURE",
            "ไม่แน่ใจ", "ไม่ทราบ", "ตอบไม่ได้",
        }

    async def _verify_ai_text(self, run, question, answer, hint=""):
        if not self.settings.get("ai_verify", True):
            return True

        detail = self.build_detail(run, question)
        kb = (self.settings.get("knowledge") or "").strip()
        prompt = f"""ตรวจสอบคำตอบของแบบฟอร์มอย่างเข้มงวด

ชื่อแบบฟอร์ม: {run.form_title or "-"}
คำถาม: {question}
คำอธิบายเพิ่มเติม: {detail or "-"}
ข้อมูลอ้างอิง: {kb or "-"}
รูปแบบที่ต้องการ: {hint or "-"}

คำตอบที่ AI รอบแรกเสนอ: {answer}

กติกา:
- ถ้าคำตอบตรงคำถามและมีเหตุผลรองรับพอ ให้ตอบคำเดียวว่า OK
- ถ้าข้อมูลไม่พอ, ต้องเดา, คนละเรื่อง, หรือคำตอบน่าสงสัย ให้ตอบคำเดียวว่า NO
- ห้ามอธิบาย"""
        raw = await self._generate(run, prompt, 12)
        ok = (raw or "").strip().upper().startswith("OK")
        run.log("🛡️ ตรวจซ้ำ AI: " + ("ผ่าน" if ok else "ไม่ผ่าน/ไม่มั่นใจ"))
        return ok

    @staticmethod
    def _extract_final_answer(raw, long=False):
        """ดึงคำตอบสุดท้ายจาก AI โดยรองรับ FINAL: ... และข้อความธรรมดา"""
        t = (raw or "").strip()
        if not t:
            return ""
        m = re.search(r"(?im)^\s*FINAL\s*:\s*(.+?)\s*$", t)
        if m:
            t = m.group(1).strip()
        t = re.sub(r"(?im)^\s*(ANSWER|คำตอบ)\s*:\s*", "", t).strip()
        if not long:
            # เอาบรรทัดแรกเพื่อใช้กรอก short answer
            t = next((x.strip() for x in t.splitlines() if x.strip()), "")
        return t.strip().strip("\"'“”‘’`*").strip()

    @staticmethod
    def _comparison_rule(question):
        q = (question or "").lower()
        rules = []
        if re.search(r"อายุน้อยที่สุด|เด็กที่สุด|youngest|younger", q, re.I):
            rules.append(
                "โจทย์ถามอายุน้อยที่สุด: ต้องเลือกคนที่เกิดทีหลังที่สุด/วันเกิดล่าสุด ไม่ใช่คนที่อายุมากที่สุด"
            )
        if re.search(r"อายุมากที่สุด|แก่ที่สุด|oldest|older", q, re.I):
            rules.append(
                "โจทย์ถามอายุมากที่สุด: ต้องเลือกคนที่เกิดก่อนที่สุด/วันเกิดเก่าที่สุด"
            )
        if re.search(r"น้อยที่สุด|ต่ำที่สุด|least|lowest|minimum", q, re.I):
            rules.append("โจทย์ถามค่าน้อยที่สุด: ห้ามกลับทิศเป็นค่ามากที่สุด")
        if re.search(r"มากที่สุด|สูงที่สุด|most|highest|maximum", q, re.I):
            rules.append("โจทย์ถามค่ามากที่สุด: ห้ามกลับทิศเป็นค่าน้อยที่สุด")
        if re.search(r"ก่อนที่สุด|earliest|first", q, re.I):
            rules.append("โจทย์ถามก่อนที่สุด: เปรียบเทียบลำดับเวลาให้ถูกทิศ")
        if re.search(r"หลังที่สุด|ล่าสุด|latest|most recent", q, re.I):
            rules.append("โจทย์ถามหลังที่สุด/ล่าสุด: เปรียบเทียบลำดับเวลาให้ถูกทิศ")
        return "\n".join(f"- {r}" for r in rules)

    async def ask_ai_text(self, run, question, hint="", long=False):
        """v1.4.8 Adaptive Fast AI: 1 call ก่อน; Judge เฉพาะเมื่อจำเป็น"""
        if not self.settings.get("ai_all", True):
            run.note = "ปิดการใช้ AI"
            return ""

        learned = self.get_learned("text", run, question)
        if learned and learned.get("answer"):
            ans = str(learned["answer"]).strip()
            run.log(f"🧠 ใช้คำตอบ AI ที่เคยยืนยันแล้ว: {question} → {ans}")
            return ans

        provider = self.settings.get("provider", "ollama")
        model = self._ai_model_cache_id()
        mode = self.settings.get("ai_mode", "fast")
        key = (
            "t-fast-v2",
            self._ai_context_key(run),
            (getattr(run, "url", "") or "").strip(),
            norm(question),
            norm(hint),
            long,
            provider,
            model,
            mode,
        )
        if key in self.ai_cache:
            ans = self.ai_cache[key]
            run.log(f"⚡ (cache) {question} → {ans}")
            return ans

        live_key = self.ai_live_start(run, question, "⚡ Fast AI กำลังตอบ")
        live_answer = ""
        live_ok = False

        try:
            detail = self.build_detail(run, question)
            ftitle = run.form_title or "-"
            kb = (self.settings.get("knowledge") or "").strip()
            compare_rule = self._comparison_rule(question)

            context_parts = []
            if detail:
                context_parts.append(f"รายละเอียด/รายชื่อ/ข้อความประกอบในข้อ:\n{detail}")
            if kb:
                context_parts.append(f"ข้อมูลอ้างอิงของผู้ใช้:\n{kb}")
            if hint:
                context_parts.append(f"ข้อมูล/คำตอบอ้างอิงจากผู้ใช้:\n{hint}")
            context_block = "\n\n".join(context_parts) if context_parts else "-"

            answer_rule = (
                "ตอบสั้น 1-3 ประโยค และขึ้นต้นบรรทัดแรกด้วย FINAL:"
                if long else
                "ตอบสั้นสำหรับกรอกฟอร์ม ขึ้นต้นด้วย FINAL: แล้วตามด้วยคำตอบเท่านั้น"
            )

            prompt = f"""ตอบคำถามนี้แบบ Gemini โดยใช้ทั้งบริบทและความรู้ทั่วไปของโมเดล

ชื่อแบบฟอร์ม: {ftitle}

บริบท:
{context_block}

คำถาม:
{question}

กติกา:
- อ่านคำถามให้ครบและห้ามกลับความหมายของคำว่า น้อยที่สุด/มากที่สุด/ก่อน/หลัง
{compare_rule or "- ตรวจชนิดการเปรียบเทียบให้ถูกทิศก่อนตอบ"}
- ถ้ามีรายชื่อในบริบท ให้ตอบจากรายชื่อเหล่านั้นเมื่อโจทย์ถามให้เปรียบเทียบ
- ถ้ามีคำตอบอ้างอิงจากผู้ใช้ ให้ใช้เป็นเบาะแส แต่ต้องตอบให้ตรงคำถาม
- ใช้ความรู้ทั่วไปของโมเดลได้ ไม่ต้องรอให้ข้อมูลอยู่ใน Knowledge box
- ถ้าต้องเห็นรูปที่ไม่ได้ส่งมา หรือเป็นข้อมูลส่วนตัวที่ไม่มีจริง ๆ ให้ตอบ __NO_ANSWER__
- {answer_rule}
- ไม่ต้องอธิบายขั้นตอนคิด

คำตอบ:"""

            run.log(f"⚡ Fast AI กำลังตอบ: {question}")
            raw = await self._generate(run, prompt, 140 if long else 70)
            answer = "" if self._ai_no_answer(raw) else self._extract_final_answer(raw, long=long)

            # Fast: ได้คำตอบที่ใช้ได้ = จบใน 1 call
            if answer and mode == "fast":
                run.log(f"✅ Fast AI → {answer}")

            else:
                # Accurate mode หรือรอบแรกไม่ตอบ: ใช้ Judge แค่ 1 รอบ
                candidate = answer or "(รอบแรกไม่ให้คำตอบ)"
                judge_prompt = f"""คุณคือ AI Judge ตัดสินคำตอบสุดท้ายของฟอร์มนี้

ชื่อแบบฟอร์ม: {ftitle}

บริบท:
{context_block}

คำถาม:
{question}

คำตอบรอบแรก:
{candidate}

ข้อบังคับ:
{compare_rule or "- ตรวจทิศทางคำถามเปรียบเทียบให้ถูกต้อง"}
- ตรวจว่ารอบแรกตอบตรงกับคำว่า น้อยที่สุด/มากที่สุด/ก่อน/หลัง หรือไม่
- ใช้ความรู้ทั่วไปของโมเดลได้
- ถ้ารอบแรกผิด ให้แก้เป็นคำตอบที่ถูกกว่า
- พยายามตอบให้ได้; ใช้ __NO_ANSWER__ เฉพาะเมื่อจำเป็นต้องเห็นรูปที่ไม่ได้ส่งมา/ไม่มีข้อมูลจริง ๆ
- ตอบบรรทัดเดียว FINAL: <คำตอบ>

คำตอบสุดท้าย:"""

                run.log("⚖️ เรียก Judge เฉพาะรอบที่จำเป็น...")
                judged = await self._generate(run, judge_prompt, 90 if long else 55)
                judged_answer = "" if self._ai_no_answer(judged) else self._extract_final_answer(
                    judged, long=long
                )

                if judged_answer:
                    answer = judged_answer
                    run.log(f"⚖️ Judge → {answer}")
                elif not answer:
                    run.note = "AI และ Judge ยังตอบไม่ได้"
                    return ""
                else:
                    run.log(f"↩️ Judge ไม่ได้คำตอบใหม่ → ใช้รอบแรก: {answer}")

            if not answer:
                run.note = "AI ยังหาคำตอบไม่ได้"
                return ""

            self.ai_cache[key] = answer
            self.put_learned("text", run, question, answer)
            live_answer = answer
            live_ok = True
            return answer

        finally:
            self.ai_live_finish(
                live_key,
                question,
                live_answer,
                live_ok,
                "" if live_ok else (run.note or "AI ยังหาคำตอบไม่ได้"),
            )

    async def _verify_ai_choice(self, run, question, choices, idxs, multi=False):
        if not self.settings.get("ai_verify", True):
            return True
        selected = [choices[i] for i in idxs]
        detail = self.build_detail(run, question, choices)
        kb = (self.settings.get("knowledge") or "").strip()
        opts = "\n".join(f"{i+1}. {c}" for i, c in enumerate(choices))
        chosen = " | ".join(selected)

        prompt = f"""ตรวจคำตอบแบบตัวเลือกอย่างเข้มงวด

ชื่อแบบฟอร์ม: {run.form_title or "-"}
คำถาม: {question}
คำอธิบายเพิ่มเติม: {detail or "-"}
ข้อมูลอ้างอิง: {kb or "-"}

ตัวเลือก:
{opts}

คำตอบที่ AI รอบแรกเลือก: {chosen}

ถ้าคำตอบนี้เหมาะสมและมีข้อมูลรองรับพอ ให้ตอบคำเดียวว่า OK
ถ้าไม่มั่นใจ, ต้องเดา, หรือมีโอกาสเลือกผิด ให้ตอบคำเดียวว่า NO
ห้ามอธิบาย"""
        raw = await self._generate(run, prompt, 12)
        ok = (raw or "").strip().upper().startswith("OK")
        run.log("🛡️ ตรวจซ้ำตัวเลือก: " + ("ผ่าน" if ok else "ไม่ผ่าน/ไม่มั่นใจ"))
        return ok

    async def ask_ai_choice(self, run, question, choices, multi=False, preferred=""):
        """v1.4.8 Adaptive Fast Choice: 1 call ก่อน; Judge เมื่อ format/คำตอบมีปัญหา"""
        if not self.settings.get("ai_all", True):
            run.note = "ปิดการใช้ AI"
            return []

        learned = self.get_learned("choice", run, question, choices)
        if learned and learned.get("answer"):
            saved = learned["answer"]
            if isinstance(saved, list):
                idxs = [int(i) for i in saved if isinstance(i, int) and 0 <= i < len(choices)]
                if idxs:
                    run.log(f"🧠 ใช้ตัวเลือก AI ที่เคยยืนยันแล้ว: {question}")
                    return idxs

        provider = self.settings.get("provider", "ollama")
        model = self._ai_model_cache_id()
        mode = self.settings.get("ai_mode", "fast")
        key = (
            "c-fast-v2",
            self._ai_context_key(run),
            (getattr(run, "url", "") or "").strip(),
            norm(question),
            tuple(norm(c) for c in choices),
            multi,
            norm(preferred),
            provider,
            model,
            mode,
        )
        if key in self.ai_cache:
            run.log(f"⚡ (cache ตัวเลือก) {question}")
            return list(self.ai_cache[key])

        live_key = self.ai_live_start(run, question, "⚡ Fast AI กำลังเลือก")
        live_answer = ""
        live_ok = False

        try:
            detail = self.build_detail(run, question, choices)
            ftitle = run.form_title or "-"
            kb = (self.settings.get("knowledge") or "").strip()
            compare_rule = self._comparison_rule(question)

            context_parts = []
            if detail:
                context_parts.append(f"รายละเอียดในข้อ:\n{detail}")
            if kb:
                context_parts.append(f"ข้อมูลอ้างอิงของผู้ใช้:\n{kb}")
            if preferred:
                context_parts.append(f"คำตอบอ้างอิงที่ผู้ใช้ตั้งไว้:\n{preferred}")
            context_block = "\n\n".join(context_parts) if context_parts else "-"

            opts = "\n".join(f"{i}. {c}" for i, c in enumerate(choices, start=1))
            how = (
                "เลือกได้หลายข้อ: ตอบเลขคั่นด้วยจุลภาค เช่น 1,3"
                if multi else
                "เลือกได้ข้อเดียว: ตอบเลขเดียว"
            )

            prompt = f"""ตอบคำถามตัวเลือกแบบ Gemini

ชื่อแบบฟอร์ม: {ftitle}

บริบท:
{context_block}

คำถาม:
{question}

ตัวเลือก:
{opts}

กติกา:
- {how}
{compare_rule or "- อ่านทิศทางของคำถามให้ถูกต้องก่อนเลือก"}
- ใช้ความรู้ทั่วไปของโมเดลได้
- ถ้ามีคำตอบอ้างอิง ให้ใช้เป็นเบาะแสแต่ต้องตรงกับโจทย์
- ตอบเฉพาะหมายเลข
- ใช้ 0 เฉพาะเมื่อจำเป็นต้องเห็นรูปที่ไม่ได้ส่งมา หรือไม่มีข้อมูลจริง ๆ

หมายเลข:"""

            def parse_choice_raw(raw):
                raw = (raw or "").strip()
                if raw == "0":
                    return []
                if multi:
                    ok = re.fullmatch(r"\s*\d+(?:\s*,\s*\d+)*\s*", raw)
                else:
                    ok = re.fullmatch(r"\s*\d+\s*", raw)
                if not ok:
                    nums = re.findall(r"\b\d+\b", raw)
                    if not nums:
                        return None
                    raw = ",".join(nums) if multi else nums[0]

                idxs = []
                for n in re.findall(r"\d+", raw):
                    i = int(n) - 1
                    if 0 <= i < len(choices) and i not in idxs:
                        idxs.append(i)
                if not multi:
                    idxs = idxs[:1]
                return idxs

            run.log(f"⚡ Fast AI กำลังเลือก: {question}")
            raw = await self._generate(run, prompt, 28)
            idxs = parse_choice_raw(raw)

            valid = idxs is not None and len(idxs) > 0

            # Fast mode: valid number = ใช้ทันที
            if valid and mode == "fast":
                run.log(f"✅ Fast AI เลือก: {', '.join(choices[i] for i in idxs)}")

            else:
                first_text = (
                    ", ".join(choices[i] for i in idxs)
                    if valid else
                    "ไม่มีคำตอบที่ใช้ได้"
                )

                judge_prompt = f"""คุณคือ AI Judge เลือกคำตอบสุดท้าย

ชื่อแบบฟอร์ม: {ftitle}

บริบท:
{context_block}

คำถาม:
{question}

ตัวเลือก:
{opts}

รอบแรกเลือก: {first_text}

กติกา:
- {how}
{compare_rule or "- ตรวจทิศทางโจทย์ให้ถูกต้อง"}
- ตรวจว่ารอบแรกกลับความหมาย น้อยที่สุด/มากที่สุด/ก่อน/หลัง หรือไม่
- ใช้ความรู้ทั่วไปของโมเดลได้ และแก้คำตอบรอบแรกได้
- ตอบเฉพาะหมายเลข
- ใช้ 0 เฉพาะเมื่อไม่มีทางตอบจริง ๆ

หมายเลขสุดท้าย:"""

                run.log("⚖️ Judge กำลังตรวจตัวเลือก...")
                judged = await self._generate(run, judge_prompt, 28)
                judged_idxs = parse_choice_raw(judged)

                if judged_idxs:
                    idxs = judged_idxs
                    valid = True
                    run.log(f"⚖️ Judge เลือก: {', '.join(choices[i] for i in idxs)}")
                elif not valid:
                    run.note = "AI และ Judge ยังเลือกคำตอบไม่ได้"
                    return []
                else:
                    run.log(f"↩️ Judge ไม่ได้คำตอบใหม่ → ใช้รอบแรก")

            if not idxs:
                run.note = "AI ยังเลือกคำตอบไม่ได้"
                return []

            self.ai_cache[key] = list(idxs)
            self.put_learned("choice", run, question, list(idxs), choices=choices)
            live_answer = " | ".join(choices[i] for i in idxs)
            live_ok = True
            return idxs

        finally:
            self.ai_live_finish(
                live_key,
                question,
                live_answer,
                live_ok,
                "" if live_ok else (run.note or "AI ยังเลือกคำตอบไม่ได้"),
            )

    # =========================================================
    # PROFILE ANSWER
    # =========================================================

    @staticmethod
    def classify_name(question):
        """จัดประเภทคำถามเรื่องชื่อ: nick / last / full / first / generic (ถามแค่ 'ชื่อ') / None"""
        q = (question or "").lower()
        q = re.sub(r"\(.*?\)|\[.*?\]|（.*?）", " ", q)  # ตัดข้อความในวงเล็บ
        q = re.sub(r"[\*\?:：]", " ", q)

        if re.search(r"ชื่อเล่น|nick\s*name|ฉายา", q):
            return "nick"

        if re.search(
            r"user\s*name|ชื่อผู้ใช้|ชื่อบัญชี|file\s*name|ชื่อไฟล์|display\s*name|สกุลเงิน|currency",
            q,
        ):
            return None

        rest = re.sub(r"last\s*name|family\s*name|sur\s*name|นามสกุล|สกุล", " ", q)
        if rest != q:  # มีคำว่านามสกุล/สกุล
            return "full" if re.search(r"ชื่อ|\bname\b|first|given", rest) else "last"

        if re.search(r"ชื่อจริง|first\s*name|given\s*name|ชื่อต้น", q):
            return "first"

        core = re.sub(
            r"ของคุณ|คุณ|ผู้สมัคร|ผู้ตอบ|ผู้เข้าร่วม|ผู้ลงทะเบียน|ผู้ติดต่อ|กรุณา|โปรด|กรอก|ระบุ|"
            r"ภาษาไทย|ภาษาอังกฤษ|\b(your|please|enter|fill|in|thai|english|th|en|the|of|you|"
            r"contact|participant|applicant)\b",
            " ",
            q,
        )
        core = norm(core)

        if core in ("ชื่อ", "name"):
            return "generic"
        if core in ("fullname", "ชื่อเต็ม"):
            return "full"
        return None

    @staticmethod
    def valid_thai_id(digits):
        """ตรวจเลขบัตรประชาชนไทย 13 หลักด้วย checksum"""
        if len(digits) != 13 or not digits.isdigit():
            return False
        total = sum(int(d) * (13 - i) for i, d in enumerate(digits[:12]))
        return (11 - total % 11) % 10 == int(digits[12])

    @staticmethod
    def age_from_birthdate(bd):
        m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", bd or "")
        if not m:
            return ""
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y > 2400:
            y -= 543
        today = datetime.now()
        age = today.year - y - ((today.month, today.day) < (mo, d))
        return str(age) if 0 < age < 120 else ""

    def profile_answer(self, question, profile, run=None):
        """จับคู่คำถามกับข้อมูลผู้ตอบแบบยืดหยุ่น (คืน None ถ้าไม่ใช่คำถามข้อมูลส่วนตัว)"""
        raw = (question or "").lower()
        first, last = profile["first_name"], profile["last_name"]
        full = f"{first} {last}".strip()

        kind = self.classify_name(question)
        if kind == "nick":
            return profile["nickname"]
        if kind == "last":
            return last
        if kind == "full":
            return full
        if kind == "first":
            return first
        if kind == "generic":
            mode = self.settings.get("name_mode", "auto")
            if mode == "first":
                return first
            if mode == "full":
                return full
            # อัตโนมัติ: ถ้าในหน้านี้มีช่อง 'นามสกุล' แยกอยู่แล้ว → ชื่อจริงอย่างเดียว ไม่งั้นใส่ชื่อ+นามสกุล
            return first if getattr(run, "page_has_lastname", False) else full

        if re.search(r"อีเมล|e-?mail|เมล์|\bmail\b", raw):
            return profile["email"]

        if re.search(
            r"เบอร์|โทรศัพท์|โทรหา|โทร\b|มือถือ|\btel\b|phone|mobile|\bcell\b|contact\s*number|หมายเลขติดต่อ",
            raw,
        ) and not re.search(r"โทรทัศน์|รองเท้า|เสื้อ|\bsize\b|ไซส์|ไซซ์", raw):
            return profile["phone"]

        if re.search(r"ปีเกิด|birth\s*year", raw):
            d = self.parse_date(profile["birthdate"])
            if not d:
                return ""
            return str(d[0] + (543 if "พ.ศ" in raw else 0))

        if re.search(r"วันเกิด|เกิดวันที่|birth|\bdob\b", raw):
            return profile["birthdate"]

        if re.search(r"อายุ|\bage\b|how\s*old", raw):
            return profile["age"] or self.age_from_birthdate(profile["birthdate"])

        if re.search(r"ที่อยู่|address|ที่พัก", raw):
            return profile["address"]

        if re.search(
            r"เลขบัตรประชาชน|เลขประจำตัวประชาชน|บัตรประชาชน|เลข\s*ปชช|"
            r"national\s*id|citizen\s*id|\bid\s*card\b|เลขบัตร\s*(ประชาชน)?",
            raw,
        ) and not re.search(r"user\s*id|ไอดี\s*ไลน์|line\s*id|student\s*id|employee\s*id", raw):
            nid = re.sub(r"[^0-9]", "", profile["national_id"] or "")
            if nid and not self.valid_thai_id(nid):
                run_log = getattr(run, "log", None)
                if run_log:
                    run_log(f"⚠️ เลขบัตรประชาชนที่กรอกไว้ '{profile['national_id']}' อาจไม่ถูกต้อง (เช็กซัม/จำนวนหลักไม่ผ่าน) แต่จะกรอกให้ตามที่ตั้งไว้")
            return nid

        if re.search(r"line\s*id|ไอดี\s*ไลน์|ไลน์|\bline\b", raw):
            return profile["line_id"]

        if re.search(r"twitter|ทวิต|\bx\s*(username|id|handle|account)|ไอดี\s*x\b|อิกซ์", raw):
            return profile["x_handle"]

        # บัญชี/Username ทั่วไป (เช่น ระบบจองบัตร, เกม, สมาชิก) - รองรับทั้งคำว่า "account" ภาษาอังกฤษ
        # และ "บัญชี" ภาษาไทย แต่ไม่จับกรณีที่เข้าข่ายบัญชีธนาคาร ซึ่งเป็นข้อมูลการเงิน
        if (
            re.search(r"username|ยูสเซอร์เนม|user\s*account|\baccount\b", raw)
            or (
                "บัญชี" in raw
                and re.search(r"ผู้ใช้|สมาชิก|เกม|ระบบ|จองบัตร|จองคิว|ไอดี", raw)
            )
        ) and not re.search(
            r"ธนาคาร|bank|พร้อมเพย์|promptpay|เลขที่บัญชี|account\s*number|bank\s*account",
            raw,
        ):
            return profile["account"]

        return None

    # =========================================================
    # CHOICE MATCHING
    # =========================================================

    @staticmethod
    def match_choice(answer, choices, loose=True):
        """จับตัวเลือกแบบเข้มงวด ลด false match"""
        a = norm(answer)
        if not a:
            return None

        ns = [norm(c) for c in choices]

        # exact
        for i, c in enumerate(ns):
            if c and a == c:
                return i

        # substring ต้องไม่สั้นเกิน และต้องมีผู้สมัครเพียงตัวเดียว
        cands = []
        for i, c in enumerate(ns):
            if not c:
                continue
            shorter = min(len(a), len(c))
            longer = max(len(a), len(c))
            if shorter >= 4 and (c in a or a in c) and shorter / max(longer, 1) >= 0.60:
                cands.append(i)
        if len(cands) == 1:
            return cands[0]

        if loose and ns:
            ratios = [difflib.SequenceMatcher(None, a, c).ratio() for c in ns]
            order = sorted(range(len(ratios)), key=lambda i: ratios[i], reverse=True)
            if order and ratios[order[0]] >= 0.88:
                # ต้องชนะอันดับสองพอสมควร ไม่งั้นกำกวม
                if len(order) == 1 or ratios[order[0]] - ratios[order[1]] >= 0.06:
                    return order[0]

        return None

    async def decide_choices(self, run, question, choices, multi=False, has_other=False):
        """คำตอบที่กำหนดไว้จะถูกส่งให้ AI เป็นข้อมูลอ้างอิงก่อนตอบ"""
        found, fixed, _raw, _score = self.find_fixed(question, self.settings["fixed"])
        preferred = fixed if (found and fixed) else ""

        if preferred:
            run.log(f"📚 มีคำตอบอ้างอิง: {preferred}")
            run.log("   ↳ ส่งคำถาม + คำตอบอ้างอิง + ตัวเลือก ให้ AI อ่านก่อนตอบ")

        # ไม่มี choice จริง แต่มีช่อง Other
        if not choices and has_other:
            hint = ""
            if preferred:
                hint = (
                    f"คำตอบอ้างอิงที่ผู้ใช้กำหนดไว้คือ: {preferred}. "
                    "อ่านคำถามก่อน แล้วตอบโดยใช้ข้อมูลอ้างอิงนี้เป็นหลักถ้ามันตรงกับคำถาม"
                )

            text_answer = await self.ask_ai_text(run, question, hint=hint)
            if text_answer:
                return [], "ai", text_answer

            # AI ไม่มั่นใจ แต่มีคำตอบที่ผู้ใช้ตั้งไว้ → fallback เพื่อไม่ปล่อยข้อว่าง
            if preferred:
                run.log(f"↩️ AI ไม่ได้คำตอบที่มั่นใจ → ใช้คำตอบอ้างอิงเดิม: {preferred}")
                return [], "fixed", preferred

            return [], "ai", None

        ai_choices = choices + ["อื่นๆ (ระบุเอง)"] if has_other else list(choices)

        # ask_ai_choice รองรับ preferred อยู่แล้ว และจะเอาไปใส่ใน prompt
        idxs = await self.ask_ai_choice(
            run,
            question,
            ai_choices,
            multi,
            preferred=preferred,
        )

        other_text = None
        if has_other and len(choices) in idxs:
            idxs = [i for i in idxs if i != len(choices)]

            hint = ""
            if preferred:
                hint = (
                    f"คำตอบอ้างอิงที่ผู้ใช้กำหนดไว้คือ: {preferred}. "
                    "ตอบข้อความสำหรับช่องอื่นๆ โดยใช้ข้อมูลนี้เป็นหลักถ้าตรงกับคำถาม"
                )

            other_text = (await self.ask_ai_text(run, question, hint=hint)) or None

            if not other_text and preferred:
                other_text = preferred

        if idxs or other_text:
            return [choices[i] for i in idxs], "ai", other_text

        # AI ไม่ตอบ/สองรอบไม่ตรงกัน แต่มี fixed:
        # ใช้ fixed เป็น fallback หลังจาก AI ได้อ่านแล้ว
        if preferred:
            parts = [p.strip() for p in re.split(r"[|;、]", preferred) if p.strip()]
            picks, unmatched = [], []

            for part in parts if multi else [preferred]:
                idx = self.match_choice(part, choices, loose=True) if choices else None
                if idx is not None:
                    if choices[idx] not in picks:
                        picks.append(choices[idx])
                else:
                    unmatched.append(part)

            if not multi:
                picks = picks[:1]

            if picks:
                run.log(f"↩️ AI ไม่มั่นใจ → fallback ใช้คำตอบอ้างอิง: {' | '.join(picks)}")
                return picks, "fixed", None

            if has_other:
                run.log(f"↩️ AI ไม่มั่นใจ → fallback ใส่ช่องอื่นๆ: {preferred}")
                return [], "fixed", preferred

            run.note = f"AI ไม่มั่นใจ และคำตอบอ้างอิง '{preferred}' ไม่ตรงกับตัวเลือกใด"
            return [], "fixed", None

        return [], "ai", None

    # =========================================================
    # QUESTION TEXT
    # =========================================================

    async def get_question_info(self, block):
        """คืน (ชื่อคำถาม, ข้อความทั้งหมดของข้อ, เป็นข้อบังคับไหม)"""
        title = ""
        try:
            h = block.locator('[role="heading"]')
            if await h.count() > 0:
                raw = (await h.first.inner_text()).strip()
                lines = [l.strip() for l in raw.splitlines() if l.strip() and l.strip() != "*"]
                title = " ".join(lines)
        except Exception:
            pass

        full = ""
        try:
            full = (await block.inner_text()).strip()
        except Exception:
            pass

        if not title:
            lines = [l.strip() for l in full.splitlines() if l.strip()]
            title = lines[0] if lines else ""

        required = False
        try:
            required = await block.locator('[aria-required="true"]').count() > 0
        except Exception:
            pass

        if re.search(r"\*\s*$", title):
            required = True
        title = re.sub(r"\s*\*\s*$", "", title).strip()

        return title, full, required

    @staticmethod
    async def _label_of(el, *attrs):
        for a in attrs:
            v = await el.get_attribute(a)
            if v:
                return v
        return ""

    # =========================================================
    # HANDLERS  (คืน (คำตอบ, แหล่งที่มา) หรือ None)
    # =========================================================

    async def select_other(self, run, block, other_el, text):
        """เลือกตัวเลือก 'อื่นๆ' แล้วพิมพ์ข้อความ"""
        await other_el.click()
        try:
            inp = block.locator('input[type="text"]')
            if await inp.count() > 0:
                await inp.last.fill(text)
        except Exception as e:
            run.log(f"⚠️ พิมพ์ข้อความช่องอื่นๆ ไม่ได้: {e}")
        run.log(f"✏️ อื่นๆ: {text}")

    async def handle_radio(self, run, block, question):
        groups = block.locator('div[role="radiogroup"]')
        gcount = await groups.count()

        if gcount > 1:
            return await self.handle_radio_grid(run, block, question, groups, gcount)

        radios = block.locator('div[role="radio"]')
        count = await radios.count()
        if count == 0:
            return None

        labels, els = [], []
        other_el = None
        for i in range(count):
            el = radios.nth(i)
            label = await self._label_of(el, "data-value", "aria-label")
            if label == "__other_option__":
                other_el = el
            elif label:
                labels.append(label)
                els.append(el)

        if not labels and other_el is None:
            return None

        picks, src, other_text = await self.decide_choices(
            run, question, labels, multi=False, has_other=other_el is not None
        )

        if picks:
            await els[labels.index(picks[0])].click()
            run.log(f"🔘 เลือก: {picks[0]}")
            return picks[0], src

        if other_text and other_el is not None:
            await self.select_other(run, block, other_el, other_text)
            return f"อื่นๆ: {other_text}", src

        run.note = run.note or "ไม่พบตัวเลือกที่ตรงกัน"
        return None

    async def handle_radio_grid(self, run, block, question, groups, gcount):
        """คำถามแบบตารางตัวเลือกหลายข้อ (แต่ละแถวเลือกได้ 1 ข้อ)"""
        answered = []
        src = "ai"

        for g in range(gcount):
            grp = groups.nth(g)
            row = (await grp.get_attribute("aria-label")) or f"แถว {g + 1}"

            radios = grp.locator('div[role="radio"]')
            labels, els = [], []
            for i in range(await radios.count()):
                el = radios.nth(i)
                label = await self._label_of(el, "data-value", "aria-label")
                if label:
                    labels.append(label)
                    els.append(el)

            if not labels:
                continue

            picks, src, _o = await self.decide_choices(
                run, f"{question} - {row}", labels, multi=False
            )
            if picks:
                await els[labels.index(picks[0])].click()
                answered.append(f"{row}: {picks[0]}")
                run.log(f"🔘 {row} → {picks[0]}")

        if answered:
            return " ; ".join(answered), src

        run.note = "ตอบตารางไม่ได้"
        return None

    async def handle_checkbox(self, run, block, question):
        groups = block.locator('div[role="group"]')
        gcount = await groups.count()
        if gcount > 1:
            grid = await self.handle_checkbox_grid(run, block, question, groups, gcount)
            if grid:
                return grid

        boxes = block.locator('div[role="checkbox"]')
        count = await boxes.count()
        if count == 0:
            return None

        labels, els = [], []
        other_el = None
        for i in range(count):
            el = boxes.nth(i)
            label = await self._label_of(el, "data-answer-value", "aria-label")
            if label == "__other_option__":
                other_el = el
            elif label:
                labels.append(label)
                els.append(el)

        if not labels and other_el is None:
            return None

        picks, src, other_text = await self.decide_choices(
            run, question, labels, multi=True, has_other=other_el is not None
        )

        for p in picks:
            el = els[labels.index(p)]
            checked = (await el.get_attribute("aria-checked") or "").lower()
            if checked != "true":
                await el.click()
            run.log(f"☑️ {p}")

        parts = list(picks)
        if other_text and other_el is not None:
            await self.select_other(run, block, other_el, other_text)
            parts.append(f"อื่นๆ: {other_text}")

        if not parts:
            run.note = run.note or "ไม่พบตัวเลือกที่ตรงกัน"
            return None

        return " | ".join(parts), src

    async def handle_checkbox_grid(self, run, block, question, groups, gcount):
        """คำถามแบบตารางช่องทำเครื่องหมาย (แต่ละแถวเลือกได้หลายข้อ)"""
        answered = []
        src = "ai"

        for g in range(gcount):
            grp = groups.nth(g)
            row = (await grp.get_attribute("aria-label")) or f"แถว {g + 1}"

            boxes = grp.locator('div[role="checkbox"]')
            labels, els = [], []
            for i in range(await boxes.count()):
                el = boxes.nth(i)
                label = await self._label_of(el, "data-answer-value", "aria-label")
                if label:
                    labels.append(label)
                    els.append(el)

            if not labels:
                continue

            picks, src, _o = await self.decide_choices(
                run, f"{question} - {row}", labels, multi=True
            )
            for p in picks:
                el = els[labels.index(p)]
                checked = (await el.get_attribute("aria-checked") or "").lower()
                if checked != "true":
                    await el.click()
            if picks:
                answered.append(f"{row}: {' | '.join(picks)}")
                run.log(f"☑️ {row} → {' | '.join(picks)}")

        if answered:
            return " ; ".join(answered), src
        return None

    async def handle_dropdown(self, run, block, question):
        lb = block.locator('div[role="listbox"]')
        if await lb.count() == 0:
            return None

        page = block.page
        await lb.first.click()
        await page.wait_for_timeout(500)

        opts = block.locator('div[role="option"]')
        labels, els = [], []
        for i in range(await opts.count()):
            o = opts.nth(i)
            v = await o.get_attribute("data-value") or ""
            if v:
                labels.append(v)
                els.append(o)

        if not labels:
            await page.keyboard.press("Escape")
            return None

        picks, src, _o = await self.decide_choices(run, question, labels, multi=False)
        if not picks:
            await page.keyboard.press("Escape")
            run.note = run.note or "ไม่พบตัวเลือกที่ตรงกัน"
            return None

        await els[labels.index(picks[0])].click()
        await page.wait_for_timeout(300)
        run.log(f"🔽 เลือก: {picks[0]}")
        return picks[0], src

    @staticmethod
    async def _named_inputs(block):
        """หา input ของช่องเวลา/วันที่แบบแยกส่วน โดยดูจาก aria-label ที่ตรงเป๊ะ (กันสับสนกับช่องข้อความทั่วไป)"""
        names = {
            "h": r"^(ชั่วโมง|hour|hours)$",
            "m": r"^(นาที|minute|minutes)$",
            "s": r"^(วินาที|second|seconds)$",
            "d": r"^(วัน|day)$",
            "mo": r"^(เดือน|month)$",
            "y": r"^(ปี|year)$",
        }
        found = {}
        inputs = block.locator("input")
        for i in range(await inputs.count()):
            el = inputs.nth(i)
            lab = ((await el.get_attribute("aria-label")) or "").strip().lower()
            for k, rx in names.items():
                if k not in found and re.match(rx, lab):
                    found[k] = el
        return found

    @staticmethod
    def parse_date(text):
        t = text or ""
        m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", t)
            if not m:
                return None
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y > 2400:  # ปี พ.ศ.
            y -= 543
        try:
            datetime(y, mo, d)  # ตรวจวันจริง เช่น 31/02 จะไม่ผ่าน
        except ValueError:
            return None
        return y, mo, d

    @staticmethod
    def parse_time(text):
        m = re.search(r"(\d{1,3})\s*[:.]\s*(\d{1,2})(?:\s*[:.]\s*(\d{1,2}))?", text or "")
        if not m:
            return None
        return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)

    async def fill_time(self, run, block, parts, hh, mm, ss, is_duration):
        page = block.page
        lb = block.locator('div[role="listbox"]')
        twelve = (not is_duration) and (await lb.count() > 0)

        h_fill = (hh % 12 or 12) if twelve else hh
        await parts["h"].fill(str(h_fill))
        await parts["m"].fill(f"{mm:02d}")
        if "s" in parts:
            await parts["s"].fill(f"{ss:02d}")

        if twelve:
            want_pm = hh >= 12
            await lb.first.click()
            await page.wait_for_timeout(400)

            opts = block.locator('div[role="option"]')
            names, els = [], []
            for i in range(await opts.count()):
                o = opts.nth(i)
                v = (await o.get_attribute("data-value")) or ""
                if v:
                    names.append(v)
                    els.append(o)

            idx = None
            for i, v in enumerate(names):
                u = v.upper()
                if want_pm and (u == "PM" or "หลังเที่ยง" in v):
                    idx = i
                if (not want_pm) and (u == "AM" or "ก่อนเที่ยง" in v):
                    idx = i
            if idx is None and len(names) >= 2:
                idx = 1 if want_pm else 0

            if idx is not None:
                await els[idx].click()
            else:
                await page.keyboard.press("Escape")

    async def handle_datetime(self, run, block, question):
        """วันที่ / เวลา / วันที่+เวลา / ระยะเวลา"""
        date_inp = block.locator('input[type="date"]')
        has_date_input = await date_inp.count() > 0
        parts = await self._named_inputs(block)

        has_time = "h" in parts and "m" in parts
        has_split_date = "d" in parts and "mo" in parts

        if not (has_date_input or has_time or has_split_date):
            return None

        has_date = has_date_input or has_split_date
        is_duration = has_time and ("s" in parts) and not has_date

        found, fixed, _r, _s = self.find_fixed(question, self.settings["fixed"])
        answer, src = None, "profile"

        if found and fixed:
            answer, src = fixed, "fixed"
        elif has_date:
            cand = self.profile_answer(question, run.profile, run)
            if cand and self.parse_date(cand):
                answer = cand

        if not answer:
            if has_date and has_time:
                hint = "ตอบเป็นวันที่และเวลา รูปแบบ YYYY-MM-DD HH:MM เท่านั้น (ปี ค.ศ. เวลา 24 ชั่วโมง)"
            elif has_date:
                hint = "ตอบเป็นวันที่รูปแบบ YYYY-MM-DD เท่านั้น (ปี ค.ศ.)"
            elif is_duration:
                hint = "ตอบเป็นระยะเวลารูปแบบ HH:MM:SS เท่านั้น"
            else:
                hint = "ตอบเป็นเวลารูปแบบ HH:MM แบบ 24 ชั่วโมงเท่านั้น"
            answer = await self.ask_ai_text(run, question, hint=hint)
            src = "ai"

        if not answer:
            run.note = run.note or "ไม่มีคำตอบสำหรับช่องวันที่/เวลา"
            return None

        d = self.parse_date(answer) if has_date else None
        rest = re.sub(
            r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}", " ", answer
        )
        t = self.parse_time(rest) if has_time else None

        if has_date and not d:
            run.note = "รูปแบบวันที่ไม่ถูกต้อง (ต้องเป็น YYYY-MM-DD)"
            return None
        if has_time and not t:
            run.note = "รูปแบบเวลาไม่ถูกต้อง (ต้องเป็น HH:MM)"
            return None

        try:
            if d:
                y, mo, dd = d
                if has_date_input:
                    await date_inp.first.fill(f"{y:04d}-{mo:02d}-{dd:02d}")
                else:
                    await parts["d"].fill(str(dd))
                    await parts["mo"].fill(str(mo))
                    if "y" in parts:
                        await parts["y"].fill(str(y))
            if t:
                await self.fill_time(run, block, parts, t[0], t[1], t[2], is_duration)
        except Exception as e:
            run.note = f"กรอกวันที่/เวลาไม่ได้: {str(e)[:60]}"
            run.log(f"⚠️ {e}")
            return None

        run.log(f"📅 {answer}")
        return answer, src

    async def handle_file_upload(self, run, block, question):
        """แนบไฟล์ Google Forms พร้อม fallback หลายแบบ"""
        btn = block.locator('div[role="button"]').filter(
            has_text=re.compile(r"เพิ่มไฟล์|add file", re.I)
        )
        if await btn.count() == 0:
            return None

        path = (run.profile.get("upload_file") or "").strip().strip("\"'")
        if not path or not os.path.exists(path):
            run.note = "ต้องแนบไฟล์ (ใส่ที่อยู่ไฟล์ในช่อง 'ไฟล์ที่จะแนบ' ของโปรไฟล์)"
            return None

        page = block.page
        try:
            await btn.first.click()
            await page.wait_for_timeout(700)

            # ทางลัด: ถ้า input[type=file] โผล่โดยตรง
            direct = page.locator('input[type="file"]')
            if await direct.count() > 0:
                await direct.last.set_input_files(path)
                await page.wait_for_timeout(1200)
                run.log(f"📎 แนบไฟล์: {os.path.basename(path)}")
                return os.path.basename(path), "profile"

            frame = None
            for _ in range(24):
                for f in page.frames:
                    furl = (f.url or "").lower()
                    if "picker" in furl or "drive" in furl:
                        frame = f
                        break
                if frame:
                    break
                await page.wait_for_timeout(350)

            if frame is None:
                run.note = "ไม่พบหน้าต่างเลือกไฟล์ของ Google"
                return None

            # ถ้า iframe มี input file โดยตรง
            fin = frame.locator('input[type="file"]')
            if await fin.count() > 0:
                await fin.first.set_input_files(path)
            else:
                # fallback ผ่าน file chooser
                browse = frame.get_by_text(re.compile(r"เรียกดู|Browse|Select files", re.I))
                if await browse.count() == 0:
                    browse = frame.locator('div[role="button"]').filter(
                        has_text=re.compile(r"เรียกดู|Browse|Select files", re.I)
                    )
                if await browse.count() == 0:
                    run.note = "ไม่พบปุ่มเลือกไฟล์ใน Google Picker"
                    return None
                async with page.expect_file_chooser(timeout=10000) as fc_info:
                    await browse.first.click()
                chooser = await fc_info.value
                await chooser.set_files(path)

            await page.wait_for_timeout(1200)

            up = frame.locator('div[role="button"]').filter(
                has_text=re.compile(r"^(อัปโหลด|Upload|Select)$", re.I)
            )
            if await up.count() == 0:
                up = frame.get_by_text(re.compile(r"^(อัปโหลด|Upload|Select)$", re.I))
            if await up.count() > 0:
                await up.first.click()

            await page.wait_for_timeout(2500)
            run.log(f"📎 แนบไฟล์: {os.path.basename(path)}")
            return os.path.basename(path), "profile"
        except Exception as e:
            run.note = f"แนบไฟล์ไม่สำเร็จ: {str(e)[:80]}"
            run.log(f"⚠️ {e}")
            return None

    async def handle_text_question(self, run, block, question):
        target = None
        is_area = False

        for sel in (
            'input[type="text"]',
            'input[type="email"]',
            'input[type="tel"]',
            'input[type="number"]',
            'input[type="url"]',
            "textarea",
        ):
            loc = block.locator(sel)
            if await loc.count() > 0:
                target = loc.first
                is_area = sel == "textarea"
                break

        if target is None:
            return None

        found, fixed, _r, _s = self.find_fixed(question, self.settings["fixed"])

        if found and fixed:
            run.log(f"📚 พบคำตอบอ้างอิง: {fixed}")
            run.log("   ↳ ส่งคำถาม + คำตอบอ้างอิง ให้ AI อ่านก่อนตอบ")

            hint = (
                f"คำตอบอ้างอิงที่ผู้ใช้กำหนดไว้คือ: {fixed}. "
                "อ่านคำถามให้ครบก่อน แล้วใช้คำตอบอ้างอิงนี้เป็นหลักถ้ามันตอบคำถามโดยตรง. "
                "ห้ามเปลี่ยนไปเป็นข้อมูลคนละเรื่อง และตอบเฉพาะคำตอบที่เหมาะกับช่องนี้"
            )

            answer = await self.ask_ai_text(
                run,
                question,
                hint=hint,
                long=is_area,
            )

            if answer:
                src = "ai"
            else:
                # AI ไม่มั่นใจ/สองรอบไม่ตรงกัน แต่ผู้ใช้มีคำตอบกำหนดไว้
                # fallback เพื่อไม่ให้ข้อ required ค้าง
                answer, src = fixed, "fixed"
                run.log(f"↩️ AI ไม่ได้คำตอบที่มั่นใจ → ใช้คำตอบอ้างอิงเดิม: {fixed}")

        else:
            prof = self.profile_answer(question, run.profile, run)

            if prof is not None:
                # ข้อมูลผู้ตอบยังกรอกโดยตรง ไม่ส่งข้อมูลส่วนตัวออกไป AI
                if not prof:
                    run.note = "คำถามนี้ต้องใช้ข้อมูลผู้ตอบ แต่ชุดข้อมูลนี้ยังว่าง"
                    run.log(f"⚠️ {run.note}")
                    return None
                answer, src = prof, "profile"
                run.log("👤 ใช้ข้อมูลผู้ตอบโดยตรง → ไม่ส่งข้อมูลนี้ไป AI")
            else:
                answer = await self.ask_ai_text(run, question, long=is_area)
                src = "ai"

        if not answer:
            run.note = run.note or "ไม่มีคำตอบที่มั่นใจพอ"
            return None

        await target.fill(str(answer))
        run.log(f"✍️ {question} → {answer}")
        return answer, src

    # =========================================================
    # PROCESS PAGE
    # =========================================================

    async def answer_block(self, run, block, question):
        for h in (
            self.handle_datetime,
            self.handle_file_upload,
            self.handle_radio,
            self.handle_checkbox,
            self.handle_dropdown,
            self.handle_text_question,
        ):
            res = await h(run, block, question)
            if res:
                return res
        return None

    async def process_questions(self, run, page):
        blocks = page.locator('div[role="listitem"]')
        count = await blocks.count()

        run.log(f"📋 พบประมาณ {count} คำถาม")

        infos = []
        for i in range(count):
            try:
                infos.append(await self.get_question_info(blocks.nth(i)))
            except Exception:
                infos.append(("", "", False))

        # ถ้าหน้านี้มีข้อ 'นามสกุล' แยกอยู่แล้ว ข้อ 'ชื่อ' เฉยๆ จะตอบเฉพาะชื่อจริง
        run.page_has_lastname = any(self.classify_name(t) == "last" for t, _f, _r in infos)

        for i in range(count):
            if self.stop_event.is_set():
                return

            block = blocks.nth(i)
            question, full, required = infos[i]

            if not question:
                continue

            run.qfull = full
            run.log(f"\n[{i + 1}] {question}" + (" *" if required else ""))
            run.note = ""
            res = None

            try:
                res = await self.answer_block(run, block, question)
            except Exception as e:
                run.note = f"ผิดพลาด: {str(e)[:60]}"
                run.log(f"⚠️ ข้อนี้ผิดพลาด: {e}")

            if res:
                run.add(question, res[0], res[1], req=required)
            else:
                note = run.note or "ยังไม่รองรับคำถามชนิดนี้"
                run.log(f"⚠️ ข้าม: {note}")
                run.add(question, "", "skip", note, req=required)

    # =========================================================
    # HELPERS
    # =========================================================

    async def sleep(self, secs):
        end = time.time() + secs
        while time.time() < end and not self.stop_event.is_set():
            await asyncio.sleep(0.25)

    async def retry(self, factory, what, log, tries=3, delay=2.0):
        last = None
        for i in range(1, tries + 1):
            if self.stop_event.is_set():
                break
            try:
                return await factory()
            except Exception as e:
                last = e
                log(f"⚠️ {what} ไม่สำเร็จ (ครั้งที่ {i}/{tries}): {str(e)[:90]}")
                if i < tries:
                    await self.sleep(delay * i)
        raise last or RuntimeError(f"{what} ถูกยกเลิก")

    async def find_next_button(self, page):
        for selector in (
            'div[role="button"]:has-text("ถัดไป")',
            'div[role="button"]:has-text("Next")',
        ):
            btn = page.locator(selector)
            if await btn.count() > 0 and await btn.first.is_visible():
                return btn.first
        return None

    async def page_signature(self, page):
        """ลายเซ็นคร่าวๆ ของ Section ปัจจุบัน ใช้ตรวจว่ากด Next แล้วเปลี่ยนหน้าจริงหรือไม่"""
        try:
            blocks = page.locator('div[role="listitem"]')
            n = await blocks.count()
            first = ""
            if n:
                first = (await blocks.first.inner_text(timeout=2000))[:300]
            return f"{n}|{norm(first)}"
        except Exception:
            return ""

    async def page_problem(self, page):
        """คืน 'closed' / 'notfound' / None"""
        try:
            if await page.locator('div[role="listitem"]').count() > 0:
                return None
            text = (await page.locator("body").inner_text(timeout=3000)).lower()
            if any(k in text for k in NOTFOUND_PHRASES):
                return "notfound"
            if any(k in text for k in CLOSED_PHRASES):
                return "closed"
        except Exception:
            pass
        return None

    async def take_screenshot(self, run, page, suffix=""):
        if not self.settings.get("screenshot"):
            return
        try:
            os.makedirs(SHOT_DIR, exist_ok=True)
            safe = re.sub(r"[^\w\-]+", "_", run.tag)
            extra = f"_{suffix}" if suffix else ""
            path = os.path.join(
                SHOT_DIR, f"{time.strftime('%Y%m%d_%H%M%S')}_{safe}{extra}.png"
            )
            await page.screenshot(path=path, full_page=True)
            run.log(f"📸 บันทึกภาพ: {path}")
        except Exception as e:
            run.log(f"⚠️ บันทึกภาพไม่สำเร็จ: {e}")

    @staticmethod
    def _submit_text_norm(value):
        s = str(value or "").replace("\u00a0", " ")
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    async def _is_clickable_visible(self, el):
        try:
            if not await el.is_visible():
                return False
            disabled = await el.get_attribute("disabled")
            aria_disabled = (await el.get_attribute("aria-disabled") or "").strip().lower()
            if disabled is not None or aria_disabled == "true":
                return False
            return True
        except Exception:
            return False

    async def find_submit_button(self, page, wait_ms=1200):
        """
        Submit Detector V2
        1) accessible role/name
        2) Google Forms known attributes
        3) input submit
        4) scan visible clickable elements by innerText / aria-label / value
        """
        submit_names = {
            "ส่ง", "ส่งคำตอบ", "ส่งแบบฟอร์ม",
            "submit", "submit form", "send",
        }
        pattern = re.compile(
            r"^\s*(ส่ง|ส่งคำตอบ|ส่งแบบฟอร์ม|Submit|Submit\s+form|Send)\s*$",
            re.I,
        )

        async def first_visible(loc):
            try:
                n = min(await loc.count(), 250)
            except Exception:
                return None
            for i in range(n):
                el = loc.nth(i)
                if await self._is_clickable_visible(el):
                    return el
            return None

        rounds = max(1, int(max(300, wait_ms) / 300))

        for _ in range(rounds):
            # 1) Playwright accessible name: ทนกว่า filter(has_text=...)
            try:
                el = await first_visible(page.get_by_role("button", name=pattern))
                if el is not None:
                    return el
            except Exception:
                pass

            # 2) Google Forms commonly uses jsname=M2UYVd for submit
            for sel in (
                '[jsname="M2UYVd"][role="button"]',
                'div[jsname="M2UYVd"]',
                '[data-id="M2UYVd"]',
            ):
                try:
                    loc = page.locator(sel)
                    n = min(await loc.count(), 20)
                    for i in range(n):
                        el = loc.nth(i)
                        if not await self._is_clickable_visible(el):
                            continue
                        vals = []
                        for attr in ("aria-label", "data-value", "value"):
                            try:
                                vals.append(await el.get_attribute(attr))
                            except Exception:
                                pass
                        try:
                            vals.append(await el.inner_text(timeout=500))
                        except Exception:
                            pass
                        try:
                            vals.append(await el.text_content(timeout=500))
                        except Exception:
                            pass
                        normalized = {self._submit_text_norm(v) for v in vals if v}
                        if normalized & submit_names:
                            return el
                except Exception:
                    pass

            # 3) Native submit/button inputs
            for sel in ('input[type="submit"]', 'input[type="button"]'):
                try:
                    loc = page.locator(sel)
                    n = min(await loc.count(), 100)
                    for i in range(n):
                        el = loc.nth(i)
                        if not await self._is_clickable_visible(el):
                            continue
                        value = self._submit_text_norm(await el.get_attribute("value"))
                        aria = self._submit_text_norm(await el.get_attribute("aria-label"))
                        if value in submit_names or aria in submit_names:
                            return el
                except Exception:
                    pass

            # 4) Broad scan: Google can change DOM structure but accessible text remains "ส่ง"
            try:
                loc = page.locator(
                    'div[role="button"], button, [role="button"], '
                    'input[type="submit"], input[type="button"]'
                )
                n = min(await loc.count(), 300)
                for i in range(n):
                    el = loc.nth(i)
                    if not await self._is_clickable_visible(el):
                        continue

                    values = []
                    for attr in ("aria-label", "data-value", "value", "title"):
                        try:
                            values.append(await el.get_attribute(attr))
                        except Exception:
                            pass
                    try:
                        values.append(await el.inner_text(timeout=350))
                    except Exception:
                        pass
                    try:
                        values.append(await el.text_content(timeout=350))
                    except Exception:
                        pass

                    for value in values:
                        if self._submit_text_norm(value) in submit_names:
                            return el
            except Exception:
                pass

            await page.wait_for_timeout(300)

        return None

    async def has_submit_button_dom(self, page):
        """DOM probe สำรอง ใช้ตรวจว่ามีปุ่มส่งจริงแม้ Playwright locator หาไม่เจอ"""
        try:
            return bool(await page.evaluate(
                """() => {
                    const names = new Set([
                        'ส่ง','ส่งคำตอบ','ส่งแบบฟอร์ม',
                        'submit','submit form','send'
                    ]);
                    const norm = (v) => String(v || '')
                        .replace(/\\u00a0/g, ' ')
                        .replace(/\\s+/g, ' ')
                        .trim()
                        .toLowerCase();
                    const visible = (el) => {
                        const s = window.getComputedStyle(el);
                        if (s.display === 'none' || s.visibility === 'hidden') return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    };
                    const els = [...document.querySelectorAll(
                        '[role="button"],button,input[type="submit"],input[type="button"],[jsname="M2UYVd"]'
                    )];
                    return els.some((el) => {
                        if (!visible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') {
                            return false;
                        }
                        const vals = [
                            el.innerText,
                            el.textContent,
                            el.getAttribute('aria-label'),
                            el.getAttribute('data-value'),
                            el.getAttribute('value'),
                            el.getAttribute('title')
                        ].map(norm);
                        return vals.some(v => names.has(v));
                    });
                }"""
            ))
        except Exception:
            return False

    async def dom_submit_fallback(self, run, page):
        """Fallback สุดท้าย: หาและ click ปุ่มส่งจาก DOM โดยตรง"""
        try:
            label = await page.evaluate(
                """() => {
                    const names = new Set([
                        'ส่ง','ส่งคำตอบ','ส่งแบบฟอร์ม',
                        'submit','submit form','send'
                    ]);
                    const norm = (v) => String(v || '')
                        .replace(/\\u00a0/g, ' ')
                        .replace(/\\s+/g, ' ')
                        .trim()
                        .toLowerCase();
                    const visible = (el) => {
                        const s = window.getComputedStyle(el);
                        if (s.display === 'none' || s.visibility === 'hidden') return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    };

                    const els = [...document.querySelectorAll(
                        '[role="button"],button,input[type="submit"],input[type="button"],[jsname="M2UYVd"]'
                    )];

                    for (const el of els) {
                        if (!visible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') {
                            continue;
                        }
                        const raw = [
                            el.getAttribute('aria-label'),
                            el.getAttribute('data-value'),
                            el.getAttribute('value'),
                            el.innerText,
                            el.textContent,
                            el.getAttribute('title')
                        ].filter(Boolean);
                        const vals = raw.map(norm);
                        if (vals.some(v => names.has(v))) {
                            el.scrollIntoView({block: 'center', inline: 'center'});
                            el.click();
                            return raw.find(v => names.has(norm(v))) || 'submit';
                        }
                    }
                    return '';
                }"""
            )
            if label:
                run.log(f"   ↳ DOM Submit Detector V2 กดปุ่ม: {label}")
                return True
        except Exception as e:
            run.log(f"⚠️ DOM Submit Detector V2 ไม่สำเร็จ: {str(e)[:120]}")
        return False

    async def click_submit_button(self, run, page, btn):
        """กด Submit หลายวิธี: normal → Enter → mouse → force → DOM"""
        try:
            await btn.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        # 1) normal click
        try:
            await btn.click(timeout=5000)
            return True
        except Exception as e:
            run.log(f"⚠️ click ปกติไม่สำเร็จ: {str(e)[:100]}")

        # 2) keyboard Enter หลัง focus
        try:
            await btn.focus(timeout=2000)
            await btn.press("Enter", timeout=2500)
            run.log("   ↳ ใช้ Enter")
            return True
        except Exception:
            pass

        # 3) mouse click ตรงกลาง bounding box
        try:
            box = await btn.bounding_box()
            if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                await page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )
                run.log("   ↳ ใช้ mouse click ตรงกลางปุ่ม")
                return True
        except Exception:
            pass

        # 4) force click
        try:
            await btn.click(timeout=5000, force=True)
            run.log("   ↳ ใช้ force click")
            return True
        except Exception as e:
            run.log(f"⚠️ force click ไม่สำเร็จ: {str(e)[:100]}")

        # 5) DOM click
        try:
            await btn.evaluate("(el) => el.click()")
            run.log("   ↳ ใช้ DOM click")
            return True
        except Exception as e:
            run.log(f"⚠️ DOM click ไม่สำเร็จ: {str(e)[:100]}")

        # 6) full DOM detector fallback
        return await self.dom_submit_fallback(run, page)


    async def wait_submitted(self, page):
        for _ in range(24):
            if "formresponse" in page.url.lower():
                return True
            try:
                text = (await page.locator("body").inner_text(timeout=3000)).lower()
            except Exception:
                text = ""
            if any(k in text for k in SUCCESS_PHRASES):
                return True
            if any(k in text for k in ERROR_REQUIRED):
                return False
            await page.wait_for_timeout(500)
        return False

    async def fix_required_errors(self, run, page):
        """หาข้อบังคับที่ Google ฟ้องว่ายังว่าง แล้วลองตอบใหม่"""
        blocks = page.locator('div[role="listitem"]').filter(
            has_text=re.compile(r"คำถามนี้จำเป็น|This is a required question", re.I)
        )
        n = await blocks.count()
        if n == 0:
            return False

        fixed = False
        for i in range(n):
            block = blocks.nth(i)
            title, full, _req = await self.get_question_info(block)
            run.qfull = full
            run.note = ""
            run.log(f"🔁 ข้อบังคับที่ยังว่าง: {title} → ลองตอบอีกครั้ง")
            try:
                res = await self.answer_block(run, block, title)
            except Exception as e:
                run.log(f"⚠️ {e}")
                res = None
            if res:
                fixed = True
                run.add(title, res[0], res[1], req=True)

        return fixed

    async def submit_form(self, run, page):
        """กดส่งแบบ robust: หาใหม่ทุกครั้ง, scroll, force/DOM fallback, แก้ required แล้วลองซ้ำ"""
        for attempt in range(1, 5):
            btn = await self.find_submit_button(page, wait_ms=2400)

            if btn is None:
                run.log(f"⚠️ Locator ยังไม่พบปุ่มส่ง (ครั้งที่ {attempt}/4) → ใช้ DOM Detector V2")
                clicked = await self.dom_submit_fallback(run, page)
                if not clicked:
                    await page.wait_for_timeout(700)
                    continue
            else:
                run.log(f"📤 กดส่ง (ครั้งที่ {attempt}/4)")
                clicked = await self.click_submit_button(run, page, btn)

            if not clicked:
                await page.wait_for_timeout(600)
                continue

            if await self.wait_submitted(page):
                run.status = "✅ ส่งแล้ว"
                run.log("✅ ส่งฟอร์มเรียบร้อย")
                await self.take_screenshot(run, page, "sent")
                return "submitted"

            fixed = await self.fix_required_errors(run, page)
            if fixed:
                run.log("🔁 แก้ข้อบังคับแล้ว → จะลองกดส่งอีกครั้ง")
                await page.wait_for_timeout(500)
                continue

            run.log("⚠️ ยังไม่พบหน้าสำเร็จและไม่มี required error → ลองกดส่งใหม่")
            await page.wait_for_timeout(800)

        run.status = "⚠️ ส่งไม่สำเร็จ"
        run.log("⚠️ ส่งไม่สำเร็จหลังลองหลายวิธี กรุณาตรวจฟอร์มใน Browser")
        await self.take_screenshot(run, page, "failed")
        return "failed"

    # =========================================================
    # FILL ONE FORM
    # =========================================================

    async def fill_form(self, page, url, run, allow_submit=True):
        run.url = url
        run.log(f"🌐 เปิดฟอร์ม {url}")

        try:
            await self.retry(
                lambda: page.goto(url, wait_until="domcontentloaded", timeout=60000),
                "เปิดฟอร์ม",
                run.log,
            )
        except Exception as e:
            run.status = "❌ เปิดฟอร์มไม่ได้"
            run.log(f"❌ เปิดฟอร์มไม่ได้: {e}")
            return "error"

        try:
            await page.wait_for_selector(
                'div[role="listitem"], div[role="button"]', timeout=8000
            )
        except Exception:
            pass
        await page.wait_for_timeout(1000)

        problem = await self.page_problem(page)
        if problem == "closed":
            run.status = "⛔ ฟอร์มปิดรับ"
            run.log("⛔ ฟอร์มนี้ปิดรับคำตอบแล้ว ข้าม")
            return "closed"
        if problem == "notfound":
            run.status = "❌ ลิงก์ใช้ไม่ได้ (ไม่พบไฟล์)"
            run.log("❌ Google แจ้งว่าไม่พบไฟล์/ฟอร์มนี้ → ลิงก์ในโพสต์อาจไม่ใช่ฟอร์มจริงหรือไม่ครบ ข้าม")
            run.log(f"   ลิงก์ที่บอทเปิด: {url}")
            return "notfound"

        try:
            run.form_title = re.sub(
                r"\s*-\s*Google\s*(Forms|ฟอร์ม)\s*$", "", await page.title(), flags=re.I
            ).strip()
        except Exception:
            run.form_title = ""

        # ติ๊กบันทึกอีเมล (เฉพาะ checkbox ที่ไม่ได้อยู่ในคำถาม)
        try:
            boxes = page.locator(
                'xpath=//div[@role="checkbox"][not(ancestor::div[@role="listitem"])]'
            )
            if await boxes.count() > 0:
                box = boxes.first
                if await box.get_attribute("aria-checked") == "false":
                    await box.click()
                    run.log("✅ เลือกบันทึกอีเมล")
        except Exception:
            pass

        # หน้าแรกอาจเป็นหน้า Intro
        next_btn = await self.find_next_button(page)
        if next_btn and await page.locator('div[role="listitem"]').count() == 0:
            run.log("➡️ กดถัดไปหน้าแรก")
            await next_btn.click()
            await page.wait_for_timeout(1500)

        run.section = 1

        while not self.stop_event.is_set():
            run.log(f"\n{'=' * 30}\n📄 Section {run.section}")

            await self.process_questions(run, page)
            await page.wait_for_timeout(400)

            next_btn = await self.find_next_button(page)

            if next_btn:
                before_sig = await self.page_signature(page)
                run.log("➡️ ไป Section ถัดไป")
                await next_btn.click()
                await page.wait_for_timeout(1200)

                after_sig = await self.page_signature(page)
                next_still = await self.find_next_button(page)

                # ถ้ายังอยู่ Section เดิม มักเกิดจาก required ยังไม่ครบ
                if before_sig and before_sig == after_sig and next_still is not None:
                    run.log("⚠️ ยังอยู่ Section เดิม → ตรวจข้อบังคับที่ยังว่าง")
                    fixed_any = await self.fix_required_errors(run, page)
                    if fixed_any:
                        await next_still.click()
                        await page.wait_for_timeout(1200)
                        after_sig = await self.page_signature(page)

                if before_sig and before_sig == after_sig and await self.find_next_button(page) is not None:
                    run.status = "⚠️ ไป Section ถัดไปไม่ได้"
                    run.log("⚠️ ไปหน้าถัดไปไม่ได้ เพราะยังมีข้อที่ตอบไม่ครบ/ไม่ถูกต้อง")
                    return "blocked"

                run.section += 1
                if run.section > 30:
                    run.log("⚠️ หยุดเนื่องจากเกิน 30 Section")
                    break
                continue

            submit_btn = await self.find_submit_button(page, wait_ms=1800)
            submit_dom = False
            if submit_btn is None:
                submit_dom = await self.has_submit_button_dom(page)

            if submit_btn is not None or submit_dom:
                if submit_dom and submit_btn is None:
                    run.log("🟢 Submit Detector V2 พบปุ่มส่งผ่าน DOM")
                run.log("🟢 กรอกถึงหน้าสุดท้ายแล้ว")
                await self.take_screenshot(run, page, "before")

                blockers = [r for r in run.rows if r["source"] == "skip" and r.get("req")]
                auto = bool(self.settings.get("auto_submit")) and allow_submit

                if not auto:
                    run.status = "🟢 พร้อมตรวจ/กดส่ง" + ("" if allow_submit else " (โหมดทดสอบ ไม่ส่ง)")
                    run.log("👀 ไม่ได้ตั้งกดส่งอัตโนมัติ/โหมดทดสอบ → กรุณาตรวจแล้วกดส่งเอง")
                    return "ready"

                if blockers:
                    run.log(
                        f"⚠️ พบข้อบังคับที่รอบแรกยังตอบไม่ได้ {len(blockers)} ข้อ "
                        "→ จะลองให้ Google ชี้ข้อผิดและแก้ซ้ำก่อนตัดสินว่าส่งไม่ได้"
                    )

                for k in range(int(self.settings.get("submit_delay", 0)), 0, -1):
                    if self.stop_event.is_set():
                        break
                    run.log(f"⏳ จะกดส่งใน {k} วินาที (กดหยุดเพื่อยกเลิก)")
                    await self.sleep(1)

                if self.stop_event.is_set():
                    run.status = "⏹️ ยกเลิกก่อนส่ง"
                    return "cancelled"

                return await self.submit_form(run, page)

            run.log("⚠️ ยังไม่พบปุ่มถัดไปหรือส่ง → รอ DOM แล้วตรวจซ้ำ")
            await page.wait_for_timeout(1200)

            late_submit = await self.find_submit_button(page, wait_ms=1800)
            late_dom = False
            if late_submit is None:
                late_dom = await self.has_submit_button_dom(page)

            if late_submit is not None or late_dom:
                run.log("🟢 พบปุ่มส่งหลังรอ DOM (Detector V2)")
                auto = bool(self.settings.get("auto_submit")) and allow_submit
                if not auto:
                    run.status = "🟢 พร้อมตรวจ/กดส่ง" + ("" if allow_submit else " (โหมดทดสอบ ไม่ส่ง)")
                    return "ready"
                return await self.submit_form(run, page)

            run.log("⚠️ ตรวจซ้ำแล้วยังไม่พบปุ่มถัดไปหรือส่ง")
            break

        run.status = "⚠️ ไม่ครบ"
        return "incomplete"

    # =========================================================
    # X : LINK EXTRACTION
    # =========================================================

    @staticmethod
    def resolve_url(u):
        """คลี่ลิงก์ t.co เป็นลิงก์จริง (ใช้ UA แบบ curl เพื่อให้ได้ redirect ตรงๆ)"""
        try:
            for _ in range(4):
                if "t.co/" not in u:
                    break

                r = requests.get(
                    u,
                    allow_redirects=False,
                    timeout=6,
                    headers={"User-Agent": "curl/8.4.0"},
                )

                loc = r.headers.get("Location")

                if not loc:
                    # บางครั้ง t.co ตอบเป็นหน้า HTML ที่ redirect ด้วย meta/JS
                    m = re.search(r'URL=([^"\'>\s]+)', r.text, re.I) or re.search(
                        r'location\.replace\("([^"]+)"\)', r.text
                    )
                    if m:
                        loc = html.unescape(m.group(1)).replace("\\/", "/")

                if not loc:
                    break
                u = loc
        except Exception:
            pass
        return u

    @staticmethod
    def normalize_url(u):
        u = u.strip().rstrip(").,;")
        if u and not u.lower().startswith("http"):
            u = "https://" + u
        # ลิงก์แก้ไขฟอร์ม (/edit) เปิดกรอกไม่ได้ → เปลี่ยนเป็น /viewform
        u = re.sub(
            r"(docs\.google\.com/forms/d/[^?#]*?)/edit(?=[?#]|$)", r"\1/viewform", u
        )
        return u

    async def _links_from_anchors(self, article, want_card):
        """เก็บลิงก์ฟอร์มจาก <a> ในโพสต์ want_card=False อ่านเฉพาะลิงก์ในเนื้อข้อความ, True อ่านเฉพาะลิงก์ในการ์ดพรีวิว"""
        found = []
        anchors = article.locator("a[href]")
        n = await anchors.count()

        for j in range(n):
            a = anchors.nth(j)
            try:
                in_card = await a.evaluate(
                    "el => !!el.closest('[data-testid=\"card.wrapper\"]')"
                )
                if in_card != want_card:
                    continue

                href = await a.get_attribute("href") or ""
                title = await a.get_attribute("title") or ""

                cands = []
                if href:
                    cands.append(await asyncio.to_thread(self.resolve_url, href))
                if title:
                    cands.append(title)

                for c in cands:
                    # ข้อความที่ถูกตัด (มี …) ห้ามใช้
                    if "…" in c or "..." in c:
                        continue
                    c = self.normalize_url(c)
                    if FORM_PATTERN.search(c):
                        found.append(c)
                        break
            except Exception:
                continue

        return found

    async def extract_form_links(self, article):
        """
        คืนลิงก์ฟอร์มตามลำดับในโพสต์ "เก็บลิงก์ซ้ำไว้ด้วย"
        (ลิงก์เดียวกัน 2 ตำแหน่ง = 2 ลิงก์ เพื่อใช้กับข้อมูลคนละชุดได้)

        อ่านจากลิงก์ในเนื้อข้อความก่อน (กันนับซ้ำกับการ์ดพรีวิวที่โผล่คู่กัน)
        ถ้าในเนื้อข้อความไม่มีลิงก์เลย (โพสต์ที่มีแต่การ์ดพรีวิว ไม่มีลิงก์เป็นตัวหนังสือ)
        ให้ใช้ลิงก์จากการ์ดพรีวิวแทน จะได้ไม่พลาดแบบนี้
        """
        found = await self._links_from_anchors(article, want_card=False)

        if not found:
            found = await self._links_from_anchors(article, want_card=True)

        # สำรอง: ถ้ายังไม่เจอจาก anchor เลย ให้ลองอ่านจากข้อความทั้งหมด
        if not found:
            try:
                text = await article.inner_text()
                for m in URL_IN_TEXT.findall(text):
                    if "…" in m:
                        continue
                    u = self.normalize_url(await asyncio.to_thread(self.resolve_url, m))
                    if FORM_PATTERN.search(u):
                        found.append(u)
            except Exception:
                pass

        return found

    # =========================================================
    # X : MONITOR (หลายบัญชี)
    # =========================================================

    async def read_timeline(self, page):
        posts = []
        articles = page.locator(ART)
        n = min(await articles.count(), 6)

        for i in range(n):
            try:
                art = articles.nth(i)

                ctx = art.locator('[data-testid="socialContext"]')
                if await ctx.count() > 0:
                    t = ((await ctx.first.inner_text()) or "").lower()
                    if "pinned" in t or "ปักหมุด" in t:
                        continue

                link = art.locator("a:has(time)").first
                href = await link.get_attribute("href", timeout=2000)
                if not href or "/status/" not in href:
                    continue

                dt, txt = None, ""
                try:
                    t = link.locator("time").first
                    dt = await t.get_attribute("datetime", timeout=1500)
                    txt = (await t.inner_text(timeout=1500)) or ""
                except Exception:
                    pass

                pid = href.split("/status/")[-1].split("/")[0].split("?")[0]
                posts.append((pid, href, dt, txt))
            except Exception:
                continue

        return posts

    @staticmethod
    def post_age_seconds(dt, txt):
        """อายุโพสต์เป็นวินาที (ใช้เวลาจริงของโพสต์ก่อน ไม่ได้ค่อยอ่านจากข้อความ เช่น 6m) / ไม่รู้ = None"""
        if dt:
            try:
                d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
                return max(0.0, (datetime.now(timezone.utc) - d).total_seconds())
            except Exception:
                pass

        t = (txt or "").strip().lower()
        m = re.match(r"^(\d+)\s*(วินาที|วิ|s|นาที|น\.?|m|ชั่วโมง|ชม\.?|h|วัน|d)\s*$", t)
        if m:
            n = int(m.group(1))
            u = m.group(2)
            if u in ("วินาที", "วิ", "s"):
                return float(n)
            if u in ("นาที", "น", "น.", "m"):
                return n * 60.0
            if u in ("ชั่วโมง", "ชม", "ชม.", "h"):
                return n * 3600.0
            return n * 86400.0

        if t in ("now", "ตอนนี้"):
            return 0.0

        return None

    async def open_post_and_get_links(self, context, href, label):
        url = href if href.startswith("http") else "https://x.com" + href
        self.log(f"🖱️ [{label}] เข้าโพสต์: {url}")

        tab = await context.new_page()
        try:
            for attempt in range(1, 4):
                if self.stop_event.is_set():
                    break
                try:
                    await tab.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await tab.wait_for_selector(ART, timeout=10000)
                    await tab.wait_for_timeout(700)

                    article = tab.locator(ART).first
                    text = ""
                    try:
                        text = await article.inner_text()
                    except Exception:
                        pass

                    links = await self.extract_form_links(article)

                    if links or attempt >= 2:
                        return links, text

                    self.log(f"ℹ️ [{label}] ยังไม่เจอลิงก์ ลองอ่านซ้ำ...")
                    await self.sleep(1.2)

                except Exception as e:
                    self.log(f"⚠️ [{label}] อ่านโพสต์ไม่สำเร็จ (ครั้งที่ {attempt}/3): {str(e)[:80]}")
                    await self.sleep(1.5 * attempt)

            return [], ""
        finally:
            try:
                await tab.close()
            except Exception:
                pass

    async def handle_post(self, context, s, state, label, pid, href):
        links, text = await self.open_post_and_get_links(context, href, label)

        def mark_post_done():
            state.done_posts.add(pid)
            self.save_done(state.done_posts, state.done_forms)

        keys = s.get("keys") or set()
        if keys:
            day = self.extract_post_day(text)
            if day is not None and day not in keys:
                shown = ", ".join(f"{k:02d}" for k in sorted(keys))
                self.log(f"⏭️ [{label}] โพสต์นี้เป็นวันที่ {day:02d} ไม่ตรงกับคีย์ที่เปิดใช้งาน ({shown}) ข้าม")
                mark_post_done()
                return
            if day is None and not s.get("notag_process", True):
                self.log(f"⏭️ [{label}] โพสต์นี้ไม่มีป้ายวันที่ และตั้งค่าให้ข้ามโพสต์แบบนี้")
                mark_post_done()
                return

        keywords = s["keywords"]
        if keywords and not any(k in text.lower() for k in keywords):
            self.log(f"⏭️ [{label}] โพสต์นี้ไม่มีคีย์เวิร์ดที่กำหนด ข้าม")
            mark_post_done()
            return

        post_limit = s.get("post_limit", 0)
        if post_limit > 0 and state.processed >= post_limit:
            self.log(
                f"⛔ [{label}] ถึงจำนวนโพสต์สูงสุดที่ตั้งไว้ ({post_limit}) แล้ว ข้ามโพสต์นี้ "
                "(ปลดล็อกได้ในแท็บ X & ฟอร์ม)"
            )
            return
        state.processed += 1

        links = [u for u in links if u not in state.done_forms]

        if not links:
            self.log(f"ℹ️ [{label}] ไม่พบลิงก์ Google Form ใหม่ในโพสต์นี้")
            mark_post_done()
            return

        self.log(f"🔗 [{label}] พบ {len(links)} ลิงก์ฟอร์ม (กรอกพร้อมกันสูงสุด {s['parallel']})")
        for i, l in enumerate(links, start=1):
            self.log(f"   ลิงก์ {i}: {l}")

        jobs = []  # (tag, link, profile, pname)
        expected_per_link = {}
        for n, link in enumerate(links, start=1):
            reps = self.get_link_profiles(n, s)
            if not reps:
                self.log(f"⚠️ [{label}] ลิงก์ {n}: ไม่มีชุดข้อมูลที่ใช้ได้ตาม mapping → ข้าม")
                continue
            expected_per_link[link] = len(reps)
            for j, (profile, pname) in enumerate(reps, start=1):
                tag = f"{label}:{n}" if len(reps) == 1 else f"{label}:{n}.{j}"
                jobs.append((tag, link, profile, pname))

        if not jobs:
            self.log(f"⚠️ [{label}] ไม่มีงานกรอกที่ใช้ได้")
            return

        if len(jobs) != len(links):
            self.log(f"🔁 [{label}] ตั้งค่าให้กรอกซ้ำ รวมทั้งหมด {len(jobs)} รายการ (จาก {len(links)} ลิงก์)")

        async def run_one(tag, link, profile, pname):
            async with state.sem:
                if self.stop_event.is_set():
                    return link, "cancelled"

                run = FormRun(self, tag, profile, pname)
                run.log(f"เริ่ม {tag.split(':', 1)[-1]} (ใช้{pname})")

                fpage = await context.new_page()
                try:
                    result = await self.fill_form(fpage, link, run)
                except Exception as e:
                    run.log(f"❌ ฟอร์มนี้ผิดพลาด: {e}")
                    run.status = "❌ ผิดพลาด"
                    result = "error"

                self.add_summary(run)
                return link, result

        raw_results = await asyncio.gather(
            *[run_one(*job) for job in jobs],
            return_exceptions=True,
        )

        results = []
        per_link = {}
        for item in raw_results:
            if isinstance(item, Exception):
                results.append("error")
                continue
            link, result = item
            results.append(result)
            per_link.setdefault(link, []).append(result)

        # ทำเครื่องหมาย form ว่าทำแล้วเมื่อทุกชุดของลิงก์นั้นสำเร็จจริง
        terminal_ok = {"submitted"}
        for link, rs in per_link.items():
            if len(rs) == expected_per_link.get(link, 0) and rs and all(r in terminal_ok for r in rs):
                state.done_forms.add(link)

        # โพสต์จะเป็น done เมื่อทุกงานส่งสำเร็จ; ถ้ามีปัญหาให้มีโอกาส retry ในรอบถัดไป
        all_submitted = bool(results) and all(r == "submitted" for r in results)
        if all_submitted:
            state.done_posts.add(pid)

        self.save_done(state.done_posts, state.done_forms)

        sent = sum(1 for r in results if r == "submitted")
        ready = sum(1 for r in results if r == "ready")
        bad = len(jobs) - sent - ready
        self.notify(
            f"🔔 [{label}] ส่งแล้ว {sent} | รอตรวจ/กดส่งเอง {ready} | มีปัญหา {bad} (จาก {len(jobs)} รายการ)"
        )
        self.ui(self.show_summary, True)

    async def monitor_account(self, context, page, url, s, state):
        label = account_label(url)
        interval = max(2, min(10, int(s["interval"])))
        keywords = s["keywords"]

        self.log(f"👀 เฝ้า {url} (รีเฟรชทุก {interval} วิ)")
        if keywords:
            self.log(f"🔎 กรองโพสต์ด้วยคำ: {', '.join(keywords)}")

        try:
            await self.retry(
                lambda: page.goto(url, wait_until="domcontentloaded", timeout=60000),
                f"เปิด {label}",
                self.log,
            )
        except Exception as e:
            self.log(f"❌ [{label}] เปิดหน้า X ไม่ได้: {e}")
            return

        seen = set(state.done_posts)
        first = True
        fails = 0

        while not self.stop_event.is_set():
            if page.is_closed():
                self.log(f"🛑 [{label}] หน้าเฝ้าโพสต์ถูกปิดแล้ว หยุดเฝ้าบัญชีนี้")
                break
            try:
                if not first:
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector(ART, timeout=8000)
                fails = 0
            except Exception:
                if self.stop_event.is_set():
                    break
                fails += 1
                self.log(f"⚠️ [{label}] ยังไม่พบโพสต์ (ยังไม่ได้ล็อกอิน/หน้าโหลดช้า?) ครั้งที่ {fails}")
                if fails >= 3:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    except Exception:
                        pass
                    fails = 0
                await self.sleep(interval)
                continue

            new_posts = []
            for pid, href, dt, txt in await self.read_timeline(page):
                if pid not in seen:
                    seen.add(pid)
                    new_posts.append((pid, href, dt, txt))

            if first:
                skipped = len(new_posts) - (1 if (s["run_latest"] and new_posts) else 0)
                self.log(f"📌 [{label}] โพสต์เดิมที่ข้าม (baseline): {max(skipped, 0)} โพสต์")
                new_posts = new_posts[:1] if s["run_latest"] else []
                first = False

            for pid, href, dt, txt in reversed(new_posts):
                if self.stop_event.is_set():
                    break

                age = self.post_age_seconds(dt, txt)
                max_age = s["max_age"]

                if max_age > 0:
                    if age is None:
                        self.log(f"⏭️ [{label}] โพสต์ id={pid}: อ่านเวลาโพสต์ไม่ได้ ({txt or '-'}) ข้าม")
                        state.done_posts.add(pid)
                        self.save_done(state.done_posts, state.done_forms)
                        continue

                    if age > max_age * 60:
                        self.log(
                            f"⏭️ [{label}] โพสต์ id={pid} อายุ {age / 60:.1f} นาที "
                            f"(เกิน {max_age} นาที) ไม่กดเข้า"
                        )
                        state.done_posts.add(pid)
                        self.save_done(state.done_posts, state.done_forms)
                        continue

                age_txt = f" (อายุ {age:.0f} วินาที)" if age is not None else ""
                self.log(f"\n🆕 [{label}] พบโพสต์ใหม่ id={pid}{age_txt}")

                # ประมวลผลเป็น task แยก เพื่อให้ยังรีเฟรชเฝ้าต่อได้ระหว่างกรอกฟอร์ม
                task = asyncio.create_task(
                    self.handle_post(context, s, state, label, pid, href)
                )
                state.tasks.add(task)
                task.add_done_callback(state.tasks.discard)

            await self.sleep(interval)

    # =========================================================
    # BOT
    # =========================================================

    def validate_before_start(self, need_x):
        x_urls = self.get_x_urls()
        form_url = self.url_entry.get().strip()

        if need_x:
            if not x_urls and not form_url:
                messagebox.showwarning(
                    "แจ้งเตือน", "กรุณากรอก X URL หรือ Google Form URL อย่างน้อยหนึ่งช่อง"
                )
                return None
        else:
            if not form_url:
                messagebox.showwarning(
                    "แจ้งเตือน", "ปุ่มทดสอบใช้ช่อง Google Form เดี่ยว กรุณาใส่ URL ฟอร์มตัวอย่าง"
                )
                return None

        self.save_config(silent=True)

        keywords = [
            k.strip().lower()
            for k in re.split(r"[,，]", self.keyword_entry.get())
            if k.strip()
        ]

        s = {
            "x_urls": x_urls,
            "form_url": form_url,
            "interval": self.interval_var.get(),
            "max_age": max(0, int(self.max_age_var.get())),
            # ไม่บังคับเพดาน 10 แล้ว; ใช้ค่าที่ผู้ใช้กำหนดจริง (ขั้นต่ำ 1)
            "parallel": max(1, int(self.parallel_var.get())),
            "run_latest": self.run_latest_var.get(),
            "per_form": self.per_form_var.get(),
            "link_map": self.parse_link_map(self.link_map_box.get("1.0", "end")),
            "profiles": [dict(p) for p in self.profiles],
            "model": self.model_var.get().strip(),
            "provider": self.current_provider_key(),
            "openrouter_key": self.openrouter_key_var.get().strip(),
            "openrouter_model": self.openrouter_model_var.get().strip() or OPENROUTER_MODELS[0],
            "gemini_key": self.gemini_key_var.get().strip(),
            "gemini_model": self.gemini_model_var.get().strip() or GEMINI_MODELS[0],
            "anthropic_key": self.anthropic_key_var.get().strip(),
            "anthropic_model": self.anthropic_model_var.get().strip() or ANTHROPIC_MODELS[1],
            "custom_base": self.custom_base_var.get().strip() or OPENAI_DEFAULT_BASE,
            "custom_key": self.custom_key_var.get().strip(),
            "custom_model": self.custom_model_var.get().strip(),
            "headless": self.headless_var.get(),
            "screenshot": self.shot_var.get(),
            "auto_submit": self.auto_submit_var.get(),
            "submit_delay": max(0, int(self.submit_delay_var.get())),
            "ai_all": self.ai_all_var.get(),
            "ai_read_every": True,
            "ai_verify": self.ai_verify_var.get(),
            "ai_mode": "fast" if self.ai_mode_var.get().startswith("⚡") else "accurate",
            "ai_concurrency": max(1, min(64, int(self.ai_concurrency_var.get()))),
            "ai_auto_tune": self.ai_auto_tune_var.get(),
            "name_mode": NAME_MODES.get(self.name_mode_var.get(), "auto"),
            "keywords": keywords,
            "fixed": self.parse_fixed(self.answers_text),
            "knowledge": self.knowledge_box.get("1.0", "end").strip(),
            "keys": self.parse_keys(self.keys_entry.get()),
            "notag_process": self.notag_var.get(),
            "post_limit": 0 if self.unlock_var.get() else max(0, int(self.post_limit_var.get())),
        }
        return s

    def launch(self, s, mode):
        self.settings = s

        filled = sum(1 for _, a, _ in s["fixed"] if a)
        self.log(f"📚 คำถามที่กำหนดคำตอบเอง: {filled}/{len(s['fixed'])} ข้อมีคำตอบ")

        self.stop_event.clear()
        self.browser_closed = False
        self.busy = True
        self.running = True
        self.update_ui_state()

        threading.Thread(target=self.thread_main, args=(s, mode), daemon=True).start()

    def gate(self, need_x):
        if self.busy:
            return False
        if self.setup_state.get("browser") is False:
            messagebox.showwarning(
                "ยังไม่มี Browser",
                "ยังไม่พบ Browser สำหรับบอท กรุณาไปแท็บ 'ติดตั้ง/ตรวจระบบ' แล้วกด 🧰 ติดตั้ง Browser",
            )
            return False
        missing = []
        if not self.login["google"]:
            missing.append("Google")
        if need_x and not self.login["x"]:
            missing.append("X")
        if missing:
            messagebox.showwarning(
                "ยังไม่ได้ล็อกอิน",
                "กรุณาล็อกอิน " + " และ ".join(missing) + " ก่อน (กดปุ่ม 🔑 ด้านบน)",
            )
            return False
        return True

    def start_bot_thread(self):
        has_x = bool(self.get_x_urls())
        if not self.gate(need_x=has_x):
            return
        s = self.validate_before_start(need_x=has_x)
        if s:
            self.launch(s, "monitor" if s["x_urls"] else "single")

    def start_dry_run(self):
        if not self.gate(need_x=False):
            return
        s = self.validate_before_start(need_x=False)
        if s:
            self.launch(s, "dry")

    def stop_bot(self):
        self.stop_event.set()
        self.log("⏹️ กำลังหยุด...")

    def thread_main(self, s, mode):
        try:
            asyncio.run(self.run_async(s, mode))
        except Exception as e:
            self.log(f"\n❌ Error: {e}")
        finally:
            self.ui(self.finish_browser_op)

    async def wait_until_browser_closed(self, context):
        self.log("\nBrowser จะเปิดค้างไว้ ตรวจคำตอบแล้วกดส่งเองได้ (ปิด Browser เมื่อเสร็จ)")
        try:
            while not self.browser_closed and context.pages:
                await asyncio.sleep(1)
        except Exception:
            pass

    def _on_browser_closed(self):
        self.browser_closed = True
        self.stop_event.set()

    async def run_async(self, s, mode):
        self.log("🚀 เริ่ม Google Forms AI Assistant" + (" (โหมดทดสอบ)" if mode == "dry" else ""))

        self.ai_cache = {}
        self.ai_inflight = {}
        self.ai_success_streak = 0

        _p = s.get("provider")
        requested = max(1, min(64, int(s.get("ai_concurrency", 12))))
        # Local Ollama มักได้ประโยชน์จาก concurrency ต่ำกว่า cloud API
        initial = min(requested, 2) if _p == "ollama" else requested

        self.ai_target_limit = requested
        self.ai_limiter = AdaptiveAILimiter(initial, min_limit=1, max_limit=64)
        self.ai_sem = None
        self.log(
            f"⚡ AI concurrency เริ่มที่ {initial}"
            + (f" / เป้าหมาย {requested}" if initial != requested else "")
            + (" (Auto Tune เปิด)" if s.get("ai_auto_tune", True) else " (คงที่)")
        )

        await asyncio.to_thread(self.check_ai_ready, s)

        async with async_playwright() as p:
            headless = s["headless"]

            context = await self.launch_context(p, headless)
            context.on("close", lambda *_: self._on_browser_closed())

            blank = context.pages[0] if context.pages else None

            try:
                # ตรวจการล็อกอินจริงอีกครั้งก่อนเริ่ม
                st = self.cookie_status(await context.cookies())
                self.ui(self.set_login_status, st)
                need = ["google"] + (["x"] if mode == "monitor" else [])
                missing = [("Google" if n == "google" else "X") for n in need if not st[n]]
                if missing:
                    self.notify(f"🔒 ยังไม่ได้ล็อกอิน {' และ '.join(missing)} (เซสชันอาจหมดอายุ) กรุณากดปุ่มล็อกอินใหม่")
                    return

                if mode == "monitor":
                    done_posts, done_forms = self.load_done()
                    state = MonitorState(done_posts, done_forms, asyncio.Semaphore(s["parallel"]))

                    monitors = []
                    for i, url in enumerate(s["x_urls"]):
                        page = blank if (i == 0 and blank) else await context.new_page()
                        monitors.append(self.monitor_account(context, page, url, s, state))

                    await asyncio.gather(*monitors, return_exceptions=True)

                    if state.tasks:
                        self.log("⏳ รอฟอร์มที่กำลังกรอกให้เสร็จ/หยุด...")
                        await asyncio.gather(*list(state.tasks), return_exceptions=True)

                else:
                    page = blank if blank else await context.new_page()
                    label = "ทดสอบ" if mode == "dry" else "ฟอร์ม"
                    run = FormRun(self, label, s["profiles"][0], "ชุดหลัก")

                    result = await self.fill_form(
                        page, s["form_url"], run, allow_submit=(mode != "dry")
                    )
                    self.add_summary(run)

                    if result == "submitted":
                        self.notify("✅ กรอกและส่งฟอร์มเรียบร้อย")
                    elif result in ("ready", "blocked", "failed"):
                        self.notify("🔔 กรอกเสร็จแล้ว กรุณาตรวจฟอร์มใน Browser")
                    self.ui(self.show_summary, True)

                self.log("\n⏹️ หยุดเฝ้า/กรอกเสร็จแล้ว")

                if not headless and not self.browser_closed:
                    await self.wait_until_browser_closed(context)

            finally:
                try:
                    await context.close()
                except Exception:
                    pass


# =============================================================
# START
# =============================================================

if __name__ == "__main__":
    root = tk.Tk()
    app = FormBotGUI(root)
    root.mainloop()
