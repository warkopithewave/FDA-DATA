"""Arsip harian broker summary dari CLI idx (fzn0x/idx, MIT) ke data/broker/TANGGAL.json.

Cara kerja:
1. Ambil daftar saham teraktif dari `idx market overview` (bagian "most traded"). Kalau gagal dibaca,
   pakai daftar cadangan dan tulis peringatan di log.
2. Ambil `idx broker` per kelompok 10 saham, dengan jeda dan percobaan ulang.
3. Simpan ringkas per saham di data/broker/per_saham/KODE.json (satu file berisi riwayat hari-hari terakhir)
   dan nama broker di data/broker/brokers.json. Aplikasi hanya perlu membaca satu file kecil per saham.
4. Hari yang lebih tua dari 60 hari dibuang dari tiap file saham.

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


KIND = {"foreign": "A", "local": "L", "state_owned": "B"}  # A = asing, L = lokal, B = BUMN


def ringkas(daftar):
    """[[kode, jenis, lot, nilai, harga rata-rata], ...] supaya file kecil."""
    return [[b["code"], KIND.get(b.get("kind"), "L"), round(b["lots"]), round(b["value"]), b.get("average_price")]
            for b in daftar or []]


def muat_json(path, bawaan):
    try:
        return json.loads(path.read_text())
    except Exception:
        return bawaan


def simpan_per_saham(item, sekarang, folder, nama_broker):
    """Tambah atau timpa data satu hari di data/broker/per_saham/KODE.json, lalu buang hari yang terlalu lama."""
    tgl = str(item.get("to") or item.get("from") or "")
    if len(tgl) != 10 or not (item.get("buyers") or item.get("sellers")):
        return False
    for b in (item.get("buyers") or []) + (item.get("sellers") or []):
        if b.get("code") and b.get("name"):
            nama_broker[b["code"]] = b["name"]
    f = folder / f"{item['symbol']}.json"
    data = muat_json(f, {"simbol": item["symbol"], "hari": {}})
    data["nama"] = item.get("name") or data.get("nama", "")
    data["hari"][tgl] = {"b": ringkas(item.get("buyers")), "s": ringkas(item.get("sellers")),
                         "fn": item.get("foreign_net_value"), "tv": item.get("total_value"),
                         "hp": item.get("average_price")}
    batas = (sekarang - timedelta(days=SIMPAN_HARI)).strftime("%Y-%m-%d")
    data["hari"] = {k: v for k, v in sorted(data["hari"].items()) if k >= batas}
    data["dibuat"] = sekarang.isoformat(timespec="seconds")
    f.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return True


def main():
    LOG.mkdir(exist_ok=True)
    uji = os.environ.get("UJI") == "1"
    sekarang = datetime.now(WIB)
    simbol, sumber = daftar_simbol(uji)
    print(f"{len(simbol)} saham dari {sumber}")
    folder = Path("data/broker/per_saham")
    folder.mkdir(parents=True, exist_ok=True)
    f_broker = Path("data/broker/brokers.json")
    nama_broker = muat_json(f_broker, {})
    tersimpan, kosong, gagal = [], [], []
    for i in range(0, len(simbol), KELOMPOK):
        grup = simbol[i:i + KELOMPOK]
        data, pesan = jalankan(["broker", *grup], f"broker_{i // KELOMPOK + 1}")
        if data is None:
            gagal.append(grup)
            print(f"GAGAL {grup}: {pesan}")
        else:
            for item in (data.get("data") or []):
                if simpan_per_saham(item, sekarang, folder, nama_broker):
                    tersimpan.append(item["symbol"])
                else:
                    kosong.append(item.get("symbol"))
            print(f"ok {grup}")
        time.sleep(JEDA_DETIK)
    if not tersimpan:
        print("Tidak ada saham yang berhasil disimpan. Periksa log_broker/ di bagian Artifacts. Mungkin IPOT memblokir server ini.")
        sys.exit(1)
    f_broker.write_text(json.dumps(dict(sorted(nama_broker.items())), ensure_ascii=False, separators=(",", ":")))
    print(f"Tersimpan {len(tersimpan)} saham, kosong {len(kosong)}, kelompok gagal {len(gagal)}")


if __name__ == "__main__":
    main()
