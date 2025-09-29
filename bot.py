import datetime
import math
import random
import time
import json
import urllib.parse
from threading import Thread, Lock
from colorama import Fore, Style, init
import pytz
import email
import re
import sys
import os
import csv
import requests
import pyfiglet
from imapclient import IMAPClient
from email.header import decode_header
import email.utils
from bs4 import BeautifulSoup
import html
import traceback
import hashlib
from collections import defaultdict

# Inisialisasi colorama
init(autoreset=True)

# --- Konfigurasi ---
BOT_TOKEN = "your_telegram_bot_token_here"
IMAP_SERVER = "imap.gmail.com"
USER_DATA_DIR = "user_data"
DAYS_BACK = 10
BATCH_SIZE = 10
# Konstanta baru untuk paginasi
ACCOUNTS_PER_PAGE = 50 
ALLOWED_SENDERS = [
    "noreply@stake.krd", "noreply@stake.mba", "noreply@stake.bz",
    "noreply@stake.pet", "noreply@stake.bet", "noreply@stake.com",
    "noreply@mail.stake.com", "@stake.com", "@stake.pet",
    "@mail.stake.com", "@alerts.stake.com", "@stake.krd",
    "noreply@stake.ac", "noreply@joinmarriottbonvoy.com"
]
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Zona waktu untuk logging
wib = pytz.timezone('Asia/Jakarta')

# Lock untuk operasi print agar output tidak campur aduk antar thread
print_lock = Lock()

# Global variables untuk bot
last_telegram_update_id = 0
user_states = defaultdict(lambda: 'IDLE')
# Global variables untuk melacak hasil pemrosesan (per user)
user_processing_status = {}

# --- Fungsi Utilitas & Logging ---
def get_timestamp():
    """Mengembalikan timestamp dalam format WIB."""
    return datetime.datetime.now(wib).strftime('%D %T')

def custom_log(message, prefix=' ┊ ', color=Fore.WHITE):
    """Fungsi logging kustom."""
    with print_lock:
        print(f"{color}{prefix}{message}{Style.RESET_ALL}")

log = custom_log

def display_banner():
    """Menampilkan banner bot."""
    os.system('cls' if os.name == 'nt' else 'clear')
    banner_text = "MULTI-USER IMAP BOT"
    banner = pyfiglet.figlet_format(banner_text, font='slant')
    lines = banner.split('\n')
    term_width = os.get_terminal_size().columns
    for line in lines:
        print(Fore.CYAN + line.center(term_width) + Style.RESET_ALL)
    print(Fore.BLUE + "".center(term_width) + Style.RESET_ALL)
    log(f"{Fore.CYAN + Style.BRIGHT}-{Style.RESET_ALL}"*75, prefix='')

def is_valid_sender(raw_sender_address):
    """Memeriksa apakah pengirim email valid berdasarkan daftar ALLOWED_SENDERS."""
    _, addr = email.utils.parseaddr(raw_sender_address)
    return any(domain.lower() in addr.lower() for domain in ALLOWED_SENDERS)

# --- Fungsi Manajemen Akun Multi-User ---
def get_user_account_filepath(user_id):
    """Mengembalikan path lengkap ke file accounts.csv untuk user_id tertentu."""
    user_dir = os.path.join(USER_DATA_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, "accounts.csv")

def load_user_accounts(user_id):
    """Memuat daftar akun dari file CSV user tertentu."""
    filepath = get_user_account_filepath(user_id)
    res = []
    try:
        with open(filepath, newline='', encoding='utf-8') as f:
            csv_reader = csv.reader(f)
            for row in csv_reader:
                if len(row) >= 2:
                    email_addr = row[0].strip()
                    app_password = row[1].strip()
                    if email_addr and app_password:
                        res.append({"email": email_addr, "app_password": app_password})
    except FileNotFoundError:
        log(f"File akun tidak ditemukan untuk user {user_id}. Akan dibuat baru saat penambahan.", prefix=' ┊ ! ', color=Fore.YELLOW)
    except Exception as e:
        log(f"Gagal baca akun user {user_id}: {e}", prefix=' ┊ ✗ ', color=Fore.RED)
    return res

def save_account_to_file(user_id, email_addr, app_password):
    """Menyimpan (menambahkan) satu akun ke file CSV user."""
    filepath = get_user_account_filepath(user_id)
    try:
        # Periksa apakah akun sudah ada
        current_accounts = load_user_accounts(user_id)
        if any(acc['email'] == email_addr for acc in current_accounts):
            return False, "Akun ini sudah terdaftar."

        with open(filepath, 'a', newline='', encoding='utf-8') as f:
            csv_writer = csv.writer(f)
            csv_writer.writerow([email_addr, app_password])
        return True, "Akun berhasil ditambahkan."
    except Exception as e:
        log(f"Gagal simpan akun user {user_id}: {e}", prefix=' ┊ ✗ ', color=Fore.RED)
        return False, f"Terjadi kesalahan saat menyimpan: {e}"

# --- Fungsi Utilitas IMAP ---

def extract_code_or_link(body_text):
    """Mengekstrak kode OTP atau link dari body email."""
    codes = re.findall(r'\b(?:\d[\s\-]?){6,}\b', body_text)
    for code_found in codes:
        pattern = re.compile(r'\b(?:unique|unik)\b.{0,50}' + re.escape(code_found), re.IGNORECASE | re.DOTALL)
        if pattern.search(body_text):
            return re.sub(r'\D', '', code_found), None
    links = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', body_text, re.IGNORECASE)
    if links:
        filtered_links = []
        for l in links:
            if len(l) > 10 and not l.startswith('#') and not l.strip().endswith('.'):
                filtered_links.append(l)
        if filtered_links:
            for link_found in filtered_links:
                if any(keyword in link_found.lower() for keyword in ['verify', 'confirm', 'reset', 'login']):
                    return None, link_found
            return None, filtered_links[0]
    return None, None

def extract_subject_and_from(envelope):
    """Mengekstrak subjek dan alamat pengirim dari objek envelope IMAP."""
    sub_raw = envelope.subject or b"(No Subject)"
    try:
        decoded_headers = decode_header(sub_raw.decode('utf-8', errors='ignore'))
        sub = "".join([
            part.decode(cs or 'utf-8', errors='ignore') if isinstance(part, bytes) else part
            for part, cs in decoded_headers
        ])
    except Exception:
        sub = sub_raw.decode('utf-8', errors='ignore')

    frm = envelope.from_[0]
    mailbox = frm.mailbox.decode(errors='ignore') if frm.mailbox else ''
    host = frm.host.decode(errors='ignore') if frm.host else ''
    frm_addr = f"{mailbox}@{host}" if mailbox and host else (mailbox or host or "Unknown Sender")
    return sub, frm_addr

def extract_email_body_content(msg_bytes):
    """Mengekstrak konten HTML dan plain-text dari body email."""
    msg = email.message_from_bytes(msg_bytes)
    html_content = ""
    plain_content = ""
    for part in msg.walk():
        ctype = part.get_content_type()
        cdisp = str(part.get('Content-Disposition'))
        if 'attachment' not in cdisp:
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    decoded_payload = payload.decode(charset, errors='ignore')
                    if ctype == 'text/html' and not html_content:
                        html_content = decoded_payload
                    elif ctype == 'text/plain' and not plain_content:
                        plain_content = decoded_payload
            except Exception as e:
                pass
    return html_content, plain_content

def get_original_email_body_html(msg_bytes):
    """Mengekstrak body HTML asli dari email."""
    msg = email.message_from_bytes(msg_bytes)
    for part in msg.walk():
        ctype = part.get_content_type()
        cdisp = str(part.get('Content-Disposition'))
        if 'attachment' not in cdisp and ctype == 'text/html':
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    return payload.decode(charset, errors='ignore')
            except Exception as e:
                pass
    return ""

def extract_and_format_email_body(html_content, plain_content):
    """Mengekstrak dan memformat body email untuk Telegram."""
    extracted_links_list = []
    cleaned_body_text = ""
    if html_content:
        soup = BeautifulSoup(html_content, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            href = a_tag.get('href')
            text = a_tag.get_text(strip=True)
            if href and text:
                extracted_links_list.append(f"<a href='{html.escape(href)}'>{html.escape(text)}</a>")
            a_tag.replace_with(text or '')
        for script_or_style in soup(['script', 'style']):
            script_or_style.decompose()
        for br in soup.find_all('br'):
            br.replace_with('\n')
        for tag_name in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'ul', 'ol', 'blockquote']:
            for tag in soup.find_all(tag_name):
                tag.insert_after('\n\n')
        cleaned_body_text = soup.get_text(separator='\n', strip=False)
    elif plain_content:
        cleaned_body_text = plain_content
        
    cleaned_body_text = re.sub(r'[\u200B-\u200F\uFEFF\u00A0\u00ad]+', '', cleaned_body_text)
    cleaned_body_text = '\n'.join([line.strip() for line in cleaned_body_text.splitlines()])
    cleaned_body_text = re.sub(r'\n{3,}', '\n\n', cleaned_body_text)
    cleaned_body_text = re.sub(r' {2,}', ' ', cleaned_body_text)
    cleaned_body_text = cleaned_body_text.strip()
    if not cleaned_body_text:
        cleaned_body_text = "Isi email tidak dapat dibaca atau kosong."
    return cleaned_body_text, extracted_links_list

def move_email_to_trash(client, email_id):
    """Memindahkan email ke folder sampah."""
    try:
        if not hasattr(client, '_cached_folders'):
            client._cached_folders = client.list_folders()
        trash_folder_name = None
        for flags, delimiter, folder_name_raw in client._cached_folders:
            folder_name = folder_name_raw.decode('utf-8', errors='ignore') if isinstance(folder_name_raw, bytes) else folder_name_raw
            if b'\\Trash' in flags:
                trash_folder_name = folder_name
                break
        if not trash_folder_name:
            common_trash_names = ['[Gmail]/Trash', 'Trash', '[Gmail]/Sampah', 'Sampah', 'Deleted Items', 'Bin']
            for name_candidate in common_trash_names:
                for flags, delimiter, folder_name_raw in client._cached_folders:
                    folder_name = folder_name_raw.decode('utf-8', errors='ignore') if isinstance(folder_name_raw, bytes) else folder_name_raw
                    if folder_name.lower() == name_candidate.lower():
                        trash_folder_name = folder_name
                        break
                if trash_folder_name:
                    break
            if not trash_folder_name:
                return False
        client.copy(email_id, trash_folder_name)
        client.delete_messages(email_id)
        client.expunge()
        return True
    except Exception as e:
        return False

# --- Fungsi Telegram API ---
def send_telegram_message(chat_id, message, inline_keyboard=None):
    """Mengirim pesan ke Telegram dengan dukungan inline keyboard."""
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if inline_keyboard:
        payload["reply_markup"] = json.dumps({"inline_keyboard": inline_keyboard})
    try:
        response = requests.post(url, json=payload, timeout=7)
        if response.status_code == 200:
            return True, None, response.json().get('result', {}).get('message_id')
        else:
            return False, f"Status: {response.status_code}, Respon: {response.text}", None
    except requests.exceptions.RequestException as e:
        return False, f"Error koneksi: {e}", None
    except Exception as e:
        return False, f"Error tak terduga: {e}", None

def get_updates(offset=None, timeout=30):
    """Mendapatkan pembaruan dari Telegram API."""
    url = f"{TELEGRAM_API_URL}/getUpdates"
    params = {'timeout': timeout, 'offset': offset}
    try:
        response = requests.get(url, params=params, timeout=timeout + 5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        # Jika timeout, ini normal saat polling panjang
        if "Read timeout" not in str(e):
             log(f"Error saat mengambil updates dari Telegram: {e}", prefix=' ┊ ✗ ', color=Fore.RED)
        return None

def kirim_notif_telegram(chat_id, subject, frm, to, code=None, link=None, date=None,
                         original_html_body=None, full_body_text=None, extracted_links_telegram=None, is_sender_valid=False):
    """Mengirim notifikasi ke Telegram dengan detail email dan file lampiran ke CHAT_ID spesifik."""
    if extracted_links_telegram is None:
        extracted_links_telegram = []

    status_label = "✅ VALID STAKE" if is_sender_valid else "❌ TIDAK VALID"
    
    pesan_parts = []
    pesan_parts.append(f"<b>--- {status_label} ---</b>\n\n")
    if date:
        waktu_str = date.strftime('%A, %d %B %Y %H:%M:%S %Z')
        pesan_parts.append(f"<b>🕒 Waktu:</b> {waktu_str}\n")
    pesan_parts.append(f"<b>📭 Dari:</b> {html.escape(frm)}\n")
    pesan_parts.append(f"<b>📧 Untuk:</b> {html.escape(to)}\n")
    if subject:
        pesan_parts.append(f"<b>📝 Subjek:</b> {html.escape(subject)}\n")
    
    if code:
        pesan_parts.append(f"\n🔢 <b>Kode OTP:</b> <code>{html.escape(code)}</code>\n")
    
    if link:
        pesan_parts.append(f"\n🔗 <b>Link Aksi:</b> <a href='{html.escape(link)}'>KLIK DI SINI</a>\n")

    pesan = "".join(pesan_parts)
    url = f"{TELEGRAM_API_URL}/sendDocument"
    file_content = original_html_body or full_body_text
    file_extension = "html" if original_html_body else "txt"
    
    if not file_content:
        log(f"Error: Konten email kosong. Hanya mengirim pesan teks.", prefix=' ┊ ✗ ', color=Fore.RED)
        return send_telegram_message(chat_id, pesan + "\n\n<i>(Konten email tidak dapat dilampirkan)</i>")

    # Membuat nama file unik
    cleaned_subject = re.sub(r'[^\w\s.-]', '', subject).strip() or "Email_Content"
    cleaned_subject = re.sub(r'\s+', '_', cleaned_subject)[:40]
    unique_id_seed = f"{time.time()}_{random.randint(0, 999999)}"
    short_unique_id = hashlib.md5(unique_id_seed.encode('utf-8')).hexdigest()[:8]
    file_name = f"{cleaned_subject}_{short_unique_id}.{file_extension}".replace('__', '_')

    try:
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(file_content)
        
        files = {'document': (file_name, open(file_name, 'rb'), 'text/html' if file_extension == 'html' else 'text/plain')}
        data = {
            "chat_id": chat_id,
            "caption": pesan,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        
        r = requests.post(url, data=data, files=files, timeout=30)
        if r.status_code == 200:
            log(f"Notifikasi Telegram dikirim ke user {chat_id} (dengan file .{file_extension}).", prefix=' ┊ ✓ ', color=Fore.GREEN)
            return True
        else:
            log(f"Gagal kirim Telegram ke user {chat_id}: {r.status_code} - {r.text}", prefix=' ┊ ✗ ', color=Fore.RED)
            send_telegram_message(chat_id, pesan + "\n\n<i>(Gagal melampirkan file konten)</i>")
            return False
    except requests.exceptions.RequestException as e:
        log(f"Error koneksi saat kirim Telegram ke user {chat_id}: {e}", prefix=' ┊ ✗ ', color=Fore.RED)
        return False
    except Exception as e:
        log(f"Error tak terduga saat kirim Telegram ke user {chat_id}: {e}", prefix=' ┊ ✗ ', color=Fore.RED)
        return False
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)

# --- Fungsi Proses Inti IMAP ---

def login(email_addr, pwd, chat_id):
    """Mencoba login ke server IMAP dengan 3 kali percobaan ulang."""
    log(f"[{chat_id}] Mencoba login ke {email_addr}...", prefix=' ┊ → ', color=Fore.CYAN)
    
    for attempt in range(3):
        c = None
        try:
            c = IMAPClient(IMAP_SERVER, ssl=True, timeout=15)
            c.login(email_addr, pwd)
            c.select_folder("INBOX")
            log(f"[{chat_id}] Berhasil login ke {email_addr}", prefix=' ┊ ✓ ', color=Fore.GREEN)
            return c
        except IMAPClient.Error as e:
            log(f"[{chat_id}] Gagal login ke {email_addr} (Percobaan ke-{attempt + 1}): {e}", prefix=' ┊ ✗ ', color=Fore.RED)
            if attempt < 2:
                time.sleep(5)
            else:
                send_telegram_message(chat_id, f"❌ **Gagal Login!** Akun: <code>{html.escape(email_addr)}</code>. Cek App Password atau Pengaturan IMAP.")
                return None
        except Exception as e:
            log(f"[{chat_id}] Error tak terduga saat login ke {email_addr} (Percobaan ke-{attempt + 1}): {e}", prefix=' ┊ ✗ ', color=Fore.RED)
            if attempt < 2:
                time.sleep(5)
            else:
                return None
    return None

def proses_akun(acc, chat_id):
    """Fungsi untuk memproses satu akun email."""
    ema, pwd = acc["email"], acc["app_password"]
    
    # Inisialisasi status jika belum ada (hanya untuk logik proses akun)
    current_status = user_processing_status.setdefault(chat_id, {'processed': 0, 'successful': 0, 'failed': 0, 'failed_emails': []})
    
    log(f"[{chat_id}] Memproses akun: {ema}", prefix=' ┊ → ', color=Fore.WHITE)
    c = None
    try:
        c = login(ema, pwd, chat_id)
        if not c:
            log(f"  ↳ Gagal login. Melewati akun ini.", prefix=' ┊ ! ', color=Fore.YELLOW)
            current_status['failed'] += 1
            if ema not in current_status['failed_emails']:
                current_status['failed_emails'].append(ema)
            return
        
        since_date = (datetime.date.today() - datetime.timedelta(days=DAYS_BACK)).strftime("%d-%b-%Y")
        mids = c.search(['UNSEEN', 'SINCE', since_date])
        
        if mids:
            log(f"  ↳ Ditemukan {len(mids)} email baru.", prefix=' ┊ ✓ ', color=Fore.GREEN)
            fetch_data = c.fetch(mids, ['ENVELOPE', 'BODY[]'])
            for m_id, data in fetch_data.items():
                env = data[b'ENVELOPE']
                full_message_bytes = data[b'BODY[]']
                
                original_html_body = get_original_email_body_html(full_message_bytes)
                email_body_html_parsed, email_body_plain = extract_email_body_content(full_message_bytes)
                temp_body_for_extraction = email_body_html_parsed if email_body_html_parsed else email_body_plain
                code, link = extract_code_or_link(temp_body_for_extraction)
                sub, frm = extract_subject_and_from(env)
                email_date = env.date.astimezone(wib) if env.date else datetime.datetime.now(wib)
                full_body_text_to_send, extracted_links_for_telegram = extract_and_format_email_body(email_body_html_parsed, email_body_plain)
                sender_is_valid = is_valid_sender(frm)

                log(f"    • Dari: {frm} | Subjek: {sub}", prefix=' ┊ │ ', color=Fore.WHITE)
                
                kirim_notif_telegram(
                    chat_id=chat_id,
                    subject=sub,
                    frm=frm,
                    to=ema,
                    code=code,
                    link=link,
                    date=email_date,
                    original_html_body=original_html_body,
                    full_body_text=full_body_text_to_send,
                    extracted_links_telegram=extracted_links_for_telegram,
                    is_sender_valid=sender_is_valid
                )
                
                c.add_flags([m_id], ['\\Seen'])
                if not sender_is_valid:
                    move_email_to_trash(c, m_id)
            current_status['successful'] += 1
        else:
            log(f"  ↳ Tidak ada email baru ditemukan.", prefix=' ┊ ! ', color=Fore.YELLOW)
            current_status['successful'] += 1
    except Exception as e:
        log(f"  ↳ Error tak terduga saat memproses {ema}: {e}", prefix=' ┊ ✗ ', color=Fore.RED)
        traceback.print_exc()
        current_status['failed'] += 1
        if ema not in current_status['failed_emails']:
            current_status['failed_emails'].append(ema)
    finally:
        if c:
            try:
                c.logout()
                log(f"  ↳ Logout berhasil untuk {ema}.", prefix=' ┊ ✓ ', color=Fore.GREEN)
            except Exception as e:
                log(f"  ↳ Gagal logout dari {ema}: {e}", prefix=' ┊ ✗ ', color=Fore.RED)
        current_status['processed'] += 1
        time.sleep(random.uniform(1, 3))

def send_user_summary_telegram(chat_id):
    """Mengirim ringkasan hasil pemrosesan ke Telegram untuk user spesifik."""
    status = user_processing_status.get(chat_id, {'processed': 0, 'successful': 0, 'failed': 0, 'failed_emails': []})
    
    processed = status['processed']
    successful = status['successful']
    failed = status['failed']
    failed_emails = status['failed_emails']

    summary_message = (
        f"📊 <b>Ringkasan Proses Akun IMAP Anda</b>\n\n"
        f"Total Akun Diproses: <b>{processed}</b>\n"
        f"Akun Berhasil Cek: <b>{successful}</b> ✅\n"
        f"Akun Gagal Login: <b>{failed}</b> ❌\n\n"
    )
    
    if failed > 0:
        summary_message += "<b>Daftar Akun Gagal Login:</b>\n"
        for i, email_failed in enumerate(failed_emails):
            if i < 5:
                summary_message += f"• <code>{html.escape(email_failed)}</code>\n"
            else:
                summary_message += f"• ...dan {failed - i} lainnya.\n"
                break
        summary_message += "\n"
        
    summary_message += f"<i>Selesai pada: {datetime.datetime.now(wib).strftime('%d %B %Y %H:%M:%S WIB')}</i>"
    
    send_telegram_message(chat_id, summary_message)

def start_email_check(chat_id, user_id):
    """Fungsi utama untuk menjalankan proses IMAP untuk SEMUA akun user."""
    log(f"[{chat_id}] Memulai proses cek semua email...", prefix=' ┊ → ', color=Fore.CYAN)
    
    ak = load_user_accounts(user_id)
    if not ak:
        send_telegram_message(chat_id, "⚠️ Anda belum memiliki akun terdaftar. Silakan tambahkan akun Anda dengan tombol <b>Tambah Akun</b>.")
        user_states[chat_id] = 'IDLE'
        send_main_menu(chat_id)
        return

    # Reset status sebelum memulai
    user_processing_status[chat_id] = {'processed': 0, 'successful': 0, 'failed': 0, 'failed_emails': []}

    send_telegram_message(chat_id, f"🚀 **Memulai pengecekan {len(ak)} akun**")
    
    total_batches = math.ceil(len(ak) / BATCH_SIZE)
    for i in range(total_batches):
        start, end = i * BATCH_SIZE, (i + 1) * BATCH_SIZE
        # Memproses batch
        for acc in ak[start:end]:
            proses_akun(acc, chat_id)
            # Check for termination signal
            if not user_states[chat_id].startswith('IMAP_RUNNING'):
                 log(f"[{chat_id}] Proses dibatalkan oleh user/dihentikan.", prefix=' ┊ ✗ ', color=Fore.RED)
                 return
    
    log(f"[{chat_id}] Semua akun selesai diproses. Mengirim ringkasan.", prefix=' ┊ ✓ ', color=Fore.GREEN)
    send_user_summary_telegram(chat_id)
    user_states[chat_id] = 'IDLE'
    send_main_menu(chat_id, "✅ Proses pengecekan selesai.")

def start_specific_email_check(chat_id, user_id, target_email):
    """Fungsi untuk menjalankan proses IMAP untuk email TERTENTU dari user."""
    log(f"[{chat_id}] Memulai proses cek email spesifik: {target_email}", prefix=' ┊ → ', color=Fore.CYAN)
    
    ak = load_user_accounts(user_id)
    target_account = next((acc for acc in ak if acc['email'].lower() == target_email.lower()), None)

    if not target_account:
        send_telegram_message(chat_id, f"❌ Akun <code>{html.escape(target_email)}</code> tidak ditemukan di daftar akun Anda. Pastikan email sudah ditambahkan.")
        user_states[chat_id] = 'IDLE'
        send_main_menu(chat_id)
        return

    # Reset status sebelum memulai
    user_processing_status[chat_id] = {'processed': 0, 'successful': 0, 'failed': 0, 'failed_emails': []}

    send_telegram_message(chat_id, f"🚀 **Memulai pengecekan email spesifik:** <code>{html.escape(target_email)}</code>")
    
    # Proses hanya satu akun
    proses_akun(target_account, chat_id)
    
    log(f"[{chat_id}] Pengecekan email spesifik selesai. Mengirim ringkasan.", prefix=' ┊ ✓ ', color=Fore.GREEN)
    send_user_summary_telegram(chat_id)
    user_states[chat_id] = 'IDLE'
    send_main_menu(chat_id, "✅ Proses pengecekan spesifik selesai.")

def view_user_accounts_paged(chat_id, user_id, page=1):
    """Menampilkan daftar akun dengan paginasi."""
    accounts = load_user_accounts(user_id)
    total_accounts = len(accounts)
    
    if not accounts:
        msg = "⚠️ Anda belum memiliki akun terdaftar."
        send_telegram_message(chat_id, msg)
        return

    total_pages = math.ceil(total_accounts / ACCOUNTS_PER_PAGE)
    # Pastikan nomor halaman valid
    page = max(1, min(page, total_pages)) 
    
    start_index = (page - 1) * ACCOUNTS_PER_PAGE
    end_index = min(page * ACCOUNTS_PER_PAGE, total_accounts)
    
    accounts_to_display = accounts[start_index:end_index]

    msg = f"📋 **Daftar Akun Anda (Halaman {page}/{total_pages}):**\n\n"
    for i, acc in enumerate(accounts_to_display):
        global_index = start_index + i + 1
        msg += f"{global_index}. <code>{html.escape(acc['email'])}</code>\n"
    
    msg += "\n*Anda dapat menghapus akun dengan mengedit langsung file CSV di folder data Anda.*"

    # Membuat Keyboard Paginasi
    pagination_keyboard = []
    row = []
    
    if page > 1:
        row.append({"text": "⬅️ Sebelumnya", "callback_data": f"view_accounts:{page-1}"})
    
    if page < total_pages:
        row.append({"text": "Selanjutnya ➡️", "callback_data": f"view_accounts:{page+1}"})
        
    if row:
        pagination_keyboard.append(row)
    
    # Tambahkan tombol kembali ke Menu Utama
    pagination_keyboard.append([{"text": "🏠 Menu Utama", "callback_data": "main_menu"}])
        
    send_telegram_message(chat_id, msg, inline_keyboard=pagination_keyboard)


def send_main_menu(chat_id, message="Pilih aksi di bawah:"):
    """Mengirim menu utama dengan tombol interaktif."""
    # Callback untuk view_accounts kini menyertakan nomor halaman awal (1)
    keyboard = [
        [{"text": "📧 Cek Email Stake (Semua Akun)", "callback_data": "check_all_email"}],
        [{"text": "🔎 Cek Email Spesifik", "callback_data": "check_specific_email"}],
        [{"text": "➕ Tambah Akun", "callback_data": "add_account"}],
        [{"text": "📋 Lihat Akun Saya", "callback_data": "view_accounts:1"}] 
    ]
    send_telegram_message(chat_id, message, inline_keyboard=keyboard)

# --- Fungsi Penanganan Update Telegram ---
def handle_updates(updates):
    """Memproses semua update Telegram yang masuk."""
    global last_telegram_update_id
    if not updates or not updates.get('ok') or not updates.get('result'):
        return

    for update in updates['result']:
        last_telegram_update_id = update['update_id']
        
        if 'message' in update:
            message = update['message']
            chat_id = message['chat']['id']
            user_id = message['from']['id']
            text = message.get('text', '')
            
            log(f"[{chat_id}] Pesan diterima: {text}", prefix=' ┊ T ', color=Fore.LIGHTBLUE_EX)
            
            # --- Penanganan Perintah Dasar ---
            if text.startswith('/start'):
                send_main_menu(chat_id, f"Halo! Selamat datang. ID Anda: <code>{user_id}</code>")
                user_states[chat_id] = 'IDLE'
                continue
            
            # --- Penanganan State 'Tambah Akun' dan 'Cek Spesifik' ---
            current_state = user_states[chat_id]
            
            if current_state == 'AWAITING_EMAIL':
                user_data = text.strip()
                if '@' not in user_data:
                    send_telegram_message(chat_id, "❌ Format email tidak valid. Kirimkan alamat email IMAP Anda.")
                    continue
                user_states[chat_id] = 'AWAITING_PASSWORD'
                user_processing_status[chat_id] = {'email_temp': user_data}
                send_telegram_message(chat_id, f"✅ Email <code>{html.escape(user_data)}</code> tersimpan sementara.\n\nSekarang, kirimkan **App Password** Anda (bukan password akun utama).")
            
            elif current_state == 'AWAITING_PASSWORD':
                email_temp = user_processing_status.get(chat_id, {}).get('email_temp')
                app_password = text.strip()
                
                if not email_temp:
                    send_telegram_message(chat_id, "❌ Terjadi kesalahan. Silakan mulai ulang proses penambahan akun.")
                    user_states[chat_id] = 'IDLE'
                    send_main_menu(chat_id)
                    continue

                success, msg = save_account_to_file(user_id, email_temp, app_password)
                
                if success:
                    send_telegram_message(chat_id, f"🎉 **Sukses!** {msg}\nAkun: <code>{html.escape(email_temp)}</code> berhasil disimpan.")
                else:
                    send_telegram_message(chat_id, f"❌ **Gagal!** {msg}")
                    
                del user_processing_status[chat_id] # Bersihkan data sementara
                user_states[chat_id] = 'IDLE'
                send_main_menu(chat_id, "Silakan pilih aksi selanjutnya:")

            elif current_state == 'AWAITING_SPECIFIC_EMAIL':
                target_email = text.strip()
                if '@' not in target_email:
                    send_telegram_message(chat_id, "❌ Format email tidak valid. Kirimkan alamat email IMAP yang ingin dicek.")
                    return
                
                # Pindah ke state IMAP_RUNNING_SPECIFIC dan mulai thread
                user_states[chat_id] = f'IMAP_RUNNING_SPECIFIC:{user_id}'
                imap_thread = Thread(target=start_specific_email_check, args=(chat_id, user_id, target_email))
                imap_thread.daemon = True
                imap_thread.start()
                # Tidak perlu send_main_menu di sini karena akan dipanggil di akhir thread.
                
            else:
                # Pesan saat IDLE atau state lain
                if not current_state.startswith('IMAP_RUNNING'):
                    send_telegram_message(chat_id, "❓ Perintah tidak dikenal. Silakan gunakan tombol di bawah.")
                    send_main_menu(chat_id)

        elif 'callback_query' in update:
            query = update['callback_query']
            chat_id = query['message']['chat']['id']
            user_id = query['from']['id']
            data = query['data']
            
            log(f"[{chat_id}] Callback diterima: {data}", prefix=' ┊ B ', color=Fore.LIGHTGREEN_EX)
            
            # Pisahkan command dan data tambahan (misalnya, nomor halaman)
            parts = data.split(':')
            command = parts[0]
            
            # Balikkan status ke 'IDLE' jika user menekan tombol utama saat di tengah proses ADD/SPECIFIC
            if user_states[chat_id].startswith('AWAITING') and command not in ['cancel_add', 'main_menu']:
                user_states[chat_id] = 'IDLE'
                
            if command == "check_all_email":
                if user_states[chat_id] == 'IDLE':
                    user_states[chat_id] = f'IMAP_RUNNING_ALL:{user_id}'
                    imap_thread = Thread(target=start_email_check, args=(chat_id, user_id))
                    imap_thread.daemon = True
                    imap_thread.start()
                    requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": query['id'], "text": "Proses Cek SEMUA Email dimulai! Notifikasi akan dikirim di sini."})
                else:
                     requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": query['id'], "text": "Bot sedang sibuk memproses akun Anda. Tunggu proses selesai."})
                
            elif command == "check_specific_email":
                if user_states[chat_id] == 'IDLE':
                    user_states[chat_id] = 'AWAITING_SPECIFIC_EMAIL'
                    requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": query['id'], "text": "Mode Cek Email Spesifik aktif"})
                    send_telegram_message(chat_id, "Masukkan Email")
                else:
                    requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": query['id'], "text": "Bot sedang sibuk memproses akun Anda. Tunggu proses selesai."})


            elif command == "add_account":
                user_states[chat_id] = 'AWAITING_EMAIL'
                requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": query['id'], "text": "Mode Tambah Akun aktif"})
                send_telegram_message(chat_id, "Masukkan Email")
            
            elif command == "view_accounts":
                # Handle paginasi
                page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": query['id'], "text": f"Menampilkan akun halaman {page}."})
                # Memanggil fungsi tampilan berhalaman
                view_user_accounts_paged(chat_id, user_id, page)

            elif command == "main_menu":
                requests.post(f"{TELEGRAM_API_URL}/answerCallbackQuery", json={"callback_query_id": query['id'], "text": "Kembali ke menu utama."})
                send_main_menu(chat_id)


def run_telegram_bot():
    """Loop utama untuk bot Telegram."""
    global last_telegram_update_id
    display_banner()
    log(f"Bot Multi-User IMAP dimulai. URL API: {TELEGRAM_API_URL}", prefix=' ┊ → ', color=Fore.CYAN)
    
    while True:
        try:
            updates = get_updates(last_telegram_update_id + 1, timeout=30)
            if updates:
                handle_updates(updates)
            
        except requests.exceptions.ReadTimeout:
            pass # Normal read timeout
        except KeyboardInterrupt:
            log("Bot Dihentikan oleh pengguna.", prefix=' ┊ ', color=Fore.RED)
            break
        except Exception as e:
            log(f"Terjadi kesalahan fatal dalam loop bot: {e}", prefix=' ┊ ✗ ', color=Fore.RED)
            traceback.print_exc()
            time.sleep(5) 

# --- Main Execution Block ---
if __name__ == "__main__":
    run_telegram_bot()
