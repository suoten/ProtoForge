"""Regression: DB1.DBX3.1 bit read (0x01) must answer transport 0x03 (BIT);
word/byte reads keep 0x04; odd(0x09) length now in bits; bit writes are read-modify-write."""
import struct, sys
sys.path.insert(0, r"E:\硕腾网络\PyGBSentry\ProtoForge")
from protoforge.protocols.s7.server import S7Server

def read_req(ts, length, db, area, byte_off, bit):
    addr = byte_off * 8 + bit
    return bytes([
        0x03, 0x00, 0x00, 0x1F, 0x02, 0xF0, 0x80,
        0x32, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x0E, 0x00, 0x00,
        0x04, 0x01, 0x12, 0x0A, 0x10, ts,
    ]) + struct.pack(">H", length) + struct.pack(">H", db) + bytes([area]) + bytes(
        [(addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF])

def write_req(ts, length, db, area, byte_off, bit, value_byte):
    addr = byte_off * 8 + bit
    return bytes([
        0x03, 0x00, 0x00, 0x27, 0x02, 0xF0, 0x80,
        0x32, 0x01, 0x00, 0x00, 0x00, 0x01, 0x00, 0x0E, 0x00, 0x00,
        0x05, 0x01, 0x12, 0x0A, 0x10, ts,
    ]) + struct.pack(">H", length) + struct.pack(">H", db) + bytes([area]) + bytes(
        [(addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF]) + bytes([0x00, ts]) + struct.pack(">H", length) + bytes([value_byte]) + b"\x00"

srv = S7Server.__new__(S7Server)  # skip async init; only test frame builders
from protoforge.protocols.s7.server import S7DeviceBehavior
beh = S7DeviceBehavior.__new__(S7DeviceBehavior)
beh._values, beh._points, beh._point_addresses = {}, {}, {}
beh._db_data, beh._marker_data = {}, bytearray(64)
beh._input_data, beh._output_data = bytearray(64), bytearray(64)
beh._timer_data, beh._counter_data = bytearray(64), bytearray(64)
beh._area_lock = __import__("threading").Lock()
S7_AREA_DB, S7_AREA_MARKERS = 0x84, 0x83
beh.S7_AREA_DB, beh.S7_AREA_MARKERS = S7_AREA_DB, S7_AREA_MARKERS
# seed DB1: byte3 = 0x22 (bit1=1), DBW2 = 0x001D (29)
beh.write_area(S7_AREA_DB, 1, 4, struct.pack(">H", 29))
beh.write_area(S7_AREA_DB, 1, 3, bytes([0x22]))
srv._behaviors = {"dev1": beh}
srv._debug_callback = None
srv._default_device_id = "dev1"

# --- 1. bit read DB1.DBX3.1 (request ts=0x01, len=1 bit) ---
resp = srv._make_s7_read_response(read_req(0x01, 1, 1, S7_AREA_DB, 3, 1), "dev1")
item = resp[21:]
assert item[0] == 0xFF, f"return code {item[0]:02X}"
assert item[1] == 0x03, f"BIT response transport must be 0x03, got {item[1]:02X}"
assert struct.unpack(">H", item[2:4])[0] == 1, "BIT response length must be 1 bit"
assert item[4] == 0x22, f"bit data {item[4]:02X} != 0x22 (bit1=1)"
print("[OK] bit read DB1.DBX3.1 -> ff 03 00 01 22 00")

# --- 2. word read DB1.DBW2 (request ts=0x04, len=2 bytes) unchanged ---
resp = srv._make_s7_read_response(read_req(0x04, 2, 1, S7_AREA_DB, 4, 0), "dev1")
item = resp[21:]
assert item[0] == 0xFF and item[1] == 0x04
assert struct.unpack(">H", item[2:4])[0] == 16, "BYTE/WORD/DWORD response length in bits"
assert struct.unpack(">H", item[4:6])[0] == 29
print("[OK] word read DB1.DBW2 -> ff 04 00 10 00 1D")

# --- 3. odd(0x09) 3-byte read: length now in bits (24), was wrong before ---
resp = srv._make_s7_read_response(read_req(0x09, 24, 1, S7_AREA_DB, 2, 0), "dev1")
item = resp[21:]
assert item[1] == 0x09 and struct.unpack(">H", item[2:4])[0] == 24
print("[OK] odd-byte read len-in-bits (24)")

# --- 4. bit write read-modify-write: DB1 byte3=0x22, write bit0=1 -> 0x23 ---
resp = srv._make_s7_write_response(write_req(0x03, 1, 1, S7_AREA_DB, 3, 0, 0x01), "dev1")
assert resp[-1] == 0xFF
assert beh.read_area(S7_AREA_DB, 1, 3, 1)[0] == 0x23, "bit0 set must not clobber other bits"
# --- 5. bit write bit1=0 -> 0x21 ---
resp = srv._make_s7_write_response(write_req(0x03, 1, 1, S7_AREA_DB, 3, 1, 0x00), "dev1")
assert beh.read_area(S7_AREA_DB, 1, 3, 1)[0] == 0x21, "bit1 clear must keep bit0"
print("[OK] bit write read-modify-write (0x22 -> 0x23 -> 0x21)")

# --- 6. byte write still whole-byte (ts=0x04) ---
resp = srv._make_s7_write_response(write_req(0x04, 8, 1, S7_AREA_DB, 3, 0, 0xAA), "dev1")
assert beh.read_area(S7_AREA_DB, 1, 3, 1)[0] == 0xAA
print("[OK] byte write unchanged")
print("ALL S7 BIT READ/WRITE REGRESSION PASSED")




