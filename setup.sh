#!/usr/bin/env bash
# ─────────────────────────────────────────────
#  Stake Keno Bot — Setup Script
#  Jalankan sekali sebelum menjalankan bot:
#    bash setup.sh
# ─────────────────────────────────────────────

set -e

echo ""
echo "========================================"
echo "  Stake Keno Bot — Setup"
echo "========================================"
echo ""

# ── 1. Buat file .env ────────────────────────
ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
    echo "[INFO] File .env sudah ada."
    read -rp "Timpa dengan konfigurasi baru? (y/N): " overwrite
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
        echo "[INFO] Setup .env dilewati."
    else
        create_env=true
    fi
else
    create_env=true
fi

if [ "${create_env:-false}" = "true" ]; then
    echo ""
    echo "--- Konfigurasi API ---"
    read -rp "Masukkan Stake API Key (x-access-token): " api_key
    if [ -z "$api_key" ]; then
        echo "[ERROR] API Key tidak boleh kosong." >&2
        exit 1
    fi

    # Tulis .env dengan printf agar karakter spesial ($, !, \) di API key
    # tidak di-expand oleh shell — heredoc tanpa quote tidak aman untuk token
    printf '# Stake Keno Bot — Environment Variables\n' > "$ENV_FILE"
    printf '# Jangan di-share atau di-commit ke repository!\n\n' >> "$ENV_FILE"
    printf 'STAKE_API_KEY=%s\n' "$api_key" >> "$ENV_FILE"

    echo ""
    echo "[OK] File .env berhasil dibuat."
fi

# ── 2. Install dependencies ──────────────────
echo ""
echo "--- Install Dependencies ---"

if command -v pip3 &>/dev/null; then
    PIP=pip3
elif command -v pip &>/dev/null; then
    PIP=pip
else
    echo "[ERROR] pip tidak ditemukan. Pastikan Python & pip sudah terinstall." >&2
    exit 1
fi

$PIP install -r requirements.txt --quiet
echo "[OK] Dependencies berhasil diinstall."

# ── 3. Selesai ───────────────────────────────
echo ""
echo "========================================"
echo "  Setup selesai!"
echo ""
echo "  Cara menjalankan bot dengan screen:"
echo "    screen -S keno-bot"
echo "    python3 bot.py"
echo "    (Ctrl+A, D untuk detach)"
echo "========================================"
echo ""
