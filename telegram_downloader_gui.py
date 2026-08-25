#!/usr/bin/env python3
"""
Telegram Media Downloader v2.0 — GUI (tkinter + telethon)

- Очередь каналов: список, выбор одного/нескольких или все сразу
- Фильтры по типам файлов, каждый тип — в свою подпапку
- Период дат (С/По)
- Фильтр по размеру файлов (мин/макс МБ)
- Инкрементальная синхронизация (только новые сообщения)
- Экспорт текста сообщений в JSONL + CSV (полный бэкап канала)
- Дедупликация: быстрая по ID файла + точная по SHA-256
- Прокси: SOCKS5 или MTProto
"""
import asyncio
import csv
import hashlib
import json
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from telethon import TelegramClient, errors, connection
from telethon.tl.types import (
    MessageMediaWebPage,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
    DocumentAttributeSticker,
    DocumentAttributeAnimated,
)

# Рядом с exe (после сборки PyInstaller) или рядом со скриптом
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_FILE = BASE_DIR / "config_gui.json"
STATE_FILE = BASE_DIR / "downloader_state.json"
DEDUP_NAME = "dedup_index.json"

ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}

CATEGORIES = [
    ("photo", "Фото"),
    ("video", "Видео"),
    ("voice_audio", "Голосовые / аудио / музыка"),
    ("documents", "Документы (pdf, doc, xls...)"),
    ("archives", "Архивы (zip, rar, 7z...)"),
    ("gif_stickers", "GIF / стикеры"),
    ("other", "Прочие файлы"),
]
CATEGORY_DIRS = {
    "photo": "Photo", "video": "Video", "voice_audio": "Voice_Audio",
    "documents": "Documents", "archives": "Archives",
    "gif_stickers": "GIF_Stickers", "other": "Other",
}
DEFAULT_FILTERS = {"photo": True, "video": True, "voice_audio": True,
                   "documents": True, "archives": False, "gif_stickers": False, "other": True}


def safe_name(value, fallback="channel"):
    value = value or fallback
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:100]


def parse_date(text, end_of_day=False):
    text = (text or "").strip()
    if not text:
        return None
    dt = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        dt += timedelta(days=1)
    return dt


def parse_mb(text):
    text = (text or "").strip()
    if not text:
        return None
    return int(float(text.replace(",", ".")) * 1024 * 1024)


def classify_message(message):
    if message.photo:
        return "photo"
    doc = message.document
    if not doc:
        return None
    attrs = doc.attributes
    is_video = any(isinstance(a, DocumentAttributeVideo) for a in attrs)
    is_audio = any(isinstance(a, DocumentAttributeAudio) for a in attrs)
    is_sticker = any(isinstance(a, DocumentAttributeSticker) for a in attrs)
    is_animated = any(isinstance(a, DocumentAttributeAnimated) for a in attrs)
    file_name = ""
    for a in attrs:
        if getattr(a, "file_name", None):
            file_name = a.file_name
            break
    ext = Path(file_name).suffix.lower()
    if is_sticker or is_animated:
        return "gif_stickers"
    if is_video:
        return "video"
    if is_audio:
        return "voice_audio"
    if ext in ARCHIVE_EXT:
        return "archives"
    if file_name:
        return "documents"
    return "other"


def file_uid(message):
    if message.document:
        return f"doc:{message.document.id}"
    if message.photo:
        return f"photo:{message.photo.id}"
    return None


def sha256_of(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Media Downloader 2.0")
        self.geometry("860x980")
        self.minsize(720, 820)

        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.settings = None
        self._state = {}
        self._dedup = {"file_ids": set(), "hashes": {}}

        self._build_ui()
        self._load_config()
        self.after(100, self._poll_events)

    # ================= UI =================
    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        api = ttk.LabelFrame(frm, text="Telegram API (my.telegram.org — один раз)", padding=6)
        api.pack(fill="x")
        self.api_id = self._row(api, 0, "api_id", width=14)
        self.api_hash = self._row(api, 0, "api_hash", col=2, show="*", width=30)
        self.phone = self._row(api, 1, "Телефон (+7...)", width=14)

        px = ttk.LabelFrame(frm, text="Прокси (необязательно)", padding=6)
        px.pack(fill="x", pady=(6, 0))
        self.use_proxy = tk.BooleanVar(value=False)
        ttk.Checkbutton(px, text="Использовать прокси", variable=self.use_proxy).grid(row=0, column=0, sticky="w")
        ttk.Label(px, text="Тип").grid(row=0, column=1, sticky="e")
        self.proxy_type = ttk.Combobox(px, values=["SOCKS5", "MTProto"], state="readonly", width=9)
        self.proxy_type.grid(row=0, column=2, padx=4)
        self.proxy_type.set("SOCKS5")
        ttk.Label(px, text="Хост").grid(row=0, column=3, sticky="e")
        self.proxy_host = ttk.Entry(px, width=16)
        self.proxy_host.grid(row=0, column=4, padx=4)
        ttk.Label(px, text="Порт").grid(row=0, column=5, sticky="e")
        self.proxy_port = ttk.Entry(px, width=7)
        self.proxy_port.grid(row=0, column=6, padx=4)
        ttk.Label(px, text="Логин").grid(row=1, column=3, sticky="e")
        self.proxy_user = ttk.Entry(px, width=16)
        self.proxy_user.grid(row=1, column=4, padx=4, pady=2)
        ttk.Label(px, text="Пароль").grid(row=1, column=5, sticky="e")
        self.proxy_pass = ttk.Entry(px, width=12, show="*")
        self.proxy_pass.grid(row=1, column=6, padx=4)
        ttk.Label(px, text="MTProto secret").grid(row=2, column=0, sticky="e")
        self.proxy_secret = ttk.Entry(px, width=40)
        self.proxy_secret.grid(row=2, column=1, columnspan=4, sticky="w", padx=4)
        ttk.Label(px, text="(логин/пароль — для SOCKS5; secret — для MTProto)").grid(row=2, column=4, columnspan=3, sticky="w")

        chf = ttk.LabelFrame(frm, text="Каналы (очередь)", padding=6)
        chf.pack(fill="x", pady=(6, 0))
        self.channel_entry = ttk.Entry(chf)
        self.channel_entry.grid(row=0, column=0, columnspan=3, sticky="ew", padx=(0, 6))
        ttk.Button(chf, text="Добавить в список", command=self._add_channel).grid(row=0, column=3)
        self.channels_box = tk.Listbox(chf, height=4, selectmode="extended", exportselection=False)
        self.channels_box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=4)
        ttk.Button(chf, text="Удалить выбранные", command=self._remove_channels).grid(row=1, column=3, sticky="n")
        ttk.Button(chf, text="Очистить", command=lambda: self.channels_box.delete(0, "end")).grid(row=1, column=3, sticky="s")
        self.all_channels = tk.BooleanVar(value=True)
        ttk.Checkbutton(chf, text="Скачать ВСЕ каналы из списка (иначе — только выделенные)",
                        variable=self.all_channels).grid(row=2, column=0, columnspan=4, sticky="w")
        chf.columnconfigure(1, weight=1)

        out = ttk.Frame(frm)
        out.pack(fill="x", pady=(6, 0))
        ttk.Label(out, text="Папка сохранения").pack(side="left")
        self.outdir = ttk.Entry(out)
        self.outdir.pack(side="left", fill="x", expand=True, padx=6)
        self.outdir.insert(0, "telegram_downloads")
        ttk.Button(out, text="Обзор...", command=self._browse).pack(side="left")

        per = ttk.LabelFrame(frm, text="Период и размер (пусто = без ограничений)", padding=6)
        per.pack(fill="x", pady=(6, 0))
        ttk.Label(per, text="С даты").grid(row=0, column=0)
        self.date_from = ttk.Entry(per, width=12)
        self.date_from.grid(row=0, column=1, padx=4)
        ttk.Label(per, text="По дату (вкл.)").grid(row=0, column=2)
        self.date_to = ttk.Entry(per, width=12)
        self.date_to.grid(row=0, column=3, padx=4)
        ttk.Label(per, text="ГГГГ-ММ-ДД").grid(row=0, column=4, sticky="w")
        ttk.Label(per, text="Мин. МБ").grid(row=0, column=5, sticky="e")
        self.min_mb = ttk.Entry(per, width=7)
        self.min_mb.grid(row=0, column=6, padx=4)
        ttk.Label(per, text="Макс. МБ").grid(row=0, column=7, sticky="e")
        self.max_mb = ttk.Entry(per, width=7)
        self.max_mb.grid(row=0, column=8, padx=4)

        flt = ttk.LabelFrame(frm, text="Типы файлов (каждый — в свою подпапку)", padding=6)
        flt.pack(fill="x", pady=(6, 0))
        self.filter_vars = {}
        for i, (key, label) in enumerate(CATEGORIES):
            var = tk.BooleanVar(value=DEFAULT_FILTERS[key])
            self.filter_vars[key] = var
            ttk.Checkbutton(flt, text=label, variable=var).grid(
                row=i // 4, column=i % 4, sticky="w", padx=8, pady=1)

        opt = ttk.LabelFrame(frm, text="Опции", padding=6)
        opt.pack(fill="x", pady=(6, 0))
        self.opt_incremental = tk.BooleanVar(value=False)
        self.opt_export = tk.BooleanVar(value=True)
        self.opt_dedup = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="Только новые (инкрементально)", variable=self.opt_incremental).grid(row=0, column=0, sticky="w", padx=8)
        ttk.Checkbutton(opt, text="Экспорт текста сообщений (JSONL+CSV)", variable=self.opt_export).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Checkbutton(opt, text="Пропускать дубликаты (ID + SHA-256)", variable=self.opt_dedup).grid(row=0, column=2, sticky="w", padx=8)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=8)
        self.start_btn = ttk.Button(btns, text="▶  Старт", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="■  Стоп", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.status = ttk.Label(btns, text="Готов к работе")
        self.status.pack(side="left", padx=12)

        logf = ttk.LabelFrame(frm, text="Журнал", padding=4)
        logf.pack(fill="both", expand=True)
        self.log = tk.Text(logf, state="disabled", wrap="word",
                           bg="#1b1b1b", fg="#d8d8d8", insertbackground="#d8d8d8",
                           font=("Consolas", 10))
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _row(self, parent, r, label, col=0, show=None, width=None):
        ttk.Label(parent, text=label).grid(row=r, column=col, sticky="w")
        e = ttk.Entry(parent, show=show, width=width)
        e.grid(row=r, column=col + 1, sticky="w", padx=6, pady=2)
        return e

    def _browse(self):
        d = filedialog.askdirectory(parent=self)
        if d:
            self.outdir.delete(0, "end")
            self.outdir.insert(0, d)

    def _add_channel(self):
        v = self.channel_entry.get().strip()
        existing = self.channels_box.get(0, "end")
        if v and v not in existing:
            self.channels_box.insert("end", v)
        self.channel_entry.delete(0, "end")

    def _remove_channels(self):
        for i in reversed(self.channels_box.curselection()):
            self.channels_box.delete(i)

    # ================= конфиг / состояние =================
    def _load_config(self):
        if not CONFIG_FILE.exists():
            return
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        self.api_id.insert(0, str(cfg.get("api_id", "")))
        self.api_hash.insert(0, cfg.get("api_hash", ""))
        self.phone.insert(0, cfg.get("phone", ""))
        if cfg.get("outdir"):
            self.outdir.delete(0, "end")
            self.outdir.insert(0, cfg["outdir"])
        self.date_from.insert(0, cfg.get("date_from", ""))
        self.date_to.insert(0, cfg.get("date_to", ""))
        self.min_mb.insert(0, cfg.get("min_mb", ""))
        self.max_mb.insert(0, cfg.get("max_mb", ""))
        for ch in cfg.get("channels", []):
            self.channels_box.insert("end", ch)
        for k, v in cfg.get("filters", {}).items():
            if k in self.filter_vars:
                self.filter_vars[k].set(bool(v))
        p = cfg.get("proxy", {})
        self.use_proxy.set(bool(p.get("enabled", False)))
        if p.get("type"):
            self.proxy_type.set(p["type"])
        for widget, key in ((self.proxy_host, "host"), (self.proxy_port, "port"),
                            (self.proxy_user, "user"), (self.proxy_pass, "password"),
                            (self.proxy_secret, "secret")):
            if p.get(key):
                widget.insert(0, str(p[key]))
        self.opt_incremental.set(bool(cfg.get("opt_incremental", False)))
        self.opt_export.set(bool(cfg.get("opt_export", True)))
        self.opt_dedup.set(bool(cfg.get("opt_dedup", True)))

    def _save_config(self):
        cfg = {
            "api_id": self.api_id.get().strip(),
            "api_hash": self.api_hash.get().strip(),
            "phone": self.phone.get().strip(),
            "outdir": self.outdir.get().strip(),
            "date_from": self.date_from.get().strip(),
            "date_to": self.date_to.get().strip(),
            "min_mb": self.min_mb.get().strip(),
            "max_mb": self.max_mb.get().strip(),
            "channels": list(self.channels_box.get(0, "end")),
            "filters": {k: v.get() for k, v in self.filter_vars.items()},
            "proxy": {
                "enabled": self.use_proxy.get(),
                "type": self.proxy_type.get(),
                "host": self.proxy_host.get().strip(),
                "port": self.proxy_port.get().strip(),
                "user": self.proxy_user.get().strip(),
                "password": self.proxy_pass.get(),
                "secret": self.proxy_secret.get().strip(),
            },
            "opt_incremental": self.opt_incremental.get(),
            "opt_export": self.opt_export.get(),
            "opt_dedup": self.opt_dedup.get(),
        }
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_state(self):
        try:
            self._state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
        except Exception:
            self._state = {}

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _load_dedup(self, outdir):
        f = Path(outdir) / DEDUP_NAME
        try:
            raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except Exception:
            raw = {}
        self._dedup = {
            "file_ids": set(raw.get("file_ids", [])),
            "hashes": dict(raw.get("hashes", {})),
        }

    def _save_dedup(self, outdir):
        f = Path(outdir) / DEDUP_NAME
        f.write_text(json.dumps({
            "file_ids": sorted(self._dedup["file_ids"]),
            "hashes": self._dedup["hashes"],
        }, ensure_ascii=False), encoding="utf-8")

    # ================= журнал / очередь =================
    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "status":
                    self.status.configure(text=payload)
                elif kind == "done":
                    self._on_finished()
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def gui_prompt(self, title, prompt, show=None):
        ev = threading.Event()
        box = {}

        def ask():
            box["value"] = simpledialog.askstring(title, prompt, show=show, parent=self)
            ev.set()

        self.after(0, ask)
        ev.wait()
        return box["value"]

    # ================= запуск / остановка =================
    def start(self):
        try:
            api_id = int(self.api_id.get().strip())
        except ValueError:
            messagebox.showerror("Ошибка", "api_id должен быть числом.", parent=self)
            return
        if not self.api_hash.get().strip() or not self.phone.get().strip():
            messagebox.showerror("Ошибка", "Заполните api_hash и телефон.", parent=self)
            return

        if self.all_channels.get():
            channels = list(self.channels_box.get(0, "end"))
        else:
            channels = [self.channels_box.get(i) for i in self.channels_box.curselection()]
        typed = self.channel_entry.get().strip()
        if not channels and typed:
            channels = [typed]
        if not channels:
            messagebox.showerror("Ошибка", "Добавьте хотя бы один канал в список.", parent=self)
            return
        if not any(v.get() for v in self.filter_vars.values()) and not self.opt_export.get():
            messagebox.showerror("Ошибка", "Выберите типы файлов или включите экспорт текста.", parent=self)
            return

        try:
            date_from = parse_date(self.date_from.get())
            date_to = parse_date(self.date_to.get(), end_of_day=True)
            min_bytes = parse_mb(self.min_mb.get())
            max_bytes = parse_mb(self.max_mb.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Проверьте формат дат (ГГГГ-ММ-ДД) и размеров (число МБ).", parent=self)
            return
        if date_from and date_to and date_from >= date_to:
            messagebox.showerror("Ошибка", "Дата 'С' должна быть раньше даты 'По'.", parent=self)
            return

        proxy = {"enabled": self.use_proxy.get(), "type": self.proxy_type.get(),
                 "host": self.proxy_host.get().strip(), "port": self.proxy_port.get().strip(),
                 "user": self.proxy_user.get().strip(), "password": self.proxy_pass.get(),
                 "secret": self.proxy_secret.get().strip()}
        if proxy["enabled"]:
            if not proxy["host"] or not proxy["port"].isdigit():
                messagebox.showerror("Ошибка", "Для прокси укажите хост и числовой порт.", parent=self)
                return
            if proxy["type"] == "MTProto" and not proxy["secret"]:
                messagebox.showerror("Ошибка", "Для MTProto-прокси нужен secret.", parent=self)
                return

        self.settings = {
            "api_id": api_id,
            "api_hash": self.api_hash.get().strip(),
            "phone": self.phone.get().strip(),
            "channels": channels,
            "outdir": self.outdir.get().strip() or "telegram_downloads",
            "date_from": date_from,
            "date_to": date_to,
            "min_bytes": min_bytes,
            "max_bytes": max_bytes,
            "filters": {k: v.get() for k, v in self.filter_vars.items()},
            "proxy": proxy,
            "incremental": self.opt_incremental.get(),
            "export": self.opt_export.get(),
            "dedup": self.opt_dedup.get(),
        }
        self._save_config()
        self._load_state()
        self._load_dedup(self.settings["outdir"])

        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.configure(text="Подключение...")
        self._append_log("=" * 60)
        self._append_log(f"Запуск. Каналов в очереди: {len(channels)}")

        self.worker = threading.Thread(target=self._worker_main, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.status.configure(text="Остановка после текущего файла...")
        self.stop_btn.configure(state="disabled")

    def _on_finished(self):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    # ================= рабочий поток =================
    def _worker_main(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run(self.settings))
        except Exception as e:
            hint = ""
            if "socks" in str(e).lower():
                hint = " (для SOCKS5 нужен пакет: pip install python-socks)"
            self.events.put(("log", f"[FATAL] {type(e).__name__}: {e}{hint}"))
        finally:
            loop.close()
            self.events.put(("done", None))

    def _make_client(self, st):
        kwargs = {}
        p = st["proxy"]
        if p["enabled"]:
            if p["type"] == "MTProto":
                kwargs["connection"] = connection.ConnectionTcpMTProxyRandomizedIntermediate
                kwargs["proxy"] = (p["host"], int(p["port"]), p["secret"])
                self.events.put(("log", f"Прокси: MTProto {p['host']}:{p['port']}"))
            else:
                kwargs["proxy"] = ("socks5", p["host"], int(p["port"]), True,
                                   p["user"] or None, p["password"] or None)
                self.events.put(("log", f"Прокси: SOCKS5 {p['host']}:{p['port']}"))
        session = str(BASE_DIR / ("session_" + re.sub(r"\D", "", st["phone"])))
        return TelegramClient(session, st["api_id"], st["api_hash"], **kwargs)

    async def _run(self, st):
        client = self._make_client(st)
        self.events.put(("status", "Авторизация..."))
        await client.start(
            phone=lambda: st["phone"],
            code_callback=lambda: self.gui_prompt(
                "Код подтверждения", "Введите код, который пришёл в Telegram:"),
            password=lambda: self.gui_prompt(
                "Двухфакторная защита", "Введите пароль 2FA:", show="*"),
        )
        self.events.put(("log", "Авторизация успешна."))

        total = {"dl": 0, "skip": 0, "dup": 0, "fail": 0}
        try:
            for ch in st["channels"]:
                if self.stop_event.is_set():
                    break
                await self._download_channel(client, ch, st, total)
        finally:
            await client.disconnect()
            self._save_state()
            self._save_dedup(st["outdir"])

        self.events.put(("log",
            f"ИТОГО по всем каналам: скачано {total['dl']}, пропущено {total['skip']}, "
            f"дубликатов {total['dup']}, ошибок {total['fail']}."))
        self.events.put(("status", "Завершено"))

    async def _download_channel(self, client, channel, st, total):
        self.events.put(("log", "-" * 60))
        self.events.put(("log", f"Канал: {channel}"))
        self.events.put(("status", f"Канал: {channel}"))

        try:
            entity = await client.get_entity(channel)
        except Exception as exc:
            self.events.put(("log", f"  Канал не найден: {exc}"))
            total["fail"] += 1
            return

        channel_name = safe_name(
            getattr(entity, "title", None)
            or getattr(entity, "username", None)
            or str(getattr(entity, "id", "channel"))
        )
        base_dir = Path(st["outdir"]) / channel_name
        base_dir.mkdir(parents=True, exist_ok=True)
        cat_dirs = {}
        for cat, enabled in st["filters"].items():
            if enabled:
                d = base_dir / CATEGORY_DIRS[cat]
                d.mkdir(parents=True, exist_ok=True)
                cat_dirs[cat] = d

        username = getattr(entity, "username", None)
        chan_key = str(getattr(entity, "id", channel))

        # Экспорт текста
        fj = fc = writer = None
        if st["export"]:
            jsonl_path = base_dir / "messages.jsonl"
            csv_path = base_dir / "messages.csv"
            csv_new = not csv_path.exists()
            fj = open(jsonl_path, "a", encoding="utf-8")
            fc = open(csv_path, "a", encoding="utf-8-sig", newline="")
            writer = csv.writer(fc)
            if csv_new:
                writer.writerow(["id", "date", "text", "category", "file", "link"])

        # Параметры обхода
        iter_kwargs = {"reverse": True}
        if st["date_from"]:
            iter_kwargs["offset_date"] = st["date_from"]
        last_id = self._state.get(chan_key, 0)
        if st["incremental"] and last_id:
            iter_kwargs["min_id"] = last_id
            self.events.put(("log", f"  Инкрементально: только сообщения новее ID {last_id}"))

        dl = skip = dup = fail = 0
        try:
            async for message in client.iter_messages(entity, **iter_kwargs):
                if self.stop_event.is_set():
                    self.events.put(("log", "  Остановлено пользователем."))
                    break

                if st["date_to"] and message.date and message.date >= st["date_to"]:
                    self.events.put(("log", f"  Достигнута верхняя дата (сообщение {message.id})."))
                    break

                self._state[chan_key] = message.id
                if message.id % 100 == 0:
                    self._save_state()

                category = classify_message(message)
                saved_name = ""

                if message.media and not isinstance(message.media, MessageMediaWebPage) and category:
                    if not st["filters"].get(category, False):
                        skip += 1
                    else:
                        size = getattr(message.file, "size", None) if message.file else None
                        if size is not None and (
                                (st["min_bytes"] and size < st["min_bytes"]) or
                                (st["max_bytes"] and size > st["max_bytes"])):
                            skip += 1
                        else:
                            uid = file_uid(message)
                            if st["dedup"] and uid and uid in self._dedup["file_ids"]:
                                dup += 1
                                saved_name = "(дубликат, пропущен)"
                            else:
                                target = cat_dirs[category]
                                last_pct = [-1]

                                def progress(recv, total_bytes, _mid=message.id, _lp=last_pct):
                                    if total_bytes:
                                        pct = recv * 100 // total_bytes
                                        if pct // 10 != _lp[0] // 10:
                                            _lp[0] = pct
                                            self.events.put(("status", f"{channel_name} · файл {_mid}: {pct}%"))

                                try:
                                    result = await message.download_media(
                                        file=target, progress_callback=progress)
                                    if result:
                                        rpath = Path(result)
                                        if st["dedup"]:
                                            digest = sha256_of(rpath)
                                            if digest in self._dedup["hashes"]:
                                                rpath.unlink(missing_ok=True)
                                                dup += 1
                                                saved_name = f"(дубликат {self._dedup['hashes'][digest]})"
                                                self.events.put(("log",
                                                    f"  [dup] {message.id}: {rpath.name}"))
                                            else:
                                                self._dedup["hashes"][digest] = rpath.name
                                                if uid:
                                                    self._dedup["file_ids"].add(uid)
                                                dl += 1
                                                saved_name = rpath.name
                                                self.events.put(("log",
                                                    f"  [{category}] {message.id}: {rpath.name}"))
                                        else:
                                            dl += 1
                                            saved_name = rpath.name
                                            self.events.put(("log",
                                                f"  [{category}] {message.id}: {rpath.name}"))
                                    else:
                                        skip += 1
                                except errors.FloodWaitError as fw:
                                    self.events.put(("log", f"  FloodWait: пауза {fw.seconds} сек."))
                                    await asyncio.sleep(fw.seconds)
                                except Exception as exc:
                                    fail += 1
                                    self.events.put(("log", f"  [ERR] {message.id}: {exc}"))

                if writer:
                    link = (f"https://t.me/{username}/{message.id}" if username
                            else f"https://t.me/c/{chan_key}/{message.id}")
                    row = [message.id,
                           message.date.isoformat(timespec="seconds") if message.date else "",
                           message.message or "",
                           category or "",
                           saved_name,
                           link]
                    writer.writerow(row)
                    fj.write(json.dumps({
                        "id": row[0], "date": row[1], "text": row[2],
                        "category": row[3], "file": row[4], "link": row[5],
                    }, ensure_ascii=False) + "\n")
        finally:
            if fj:
                fj.close()
            if fc:
                fc.close()
            self._save_state()

        total["dl"] += dl
        total["skip"] += skip
        total["dup"] += dup
        total["fail"] += fail
        self.events.put(("log",
            f"  Канал готов: скачано {dl}, пропущено {skip}, дубликатов {dup}, ошибок {fail}."))


if __name__ == "__main__":
    App().mainloop()
