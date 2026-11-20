import unittest
from protocol import Parser, encode

class ProtocolTests(unittest.TestCase):
    def test_fragmentation(self):
        frame=encode('D,2,0,1234,1000,-1000,61000,-61000,61000,-61000,0,0,-2147483648,-2147483648,3,2000,3,0')
        for split in range(len(frame)+1):
            parser=Parser()
            self.assertEqual(len(parser.feed(frame[:split])+parser.feed(frame[split:])),1)
    def test_corruption_recovery(self):
        frame=encode('D,2,0,1234,1000,-1000,61000,-61000,61000,-61000,0,0,-2147483648,-2147483648,3,2000,3,0')
        bad=bytearray(frame);bad[6]^=1
        parser=Parser();self.assertEqual(len(parser.feed(bad+frame)),1)
        self.assertEqual(parser.errors,1)
    def test_calibration_session_flag(self):
        parser = Parser()
        frame = encode('D,2,1,2000,100,-100,61000,-61000,61000,-61000,-2147483648,-2147483648,-2147483648,-2147483648,16,2000,3,0')
        self.assertEqual(len(parser.feed(frame)), 1)

    def test_status(self):
        parser=Parser()
        self.assertEqual(len(parser.feed(encode('S,2,1234,0,0,0,0,0,0,0,0,1,1,0,0'))),1)

    def test_config(self):
        parser=Parser()
        frame = encode('G,2,2000,3,52000,115200,0,0,0,-1,0,0,0,0,1000000,1000000,0')
        self.assertEqual(len(parser.feed(frame)), 1)

    def test_extended_data_frame_with_relative_wave_baseline(self):
        payload = 'D,2,123,456,10,-20,1000,-2000,900,-1900,100,200,0,0,39,500,3,0,125,-75'
        parser = Parser()
        packets = parser.feed(encode(payload))
        self.assertEqual(len(packets), 1)
        self.assertEqual(list(map(int, packets[0][2:]))[-2:], [125, -75])
        self.assertEqual(parser.errors, 0)

    def test_relative_wave_zero_flag(self):
        payload = 'D,2,123,456,10,-20,1000,-2000,900,-1900,100,200,0,0,39,500,3,0,0,0'
        parser = Parser()
        packets = parser.feed(encode(payload))
        self.assertEqual(len(packets), 1)
        self.assertTrue(int(packets[0][14]) & 32)

    def test_key_zero_feedback_packets(self):
        parser=Parser()
        frames=(encode('Z,2,SET,WAIT_STABLE')+
                encode('Z,2,SET,OK')+
                encode('Z,2,CLEAR,OK')+
                encode('Z,2,SET,ERR,NOT_STABLE_ANGLE_0_STABLE_0'))
        packets=parser.feed(frames)
        self.assertEqual([p[0] for p in packets],['Z','Z','Z','Z'])
        self.assertEqual(packets[0][3],'WAIT_STABLE')
        self.assertEqual(packets[1][3],'OK')
        self.assertEqual(parser.errors,0)

    def test_bounds(self):
        parser=Parser()
        self.assertEqual(parser.feed(b'x'*10000+b'\n'),[])
        self.assertEqual(len(parser.buf),0)
        self.assertEqual(len(parser.feed(encode('A,2,77,OK'))),1)

if __name__=='__main__':unittest.main()
