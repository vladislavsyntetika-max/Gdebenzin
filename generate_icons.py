import os
import struct
import zlib

BG = (20, 23, 26)
YEL = (255, 176, 0)


def make_png(size, path, ss=4):
    inv_ss = 1.0 / ss
    inv_sq = 1.0 / (ss * ss)
    cx = size / 2.0
    cy = size * 0.40
    r = size * 0.27
    tip = size * 0.86
    hr = r * 0.48
    hr2 = hr * hr
    r2 = r * r
    span = tip - cy

    raw = bytearray()
    for py in range(size):
        raw.append(0)
        for px in range(size):
            cov = 0
            for dy in range(ss):
                yy = py + (dy + 0.5) * inv_ss
                dy_cy = yy - cy
                inside_tri_row = (cy <= yy <= tip)
                if inside_tri_row:
                    t = (yy - cy) / span
                    hw = r * (1.0 - t)
                for dx in range(ss):
                    xx = px + (dx + 0.5) * inv_ss
                    dx_cx = xx - cx
                    d2 = dx_cx * dx_cx + dy_cy * dy_cy
                    if d2 <= r2:
                        is_pin = True
                    elif inside_tri_row and abs(dx_cx) <= hw:
                        is_pin = True
                    else:
                        is_pin = False
                    if is_pin and d2 > hr2:
                        cov += 1
            a = cov * inv_sq
            rr = int(BG[0] * (1 - a) + YEL[0] * a + 0.5)
            gg = int(BG[1] * (1 - a) + YEL[1] * a + 0.5)
            bb = int(BG[2] * (1 - a) + YEL[2] * a + 0.5)
            raw += bytes((rr, gg, bb, 255))

    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    print(f"OK  {path}  ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    os.makedirs("webapp", exist_ok=True)
    for s, p in [(192, "webapp/icon-192.png"), (512, "webapp/icon-512.png"), (180, "webapp/apple-touch-icon.png")]:
        make_png(s, p)
