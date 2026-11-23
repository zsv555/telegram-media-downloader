# Telegram Media Downloader 2.1

[Русский](#-русский) · [English](#-english)

GUI-приложение для скачивания медиафайлов и полного бэкапа Telegram-каналов через ваш аккаунт.
A GUI app to download media and make full backups of Telegram channels via your own account.

---

## 🇷🇺 Русский

### О программе

Программа с графическим интерфейсом (tkinter + [Telethon](https://github.com/LonamiWebs/Telethon)), которая скачивает файлы из Telegram-каналов через ваш обычный аккаунт и делает полный бэкап канала, включая текст сообщений и все ссылки.

### Возможности

- **Очередь каналов** — список каналов: скачивать выбранные или все сразу
- **Фильтр по типам файлов** — фото, видео, голосовые/аудио, документы, архивы, GIF/стикеры, прочее; каждый тип сохраняется в свою подпапку
- **Период дат** — скачивание только за указанный промежуток (С даты / По дату)
- **Фильтр по размеру** — минимальный и максимальный размер файла в МБ (размер известен до скачивания, трафик не тратится)
- **Инкрементальная синхронизация** — при повторном запуске скачиваются только новые сообщения
- **Экспорт текста сообщений** — `messages.jsonl` + `messages.csv`: ID, дата, текст, тип вложения, имя файла, ссылка на сообщение
- **Сбор ссылок** — извлечение всех ссылок из текстов постов, скрытых гиперссылок, кнопок под постами и превью-карточек: `links.csv` + `links_unique.txt`
- **Дедупликация** — двухуровневая: по ID файла (до скачивания) и по SHA-256 (после); дубликаты пропускаются или удаляются
- **Прокси** — SOCKS5 (с логином/паролем) и MTProto (host/port/secret)
- **Авторизация в окне** — код из Telegram и пароль 2FA запрашиваются в диалоговых окнах, консоль не нужна

### Требования

- Python 3.9 или новее
- Windows / macOS / Linux
- Аккаунт Telegram и свои `api_id` / `api_hash` (см. ниже)

### Установка

```bash
git clone https://github.com/zsv555/telegram-media-downloader.git
cd telegram-media-downloader
python -m pip install -r requirements.txt
```

### Получение api_id и api_hash (один раз)

1. Откройте https://my.telegram.org и войдите по номеру телефона.
2. Перейдите в **API development tools**.
3. Заполните форму (достаточно полей *App title* и *Short name*) и нажмите **Create application**.
4. Скопируйте `api_id` и `api_hash`. **Не публикуйте `api_hash` — это секрет.**

> Если my.telegram.org не открывается с вашего IP, добавьте в файл `hosts`
> (`C:\Windows\System32\drivers\etc\hosts`) строку:
> `149.154.167.220 my.telegram.org`

### Запуск

```bash
python telegram_downloader_gui.py
```

При первом запуске программа попросит код из Telegram и пароль двухфакторной защиты (если включён) — вводится в окне программы. Сессия сохраняется, повторная авторизация не потребуется.

### Что заполнять в окне

| Поле | Что вводить |
|---|---|
| `api_id` / `api_hash` | Данные приложения с my.telegram.org (вводятся один раз, сохраняются в `config_gui.json`) |
| Телефон | Номер в международном формате, например `+79991234567` |
| Каналы | `@username`, ссылка `https://t.me/...` или ID. Кнопка «Добавить в список» — для очереди |
| Папка сохранения | Куда складывать файлы (создаётся автоматически) |
| С даты / По дату | Период в формате `ГГГГ-ММ-ДД`. Пусто = вся история |
| Мин. МБ / Макс. МБ | Ограничение размера файлов. Пусто = без ограничений |
| Типы файлов | Галочки: что скачивать. Каждый тип — в свою подпапку |
| Только новые | Инкрементальная синхронизация: докачивать лишь новые сообщения |
| Экспорт текста | Писать `messages.jsonl` и `messages.csv` (полный бэкап текстов) |
| Собирать ссылки | Извлекать все ссылки из сообщений в `links.csv` и `links_unique.txt` (работает независимо от фильтров файлов) |
| Пропускать дубликаты | Дедупликация по ID файла и SHA-256 |
| Прокси | SOCKS5: хост, порт, логин/пароль. MTProto: хост, порт, secret |

### Структура выгрузки

```
telegram_downloads/
└── Имя_канала/
    ├── Photo/  Video/  Voice_Audio/  Documents/
    ├── Archives/  GIF_Stickers/  Other/
    ├── messages.jsonl      # тексты сообщений (JSON Lines)
    ├── messages.csv        # то же в CSV (открывается в Excel)
    ├── links.csv           # все ссылки: текст, кнопки, превью
    └── links_unique.txt    # уникальные ссылки, по одной на строку
```

### Сборка в .exe (Windows)

```bash
python -m pip install pyinstaller
pyinstaller --onefile --noconsole --name TelegramDownloader telegram_downloader_gui.py
```

Готовый `TelegramDownloader.exe` появится в папке `dist/`. Python для запуска exe не нужен.

### Файлы, которые создаёт программа (НЕ публиковать!)

| Файл | Назначение |
|---|---|
| `config_gui.json` | Ваши настройки, включая `api_hash` и телефон |
| `session_*.session` | Авторизованная сессия — даёт доступ к аккаунту! |
| `downloader_state.json` | Прогресс инкрементальной синхронизации |
| `dedup_index.json` | База хэшей скачанных файлов |

Все они уже добавлены в `.gitignore`. **Никогда не коммитьте их в репозиторий.**

### FAQ

**FloodWait в журнале** — Telegram просит паузу; программа ждёт и продолжает сама, это нормально.

**«Канал не найден»** — для приватного канала ваш аккаунт должен быть его участником; используйте ID или ссылку-приглашение.

**SOCKS5 не работает** — убедитесь, что установлен пакет `python-socks` (он в `requirements.txt`).

### Отказ от ответственности

Программа предназначена для личного бэкапа каналов, к которым у вас есть законный доступ. Использование Telegram API регулируется [условиями Telegram](https://core.telegram.org/api/terms): спам, флуд и накрутки приводят к блокировке аккаунта. Автор не несёт ответственности за использование программы.

### Лицензия

[MIT](LICENSE)

---

## 🇬🇧 English

### Overview

A desktop GUI application (tkinter + [Telethon](https://github.com/LonamiWebs/Telethon)) that downloads media files from Telegram channels through your own account and creates a full channel backup, including message texts and all links.

### Features

- **Channel queue** — manage a list of channels; download selected ones or all at once
- **File type filters** — photos, videos, voice/audio, documents, archives, GIFs/stickers, other; each type goes to its own subfolder
- **Date range** — download only messages within a given period (From / To)
- **Size filter** — min/max file size in MB (size is known before downloading, so no traffic is wasted)
- **Incremental sync** — on subsequent runs only new messages are downloaded
- **Message text export** — `messages.jsonl` + `messages.csv`: ID, date, text, media type, saved file name, message link
- **Link harvesting** — extracts every link from post text, hidden hyperlinks, inline buttons and link previews: `links.csv` + `links_unique.txt`
- **Deduplication** — two-level: by file ID (before download) and by SHA-256 (after); duplicates are skipped or removed
- **Proxy support** — SOCKS5 (with auth) and MTProto (host/port/secret)
- **In-app authorization** — the Telegram code and 2FA password are requested in dialog windows; no console needed

### Requirements

- Python 3.9+
- Windows / macOS / Linux
- A Telegram account and your own `api_id` / `api_hash` (see below)

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/telegram-media-downloader.git
cd telegram-media-downloader
python -m pip install -r requirements.txt
```

### Getting api_id and api_hash (one time)

1. Go to https://my.telegram.org and log in with your phone number.
2. Open **API development tools**.
3. Fill in the form (*App title* and *Short name* are enough) and click **Create application**.
4. Copy your `api_id` and `api_hash`. **Never publish your `api_hash` — it is a secret.**

### Running

```bash
python telegram_downloader_gui.py
```

On the first run the app will ask for the Telegram login code and your 2FA password (if enabled) via dialog windows. The session is saved, so you won't need to log in again.

### What to fill in

| Field | What to enter |
|---|---|
| `api_id` / `api_hash` | App credentials from my.telegram.org (entered once, stored in `config_gui.json`) |
| Phone | Number in international format, e.g. `+79991234567` |
| Channels | `@username`, a `https://t.me/...` link, or an ID. Use "Add to list" to build a queue |
| Output folder | Where to save files (created automatically) |
| From / To date | Period in `YYYY-MM-DD` format. Empty = full history |
| Min / Max MB | File size limits. Empty = no limits |
| File types | Checkboxes: what to download. Each type goes to its own subfolder |
| Only new | Incremental sync: download only new messages |
| Export text | Write `messages.jsonl` and `messages.csv` (full text backup) |
| Collect links | Extract all links from messages into `links.csv` and `links_unique.txt` (works independently of file filters) |
| Skip duplicates | Deduplication by file ID and SHA-256 |
| Proxy | SOCKS5: host, port, login/password. MTProto: host, port, secret |

### Output structure

```
telegram_downloads/
└── Channel_name/
    ├── Photo/  Video/  Voice_Audio/  Documents/
    ├── Archives/  GIF_Stickers/  Other/
    ├── messages.jsonl      # message texts (JSON Lines)
    ├── messages.csv        # same data as CSV (opens in Excel)
    ├── links.csv           # all links: text, buttons, previews
    └── links_unique.txt    # unique links, one per line
```

### Building a Windows .exe

```bash
python -m pip install pyinstaller
pyinstaller --onefile --noconsole --name TelegramDownloader telegram_downloader_gui.py
```

The ready `TelegramDownloader.exe` will appear in `dist/`. No Python installation is required to run it.

### Files created at runtime (do NOT publish!)

| File | Purpose |
|---|---|
| `config_gui.json` | Your settings, including `api_hash` and phone number |
| `session_*.session` | Authorized session — grants access to your account! |
| `downloader_state.json` | Incremental sync progress |
| `dedup_index.json` | Hash database of downloaded files |

All of them are already listed in `.gitignore`. **Never commit them.**

### FAQ

**FloodWait in the log** — Telegram is asking for a pause; the app waits and continues automatically. This is normal.

**"Channel not found"** — for a private channel your account must be a member; use its ID or an invite link.

**SOCKS5 not working** — make sure the `python-socks` package is installed (it is in `requirements.txt`).

### Disclaimer

This app is intended for personal backup of channels you have legitimate access to. Using the Telegram API is governed by [Telegram's Terms of Service](https://core.telegram.org/api/terms): spam, flooding and abuse lead to account bans. The author is not responsible for how you use this software.

### License

[MIT](LICENSE)
