"""IIS2ICLX V2 ASCII payload, CRC32 (zlib), bounded fragmented stream parser."""
import zlib

def encode(payload):
    b = payload.encode('ascii')
    if len(b) > 180 or b'\n' in b or b'*' in b:
        raise ValueError('invalid payload')
    return b'@' + b + b'*' + f'{zlib.crc32(b):08X}\n'.encode()

class Parser:
    def __init__(self):
        self.buf = bytearray()
        self.errors = 0
        self.discard = False
    def feed(self, data):
        result = []
        for c in data:
            if c == 10:
                if not self.discard and self.buf:
                    try:
                        raw = bytes(self.buf).rstrip(b'\r')
                        payload, crc = raw[1:].rsplit(b'*', 1)
                        if raw[:1] != b'@' or len(crc) != 8 or int(crc, 16) != zlib.crc32(payload):
                            raise ValueError('CRC')
                        parts = payload.decode('ascii').split(',')
                        if len(parts) < 2 or parts[1] != '2':
                            raise ValueError('version')
                        if parts[0] == 'D':
                            if len(parts) not in (18, 20): raise ValueError('data length')
                            nums = list(map(int, parts[2:]))
                            if any(not 0 <= x <= 0xffffffff for x in nums[:2]): raise ValueError('counter')
                            if any(not -32768 <= x <= 32767 for x in nums[2:4]): raise ValueError('raw')
                            if any(not -6000000 <= x <= 6000000 for x in nums[4:8]): raise ValueError('ug')
                            if any(x != -2147483648 and not -180000 <= x <= 180000 for x in nums[8:12]): raise ValueError('angle')
                            if not 0 <= nums[12] <= 63 or nums[13] not in (500,1000,2000,3000) or not 1 <= nums[14] <= 7 or not 0 <= nums[15] <= 0xffffffff: raise ValueError('config')
                            if len(nums) == 18 and any(not -6000000 <= x <= 6000000 for x in nums[16:18]): raise ValueError('wave baseline')
                        elif parts[0] == 'P':
                            if len(parts) != 6: raise ValueError('candidate')
                            list(map(int, parts[2:]))
                        elif parts[0] == 'S':
                            if len(parts) != 15: raise ValueError('status length')
                            list(map(int, parts[2:]))
                        elif parts[0] == 'G':
                            if len(parts) != 17: raise ValueError('config length')
                            list(map(int, parts[2:]))
                        elif parts[0] == 'A':
                            if len(parts) != 4 or parts[3] not in ('OK','ERR'): raise ValueError('ack')
                            int(parts[2])
                        result.append(parts)
                    except (ValueError, UnicodeError):
                        self.errors += 1
                self.buf.clear(); self.discard = False
            elif not self.discard:
                if len(self.buf) >= 191:
                    self.buf.clear(); self.discard = True; self.errors += 1
                else:
                    self.buf.append(c)
        return result
