# ImapStake

Bot Telegram untuk monitoring email IMAP dan mengirimkan notifikasi otomatis untuk email terkait Stake 

## Fitur Utama

- **IMAP Monitoring**: Memantau email masuk dari berbagai akun Gmail secara otomatis
- **Telegram Integration**: Mengirimkan notifikasi real-time ke Telegram chat
- **Code & Link Extraction**: Ekstrak kode verifikasi dan link dari email

## Persyaratan

- Python 3.7+ instal dari F-Droid
- Bot Telegram (Token dari @BotFather)
- Akun Gmail dengan App Password
- Koneksi internet stabil

## Instalasi

### 1. Clone Repository

```bash
git clone https://github.com/msidqi07/imapstake.git
cd imapstake
```

### 2. Install Dependencies

```bash
pip install requests colorama imapclient python-dateutil pytz pyfiglet beautifulsoup4
```

### 3. Konfigurasi Bot

Edit file `bot.py` dan ubah konfigurasi berikut:

```python
# Telegram Bot Configuration
BOT_TOKEN = "your_telegram_bot_token_here"  # GANTI dengan BOT TOKEN Anda



### 4. Setup Gmail App Password

1. Aktifkan 2-Factor Authentication di akun Gmail
2. Buat App Password untuk aplikasi ini
3. Gunakan App Password (bukan password utama) saat menambah akun

### 5. Dapatkan Chat ID Telegram

1. Start bot dengan mengirim `/start`
## Penggunaan

### Menjalankan Bot

```bash
python bot.py
```

### Perintah Bot Telegram

- **📧 Cek Email Stake (Semua Akun)**: Cek semua akun email 
- **➕ Tambah Akun**: Tambah akun Gmail baru
- **📋 Lihat Akun Saya**: Lihat daftar akun terdaftar 



## Konfigurasi Lanjutan

### Valid Senders

Bot memfilter email berdasarkan pengirim yang valid. Daftar pengirim valid sudah dikonfigurasi:

```python
ALLOWED_SENDERS = [
    "noreply@stake.krd", "noreply@stake.mba", "noreply@stake.bz",
    "noreply@stake.pet", "noreply@stake.bet", "noreply@stake.com",
    "noreplymail.stake.com", "stake.com", "stake.pet",
    "mail.stake.com", "alerts.stake.com", "stake.krd",
    "noreply@stake.ac", "noreply@joinmarriottbonvoy.com"
]
```



## Troubleshooting

### Error Login IMAP

1. Pastikan App Password sudah benar
2. Cek koneksi internet
3. Verifikasi pengaturan IMAP Gmail sudah aktif

### Bot Tidak Merespon

1. Periksa token bot Telegram
2. Pastikan bot sudah di-start dengan `/start`
3. Cek log error di terminal



## Keamanan

- Jangan share token bot Telegram
- Gunakan App Password, bukan password utama Gmail


---

**⚠️ Disclaimer**: Bot ini dibuat untuk tujuan edukasi dan monitoring email pribadi. Pastikan mematuhi terms of service dari layanan email dan platform yang digunakan.

