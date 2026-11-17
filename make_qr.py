"""Tạo QR PNG từ địa chỉ truy cập thực sau khi chạy/deploy app.

Ví dụ: python make_qr.py --url https://YOUR-APP.streamlit.app
"""
from __future__ import annotations
import argparse
from pathlib import Path
from urllib.parse import urlparse
import qrcode


def main():
    parser=argparse.ArgumentParser(description="Tạo QR mở Booking Data Analyst Lab")
    parser.add_argument("--url",required=True,help="Địa chỉ URL app đang truy cập được")
    parser.add_argument("--out",default="booking_app_qr.png")
    args=parser.parse_args()
    p=urlparse(args.url.strip())
    if p.scheme not in {"http","https"} or not p.netloc:
        parser.error("URL phải bắt đầu bằng https:// hoặc http:// và có hostname.")
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=12,border=3)
    qr.add_data(args.url.strip()); qr.make(fit=True)
    out=Path(args.out).resolve()
    out.parent.mkdir(parents=True,exist_ok=True)
    qr.make_image(fill_color="#173953",back_color="white").save(out)
    print("QR:",out)
    print("Lưu ý: mã QR chỉ hoạt động khi URL truy cập được từ thiết bị quét.")

if __name__=="__main__": main()
