"""Generate one printable QR code per kiosk in the lot config.

    python scripts/make_qr.py --base-url https://parking.example.com

Each QR opens  <base-url>/?kiosk=<ID>  so the site knows where the visitor is standing.
"""
import argparse
import sys
from pathlib import Path

import qrcode

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.lot import load_lot  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--config", default="config/lot.json")
    ap.add_argument("--out", default="qr")
    a = ap.parse_args()
    lot = load_lot(a.config)
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    for p in lot.points.values():
        if p.kind != "kiosk":
            continue
        url = f"{a.base_url.rstrip('/')}/?kiosk={p.id}"
        qrcode.make(url, box_size=12, border=3).save(out / f"{p.id}.png")
        print(f"{p.id:4} {p.name:35} -> {out / (p.id + '.png')}  ({url})")


if __name__ == "__main__":
    main()
