# Menggunakan base image Python resmi yang lebih ringan
FROM python:3.10-slim

# Menetapkan direktori kerja di dalam container
WORKDIR /app

# Menyalin requirements.txt dan menginstal dependensi
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Menyalin kode aplikasi ke dalam container
COPY . .

# Membuat direktori untuk QRIS dan uploads
RUN mkdir -p /app/qris_images
RUN mkdir -p /app/uploads

# Menjalankan aplikasi
# -u untuk memastikan output tidak dibuffer, penting untuk logging
# Menggunakan Gunicorn atau sejenisnya jika ingin Flask lebih stabil di produksi.
# Namun, untuk contoh ini, runbot_and_web.py sudah cukup.
CMD ["python", "bot.py"]
