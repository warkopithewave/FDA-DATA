"""Arsip harian broker summary dari CLI idx (fzn0x/idx, MIT) ke data/broker/TANGGAL.json.

Cara kerja:
1. Ambil daftar saham teraktif dari `idx market overview` (bagian "most traded"). Kalau gagal dibaca,
   pakai daftar cadangan dan tulis peringatan di log.
2. Ambil `idx broker` per kelompok 10 saham, dengan jeda dan percobaan ulang.
3. Simpan hasil mentah apa adanya. Parser untuk aplikasi dibuat setelah bentuk hasil aslinya terlihat.
4. Hapus arsip yang lebih tua dari 60 hari.

Mode uji (UJI=1): hanya 5 saham, untuk memastikan IPOT bisa diakses dari server GitHub.
Keluar dengan kode 1 bila tidak satu pun saham berhasil, supaya Actions berwarna merah.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

WIB = timezone(timedelta(hours=7))
JUMLAH = 100
KELOMPOK = 10
JEDA_DETIK = 2.0
PERCOBAAN = 3
SIMPAN_HARI = 60
UJI_SIMBOL = ["BBCA", "BBRI", "BMRI", "TLKM", "ASII"]
CADANGAN = ["BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII", "UNVR", "ICBP", "ADRO", "ANTM", "GOTO", "BUMI", "PTBA",
            "INDF", "KLBF", "MDKA", "AMMN", "BRPT", "CPIN", "MAPI"]
LOG = Path("log_broker")
KUNCI_KODE = ("symbol", "code", "ticker", "kode")


def jalankan(args, nama_log):
    """Panggil idx dan kembalikan (json atau None, pesan). Setiap percobaan dicatat di log_broker/."""
    pesan = ""
    for ke in range(1, PERCOBAAN + 1):
        try:
            p = subprocess.run(["idx", "-o", "json", *args], capture_output=True, text=True, timeout=180)
        except Exception as e:  # waktu habis, idx tidak ditemukan, dan sebagainya
            pesan = f"{type(e).__name__}: {e}"
        else:
            (LOG / f"{nama_log}_{ke}.txt").write_text(f"exit={p.returncode}\n--- stdout\n{p.stdout[:20000]}\n--- stderr\n{p.stderr[:5000]}\n")
            if p.returncode == 0:
                try:
                    return json.loads(p.stdout), ""
                except ValueError as e:
                    pesan = f"keluaran bukan JSON: {e}"
            else:
                pesan = f"exit {p.returncode}: {p.stderr.strip()[:300]}"
        time.sleep(JEDA_DETIK * ke)
    return None, pesan


def cari_kode(node, sedang_di_bagian_aktif=False, hasil=None):
    """Cari daftar kode saham di bagian JSON yang namanya mengandung 'most' dan 'trad' atau 'active'."""
    hasil = [] if hasil is None else hasil
    if isinstance(node, dict):
        for k, v in node.items():
            nama = str(k).lower()
            aktif = sedang_di_bagian_aktif or ("most" in nama and ("trad" in nama or "activ" in nama))
            cari_kode(v, aktif, hasil)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and sedang_di_bagian_aktif:
                for kk in KUNCI_KODE:
                    v = item.get(kk)
                    if isinstance(v, str) and 3 <= len(v) <= 5 and v.isalpha():
                        hasil.append(v.upper())
                        break
            else:
                cari_kode(item, sedang_di_bagian_aktif, hasil)
    return hasil


def daftar_simbol(uji):
    if uji:
        return UJI_SIMBOL, "mode uji"
    data, pesan = jalankan(["market", "overview", "--top", str(JUMLAH)], "overview")
    if data is not None:
        kode = list(dict.fromkeys(cari_kode(data)))
        if len(kode) >= 10:
            return kode[:JUMLAH], "market overview"
        print(f"PERINGATAN: hanya {len(kode)} kode terbaca dari market overview. Periksa log_broker/overview_1.txt dan "
              "sesuaikan fungsi cari_kode. Memakai daftar cadangan.")
    else:
        print(f"PERINGATAN: market overview gagal ({pesan}). Memakai daftar cadangan.")
    return CADANGAN, "daftar cadangan"


def main():
    LOG.mkdir(exist_ok=True)
    uji = os.environ.get("UJI") == "1"
    sekarang = datetime.now(WIB)
    simbol, sumber = daftar_simbol(uji)
    print(f"{len(simbol)} saham dari {sumber}")
    batch, gagal = [], []
    for i in range(0, len(simbol), KELOMPOK):
        grup = simbol[i:i + KELOMPOK]
        data, pesan = jalankan(["broker", *grup], f"broker_{i // KELOMPOK + 1}")
        if data is None:
            gagal.append({"simbol": grup, "pesan": pesan})
            print(f"GAGAL {grup}: {pesan}")
        else:
            batch.append({"simbol": grup, "hasil": data})
            print(f"ok {grup}")
        time.sleep(JEDA_DETIK)
    if not batch:
        print("Tidak ada saham yang berhasil diambil. Periksa log_broker/ di bagian Artifacts. Mungkin IPOT memblokir server ini.")
        sys.exit(1)
    folder = Path("data/broker")
    folder.mkdir(parents=True, exist_ok=True)
    nama = folder / f"{sekarang:%Y-%m-%d}{'_uji' if uji else ''}.json"
    nama.write_text(json.dumps({
        "tanggal": f"{sekarang:%Y-%m-%d}", "dibuat": sekarang.isoformat(timespec="seconds"),
        "sumber_daftar": sumber, "simbol": simbol, "batch": batch, "gagal": gagal,
    }, ensure_ascii=False))
    print(f"Disimpan: {nama} ({len(batch)} kelompok berhasil, {len(gagal)} gagal)")
    batas = (sekarang - timedelta(days=SIMPAN_HARI)).strftime("%Y-%m-%d")
    for f in folder.glob("*.json"):
        if f.name[:10] < batas:
            f.unlink()
            print(f"Dihapus (lebih dari {SIMPAN_HARI} hari): {f.name}")


if __name__ == "__main__":
    main()
