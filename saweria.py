import cloudscraper
from bs4 import BeautifulSoup
import json

# Constants
BACKEND = 'https://backend.saweria.co'
FRONTEND = 'https://saweria.co'

# Buat scraper dengan bypass Cloudflare
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'android',
        'mobile': True
    }
)

def insert_plus_in_email(email, insert_str):
    return email.replace("@", f"+{insert_str}@", 1)

def paid_status(transaction_id: str) -> bool:
    """
    Cek status transaksi apakah sudah dibayar.

    Args:
        transaction_id (str): ID transaksi dari create_payment

    Returns:
        bool: True jika sudah dibayar, False jika belum
    """
    resp = scraper.get(f"{BACKEND}/donations/qris/{transaction_id}")
    if not resp.ok:
        raise ValueError("Gagal mengecek status transaksi!")
    
    data = resp.json().get("data", {})
    if data.get("qr_string", "") != "":
        return False  # Masih ada QR berarti belum dibayar
    return True       # QR kosong artinya sudah dibayar

def create_payment_string(username: str, amount: int, sender: str, email: str, message: str) -> dict:
    """
    Membuat transaksi QRIS Saweria.

    Args:
        username (str): Username akun saweria
        amount (int): Jumlah donasi minimal 10000
        sender (str): Nama pengirim
        email (str): Email pengirim
        message (str): Pesan

    Returns:
        dict: Detail transaksi
    """
    if amount < 10000:
        raise ValueError("Minimal donasi adalah 10000 IDR")

    # Ambil user_id dari halaman depan
    print(f"Mengakses profil: {FRONTEND}/{username}")
    response = scraper.get(f"{FRONTEND}/{username}")
    soup = BeautifulSoup(response.text, "html.parser")
    
    next_data = soup.find(id="__NEXT_DATA__")
    if not next_data:
        raise ValueError("Akun saweria tidak ditemukan!")

    parsed_data = json.loads(next_data.text)
    user_id = parsed_data.get("props", {}).get("pageProps", {}).get("data", {}).get("id")
    if not user_id:
        raise ValueError("Gagal mengambil user ID saweria!")

    payload = {
        "agree": True,
        "notUnderage": True,
        "message": message,
        "amount": amount,
        "payment_type": "qris",
        "vote": "",
        "currency": "IDR",
        "customer_info": {
            "first_name": sender,
            "email": insert_plus_in_email(email, sender),
            "phone": ""
        }
    }

    resp = scraper.post(f"{BACKEND}/donations/{user_id}", json=payload)
    if not resp.ok:
        raise ValueError("Gagal membuat transaksi QR")

    return resp.json()["data"]

def create_payment_qr(username: str, amount: int, sender: str, email: str, message: str) -> tuple:
    """
    Menghasilkan string QR dan ID transaksi.

    Args:
        username (str): Username akun Saweria
        amount (int): Jumlah donasi
        sender (str): Nama pengirim
        email (str): Email pengirim
        message (str): Pesan ke kreator

    Returns:
        tuple: (qr_string, transaction_id)
    """
    details = create_payment_string(username, amount, sender, email, message)
    return details["qr_string"], details["id"]
