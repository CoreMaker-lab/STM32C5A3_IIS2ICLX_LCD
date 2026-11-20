"""IIS2ICLX dual-axis monitor. UI thread owns all widgets; worker owns serial."""
import csv
import math
import queue
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import serial
from serial.tools import list_ports
from PySide6 import QtCore, QtWidgets
import pyqtgraph as pg
from protocol import Parser, encode
from calibration_ui import CalibrationDialog

class SerialWorker(QtCore.QThread):
    batch = QtCore.Signal(list, int)
    message = QtCore.Signal(str)
    connected = QtCore.Signal()
    def __init__(self, port, baud):
        super().__init__()
        self.port = port
        self.baud = baud
        self.commands = queue.Queue(maxsize=32)
        self.stop_requested = False
    def run(self):
        parser = Parser()
        try:
            with serial.Serial(self.port, self.baud, timeout=.03, write_timeout=.3) as dev:
                self.connected.emit()
                pending = []
                switch = None
                last = time.monotonic()
                while not self.stop_requested:
                    try:
                        cmd = self.commands.get_nowait()
                    except queue.Empty:
                        cmd = None
                    if isinstance(cmd,tuple):switch=(time.monotonic()+.4,cmd[1])
                    elif cmd is not None:dev.write(cmd)
                    if switch and time.monotonic()>=switch[0]:
                        dev.baudrate=switch[1];self.baud=switch[1];dev.reset_input_buffer();parser=Parser()
                        switch=None;self.message.emit(f'PC 串口已切到 {self.baud}，等待 MCU 确认。')
                    pending.extend(parser.feed(dev.read(min(max(dev.in_waiting, 1), 4096))))
                    now = time.monotonic()
                    if now-last >= .05:
                        self.batch.emit(pending, parser.errors)
                        pending = []; last = now
                if pending: self.batch.emit(pending, parser.errors)
        except Exception as exc:
            self.message.emit(f'串口错误：{exc}')

class Monitor(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.lang = 'zh'
        self.setWindowTitle('STM32C5A3 IIS2ICLX 双轴倾角监测')
        self.resize(1180, 860)
        self.worker = None; self.csv_file = None; self.writer = None
        self.pending = {}; self.command_id = 0; self.board_hold = False; self.board_light = True
        self.history = deque(maxlen=22000); self.latest = None
        self.last_seq = self.last_tick = None; self.elapsed = 0.0
        self.received = 0; self.gaps = 0; self.reboots = 0
        self.rate_count = 0; self.rate_time = time.monotonic(); self.rate = 0
        self.last_sample_time = None; self.record_count = 0
        self.local_hold = False
        self.config={};self.candidate=None;self.cal_dialog=None;self.extended=None;self.last_epoch=None;self.board_snapshot=None
        self.baud_switching=False;self.switch_deadline=0;self.expected_baud=None;self.last_ping=0
        self._plot_last_x_right=-1.0;self._plot_last_y=0.0;self._plot_last_y_update=0.0
        self._plot_shrink_since=None;self._plot_next_x_update=0.0
        self._plot_update_period=0.033;self._plot_max_points=1600
        self._plot_next_update=0.0
        self._plot_fps=0.0;self._plot_frames=0;self._plot_fps_time=time.monotonic()
        root = QtWidgets.QWidget(); self.setCentralWidget(root)
        layout = QtWidgets.QVBoxLayout(root)
        bar = QtWidgets.QHBoxLayout(); layout.addLayout(bar)
        self.ports = QtWidgets.QComboBox(); self.ports.setMinimumWidth(240)
        self.refresh_btn = QtWidgets.QPushButton('刷新串口'); self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn = QtWidgets.QPushButton('连接'); self.connect_btn.clicked.connect(self.toggle_connect)
        self.record_btn = QtWidgets.QPushButton('开始 CSV 记录'); self.record_btn.clicked.connect(self.toggle_record)
        self.pause_btn = QtWidgets.QPushButton('暂停 PC 显示'); self.pause_btn.clicked.connect(self.pause_local)
        for w in [self.ports,self.refresh_btn,self.connect_btn,self.record_btn,self.pause_btn]: bar.addWidget(w)
        self.baud_box=QtWidgets.QComboBox();self.baud_box.addItems(['115200','230400','460800','921600','2000000']);self.baud_box.setCurrentText('2000000')
        self.baud_label = QtWidgets.QLabel('波特率')
        bar.addWidget(self.baud_label);bar.addWidget(self.baud_box)
        self.baud_apply=QtWidgets.QPushButton('同步切换');self.baud_apply.clicked.connect(lambda:self.send('BAUD',int(self.baud_box.currentText())));self.baud_apply.setEnabled(False)
        bar.addWidget(self.baud_apply)
        bar.addStretch()
        self.language_box = QtWidgets.QComboBox()
        self.language_box.addItem('中文', 'zh')
        self.language_box.addItem('English', 'en')
        self.language_box.currentIndexChanged.connect(self.change_language)
        bar.addWidget(self.language_box)
        values = QtWidgets.QHBoxLayout(); layout.addLayout(values)
        self.values=[]
        for axis,color in [('X','#34c9ed'),('Y','#57d68d')]:
            lab=QtWidgets.QLabel(f'{axis}: -- mg\nRAW: --')
            lab.setStyleSheet(f'font-size:20px; color:{color}; background:#18212f; padding:14px;')
            values.addWidget(lab); self.values.append(lab)
        self.stats=QtWidgets.QLabel('未连接 | 量程 ±2 g | 标称 ODR 52 Hz');layout.addWidget(self.stats)
        pg.setConfigOptions(antialias=False)
        self.plot=pg.PlotWidget(title='X / Y 校准后振动加速度（相对置零后围绕 0 mg）')
        self.plot.setLabel('left','校准后加速度',units='mg'); self.plot.setLabel('bottom','设备采样读取时间',units='s')
        self.plot.addLegend();self.plot.showGrid(x=True,y=True,alpha=.2)
        self.curves=[self.plot.plot(pen=pg.mkPen(c,width=2),name=a,connect='finite') for a,c in [('X','#34c9ed'),('Y','#57d68d')]]
        # Do not let pyqtgraph auto-range on every setData(). The application controls Y range.
        self.plot.enableAutoRange(axis='x', enable=False)
        self.plot.enableAutoRange(axis='y', enable=False)
        for curve in self.curves:
            curve.setDownsampling(auto=True, method='peak', ds=1)
            curve.setClipToView(True)
        layout.addWidget(self.plot,1)
        controls=QtWidgets.QHBoxLayout();layout.addLayout(controls)
        self.hold_btn=QtWidgets.QPushButton('暂停板端显示');self.hold_btn.clicked.connect(lambda:self.send('HOLD',int(not self.board_hold)))
        self.light_btn=QtWidgets.QPushButton('关闭背光');self.light_btn.clicked.connect(lambda:self.send('LIGHT',int(not self.board_light)))
        self.range_box=QtWidgets.QComboBox();self.range_box.addItems(['自动','±20 mg','±50 mg','±100 mg','±200 mg','±500 mg','±1000 mg','±2000 mg'])
        self.plot_range_btn=QtWidgets.QPushButton('设置 PC 曲线范围');self.plot_range_btn.clicked.connect(self.apply_plot_range)
        self.clear_plot_btn=QtWidgets.QPushButton('清除 PC 曲线');self.clear_plot_btn.clicked.connect(self.clear_plot)
        self.remote_widgets=[self.hold_btn,self.light_btn]
        for w in self.remote_widgets:controls.addWidget(w)
        controls.addWidget(self.range_box)
        controls.addWidget(self.plot_range_btn)
        controls.addWidget(self.clear_plot_btn)
        for w in self.remote_widgets:w.setEnabled(False)
        settings=QtWidgets.QHBoxLayout();layout.addLayout(settings)
        self.fs_box=QtWidgets.QComboBox()
        for v in [500,1000,2000,3000]:self.fs_box.addItem(f'±{v/1000:g} g',v)
        self.fs_box.setCurrentIndex(2)
        self.fs_apply=QtWidgets.QPushButton('设置采集量程');self.fs_apply.clicked.connect(lambda:self.send('FS',self.fs_box.currentData()))
        self.odr_box=QtWidgets.QComboBox()
        for i,v in enumerate([12.5,26,52,104,208,416,833],1):self.odr_box.addItem(f'{v:g} Hz',i)
        self.odr_box.setCurrentIndex(2)
        self.odr_apply=QtWidgets.QPushButton('设置采样率');self.odr_apply.clicked.connect(lambda:self.send('ODR',self.odr_box.currentData()))
        self.cal_btn=QtWidgets.QPushButton('四位置校准');self.cal_btn.clicked.connect(self.open_calibration)
        self.reset_btn=QtWidgets.QPushButton('清空四位置校准');self.reset_btn.setToolTip('清除已保存的四位置 Offset/Gain，恢复默认参数；同时清除依赖旧校准坐标系的相对角度零点和波形基线。');self.reset_btn.clicked.connect(self.reset_calibration)
        self.zero_btn=QtWidgets.QPushButton('相对置零（角度+波形）');self.zero_btn.setToolTip('记录当前稳定姿态和静态加速度基线；相对角度归零，振动波形围绕 0 mg 显示。绝对校准加速度与 RAW 保留。');self.zero_btn.clicked.connect(lambda:self.send('ZERO',0))
        self.unzero_btn=QtWidgets.QPushButton('取消相对置零');self.unzero_btn.clicked.connect(lambda:self.send('UNZERO',0))
        self.setting_widgets=[self.fs_box,self.fs_apply,self.odr_box,self.odr_apply,self.cal_btn,self.reset_btn,self.zero_btn,self.unzero_btn]
        for w in self.setting_widgets:settings.addWidget(w)
        for w in self.setting_widgets:w.setEnabled(False)
        self.actual=QtWidgets.QLabel('实际配置：等待 MCU 回报。UART 默认波特率：2,000,000。');layout.addWidget(self.actual)
        self.tip=QtWidgets.QLabel('倾角：敏感轴相对水平面，asin(a/g)，±90°；仅适用于静止/缓慢运动，不是完整姿态角。稳定判定不能排除恒定线性加速度。')
        self.tip.setWordWrap(True);layout.addWidget(self.tip)
        self.board=QtWidgets.QLabel('板端状态：等待数据');layout.addWidget(self.board)
        self.log=QtWidgets.QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(115)
        self.log.document().setMaximumBlockCount(150);layout.addWidget(self.log)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.render);self.timer.start(16)
        self.refresh_ports()
        self.apply_language()
    def tr(self, zh, en):
        return zh if self.lang == 'zh' else en

    def change_language(self, index):
        lang = self.language_box.currentData()
        if lang not in ('zh', 'en'):
            return
        self.lang = lang
        self.apply_language()

    def apply_language(self):
        en = self.lang == 'en'
        self.setWindowTitle('STM32C5A3 IIS2ICLX Dual-axis Tilt Monitor' if en else 'STM32C5A3 IIS2ICLX 双轴倾角监测')
        self.refresh_btn.setText('Refresh Ports' if en else '刷新串口')
        self.connect_btn.setText(('Disconnect' if en else '断开') if self.worker else ('Connect' if en else '连接'))
        self.record_btn.setText(('Stop CSV Recording' if en else '停止 CSV 记录') if self.csv_file else ('Start CSV Recording' if en else '开始 CSV 记录'))
        self.pause_btn.setText(('Resume PC Display' if en else '恢复 PC 显示') if self.local_hold else ('Pause PC Display' if en else '暂停 PC 显示'))
        self.baud_label.setText('Baud rate' if en else '波特率')
        self.baud_apply.setText('Switch baud rate' if en else '同步切换波特率')
        self.stats.setText('Disconnected | Range ±2 g | Nominal ODR 52 Hz' if en else '未连接 | 量程 ±2 g | 标称 ODR 52 Hz')
        self.plot.setTitle('Calibrated X / Y Vibration Acceleration (relative-zero baseline removed)' if en else 'X / Y 校准后振动加速度（相对置零后围绕 0 mg）')
        self.plot.setLabel('left', 'Calibrated acceleration' if en else '校准后加速度', units='mg')
        self.plot.setLabel('bottom', 'Device sample time' if en else '设备采样读取时间', units='s')
        self.hold_btn.setText(('Resume Board Display' if en else '恢复板端显示') if self.board_hold else ('Pause Board Display' if en else '暂停板端显示'))
        self.light_btn.setText(('Turn Backlight Off' if en else '关闭背光') if self.board_light else ('Turn Backlight On' if en else '开启背光'))
        self.range_box.setItemText(0, 'Auto' if en else '自动')
        self.plot_range_btn.setText('Set PC Plot Range' if en else '设置 PC 曲线范围')
        self.clear_plot_btn.setText('Clear PC Plot' if en else '清除 PC 曲线')
        self.fs_apply.setText('Set Full Scale' if en else '设置采集量程')
        self.odr_apply.setText('Set Sample Rate' if en else '设置采样率')
        self.cal_btn.setText('Four-position Calibration' if en else '四位置校准')
        self.reset_btn.setText('Clear Four-position Calibration' if en else '清空四位置校准')
        self.zero_btn.setText('Relative Zero (Tilt + Waveform)' if en else '相对置零（角度+波形）')
        self.unzero_btn.setText('Cancel Relative Zero' if en else '取消相对置零')
        self.actual.setText('Actual configuration: waiting for MCU. UART default: 2,000,000 baud.' if en else '实际配置：等待 MCU 回报。UART 默认波特率：2,000,000。')
        self.tip.setText('Tilt: sensitive-axis angle relative to horizontal, asin(a/g), ±90°. Intended for stationary/slow motion; not a full attitude solution. Stability detection cannot reject constant linear acceleration.' if en else '倾角：敏感轴相对水平面，asin(a/g)，±90°；仅适用于静止/缓慢运动，不是完整姿态角。稳定判定不能排除恒定线性加速度。')
        self.board.setText('Board status: waiting for data' if en else '板端状态：等待数据')
        if self.config:
            c=self.config
            if en:
                self.actual.setText(f"Actual: ±{c['fs']/1000:g} g / {c['millihz']/1000:g} Hz / {c['baud']} baud | Calibration {'saved' if c['calibrated'] else 'default'} | Flash {c['nvm']} | Offset ug {c['offset_x']}, {c['offset_y']} | Gain {c['gain_x']/1e6:.6f}, {c['gain_y']/1e6:.6f}")
            else:
                self.actual.setText(f"实际：±{c['fs']/1000:g} g / {c['millihz']/1000:g} Hz / {c['baud']} baud | 校准 {'已保存' if c['calibrated'] else '默认'} | Flash {c['nvm']} | 偏置ug {c['offset_x']}, {c['offset_y']} | 增益 {c['gain_x']/1e6:.6f}, {c['gain_y']/1e6:.6f}")
        if self.board_snapshot:
            irq,samples,readerr,fallback,drop,lcd,hold,rng,light,ok,txerr,rxov=self.board_snapshot
            self.board.setText(
                (f'Board: Sensor {"OK" if ok else "ERROR"} | LCD {lcd} | IRQ {irq} | Samples {samples} | SPI errors {readerr} | Fallback reads {fallback} | TX drop/errors {drop}/{txerr} | RX overflow {rxov} | Range {rng}')
                if en else
                (f'板端：传感器 {"正常" if ok else "异常"} | LCD {lcd} | IRQ {irq} | 采集 {samples} | SPI错误 {readerr} | 兜底读取 {fallback} | TX丢弃/错误 {drop}/{txerr} | RX溢出 {rxov} | 范围档位 {rng}')
            )
        self.reset_btn.setToolTip(
            'Clear saved four-position Offset/Gain and restore defaults. Relative angle zero and waveform baseline are also cleared.'
            if en else
            '清除已保存的四位置 Offset/Gain，恢复默认参数；同时清除依赖旧校准坐标系的相对角度零点和波形基线。'
        )
        self.zero_btn.setToolTip(
            'Capture the current stable tilt and static acceleration baseline. Relative tilt becomes zero and the vibration waveform is centred around 0 mg. Absolute calibrated acceleration and RAW are retained.'
            if en else
            '记录当前稳定姿态和静态加速度基线；相对角度归零，振动波形围绕 0 mg 显示。绝对校准加速度与 RAW 保留。'
        )
        if self.cal_dialog:
            self.cal_dialog.apply_language()

    def note(self,text):
        self.log.appendPlainText(time.strftime('%H:%M:%S ')+text)
    def refresh_ports(self):
        selected=self.ports.currentData();self.ports.clear()
        preferred = None
        for p in list_ports.comports():
            self.ports.addItem(f'{p.device} — {p.description}',p.device)
            desc = (p.description or '').lower()
            if preferred is None and ('usb serial device' in desc or 'usb 串行设备' in desc):
                preferred = p.device
        idx=self.ports.findData(selected)
        if idx>=0:self.ports.setCurrentIndex(idx)
        elif preferred is not None:self.ports.setCurrentIndex(self.ports.findData(preferred))
    def toggle_connect(self):
        if self.worker:
            self.worker.stop_requested=True;self.connect_btn.setEnabled(False);return
        port=self.ports.currentData()
        if not port:self.note(self.tr('未找到串口，请连接开发板后刷新。','No serial port found. Connect the board and refresh ports.'));return
        self.history.clear();self.latest=None;self.last_seq=self.last_tick=None;self.elapsed=0
        self.plot_elapsed=0.0;self.last_plot_host=None
        self._plot_last_x_right=-1.0;self._plot_last_y=0.0;self._plot_last_y_update=0.0
        self._plot_shrink_since=None;self._plot_next_x_update=0.0;self._plot_next_update=0.0
        self.received=self.gaps=self.reboots=0;self.rate_count=0;self.rate_time=time.monotonic();self.rate=0
        self.last_sample_time=None;self.last_data_host=0.0;self.pending.clear();self.parser_errors=0
        self.config={};self.last_epoch=None;self.extended=None;self.baud_switching=False
        self.worker=SerialWorker(port,int(self.baud_box.currentText()))
        self.worker.batch.connect(self.on_batch);self.worker.message.connect(self.note)
        self.worker.connected.connect(self.on_connected);self.worker.finished.connect(self.on_finished)
        self.connect_btn.setText(self.tr('正在连接…','Connecting…'));self.connect_btn.setEnabled(False);self.ports.setEnabled(False)
        self.worker.start()
    def on_connected(self):
        self.connect_btn.setText(self.tr('断开','Disconnect'));self.connect_btn.setEnabled(True)
        for w in self.remote_widgets+self.setting_widgets:w.setEnabled(True)
        self.baud_apply.setEnabled(True)
        self.note(self.tr(f'串口已打开：{self.baud_box.currentText()} 8N1。等待 V2 数据。',f'Serial port opened at {self.baud_box.currentText()} 8N1. Waiting for V2 data.'));self.send('PING',0)
    def on_finished(self):
        worker=self.worker;self.worker=None
        if worker:worker.deleteLater()
        self.connect_btn.setText(self.tr('连接','Connect'));self.connect_btn.setEnabled(True);self.ports.setEnabled(True)
        for w in self.remote_widgets:w.setEnabled(False)
        self.config={};self.extended=None;self.latest=None;self.baud_switching=False
        for w in self.setting_widgets:w.setEnabled(False)
        self.baud_apply.setEnabled(False)
        self.pending.clear();self.stop_record();self.board.setText(self.tr('板端状态：串口已断开','Board status: serial disconnected'));self.note(self.tr('串口已关闭。','Serial port closed.'))
    def send(self,verb,value):
        if not self.worker or not self.worker.isRunning():return
        if self.pending or self.baud_switching:
            if verb!='PING':self.note(self.tr('有命令等待应答或正在切换波特率，请稍后。','A command is pending or baud-rate switching is in progress. Please wait.'))
            return
        self.command_id=(self.command_id+1)&0xffffffff
        ident=self.command_id
        try:self.worker.commands.put_nowait(encode(f'C,2,{ident},{verb},{value}'))
        except queue.Full:self.note(self.tr('发送队列已满。','Command queue is full.'));return
        self.pending[ident]=(time.monotonic(),verb,value)
    def pause_local(self):
        self.local_hold=not self.local_hold
        self.pause_btn.setText(self.tr('恢复 PC 显示','Resume PC Display') if self.local_hold else self.tr('暂停 PC 显示','Pause PC Display'))
    def apply_plot_range(self):
        idx = self.range_box.currentIndex()
        limits = [None, 20, 50, 100, 200, 500, 1000, 2000]
        value = limits[idx]
        self.plot.enableAutoRange(axis='y', enable=False)
        if value is None:
            self._plot_last_y=0.0
            self._plot_last_y_update=0.0
            self._plot_shrink_since=None
            self.note(self.tr('PC 曲线 Y 轴恢复自动量程。','PC plot Y-axis returned to auto range.'))
        else:
            self._plot_last_y=float(value)
            self.plot.setYRange(-value, value, padding=0)
            self.note(self.tr(f'PC 曲线 Y 轴范围设置为 ±{value} mg。',f'PC plot Y range set to ±{value} mg.'))
    def clear_plot(self):
        self.history.clear()
        # Keep the monotonic plot clock so the next samples continue scrolling
        # from the current right edge instead of jumping back to 0 s.
        self.curves[0].setData([], [])
        self.curves[1].setData([], [])
        self.note(self.tr('PC 曲线缓存已清除；串口采集继续，时间轴保持连续。','PC plot buffer cleared; serial acquisition continues and the time axis remains continuous.'))
    def stop_record(self):
        if self.csv_file:
            try:self.csv_file.close()
            except OSError as exc:self.note(f'关闭 CSV 失败：{exc}')
        self.csv_file=None;self.writer=None;self.record_btn.setText(self.tr('开始 CSV 记录','Start CSV Recording'))
    def toggle_record(self):
        if self.csv_file:self.stop_record();self.note('CSV 记录已停止。');return
        if not self.worker:self.note(self.tr('请先连接开发板。','Connect the board first.'));return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,self.tr('保存原始数据','Save raw data'),f'IIS2ICLX_{time.strftime("%Y%m%d_%H%M%S")}.csv','CSV (*.csv)')
        if not path:return
        try:
            self.csv_file=open(path,'w',newline='',encoding='utf-8-sig');self.writer=csv.writer(self.csv_file)
            self.writer.writerow(['host_utc','session_segment','sequence','mcu_tick_ms','raw_x','raw_y','x_ug','y_ug','x_mg','y_mg','corrected_x_ug','corrected_y_ug','wave_x_ug','wave_y_ug','absolute_x_deg','absolute_y_deg','relative_x_deg','relative_y_deg','flags','fs_mg','odr_code','config_epoch'])
            self.record_count=0;self.record_btn.setText(self.tr('停止 CSV 记录','Stop CSV Recording'));self.note('正在记录：'+path)
        except OSError as exc:self.stop_record();self.note(f'无法创建 CSV：{exc}')
    def on_batch(self,packets,errors):
        self.parser_errors=errors
        for p in packets:
            kind=p[0]
            if kind=='D':
                nums=list(map(int,p[2:]))
                seq,tick,rx,ry,ux,uy,cx,cy,ax,ay,zx,zy,flags,fs,odr,epoch=nums[:16]
                wave_x,wave_y=(nums[16:18] if len(nums)>=18 else (cx,cy))
                delta=0 if self.last_seq is None else (seq-self.last_seq)&0xffffffff
                # Use the packet sequence as the authoritative stream continuity
                # indicator. Do not treat a temporary MCU tick anomaly as a reboot:
                # that used to clear the plot and restart it from the left.
                reset=self.last_seq is not None and delta>0x80000000
                if self.last_seq is not None and delta==0 and not reset:
                    continue
                if reset:
                    self.reboots+=1
                    # Start a new segment without resetting the visible time axis.
                    self.history.clear()
                    self.elapsed=self.plot_elapsed
                    self.last_tick=None
                    self.last_plot_host=None
                    self.last_epoch=None
                    self._plot_last_x_right=-1.0
                    self.note('检测到 MCU 序号回退，开始新的曲线段。')
                elif delta>1:
                    self.gaps+=delta-1
                    self.history.append((self.plot_elapsed,math.nan,math.nan))
                if self.last_epoch is not None and self.last_epoch!=epoch:
                    self.history.append((self.plot_elapsed,math.nan,math.nan))
                self.last_epoch=epoch

                # Advance the plot clock from MCU sample sequence, not GUI batch
                # arrival time. This keeps the waveform uniformly spaced even when
                # several samples arrive in one USB read.
                odr_hz = self.config.get('millihz', 52000) / 1000.0
                if not (1.0 <= odr_hz <= 10000.0):
                    odr_hz = 52.0
                step_count = 1 if self.last_seq is None else max(1, min(delta, 1000))
                self.plot_elapsed += step_count / odr_hz
                self.elapsed=self.plot_elapsed
                self.last_seq=seq;self.last_tick=tick
                self.history.append((self.plot_elapsed,wave_x/1000,wave_y/1000));self.latest=(rx,ry,ux,uy,cx,cy,wave_x,wave_y)
                # Retain by device time, not a point count tied to a low ODR.
                # Capacity includes discontinuity markers at the maximum ODR.
                cutoff=self.elapsed-12.0
                while len(self.history)>1 and self.history[1][0]<cutoff:
                    self.history.popleft()
                self.extended=(ax,ay,zx,zy,flags)
                self.received+=1;self.rate_count+=1;self.last_sample_time=time.monotonic();self.last_data_host=self.last_sample_time
                if self.writer:
                    try:
                        self.writer.writerow([datetime.now(timezone.utc).isoformat(),self.reboots,seq,tick,rx,ry,ux,uy,ux/1000,uy/1000,cx,cy,wave_x,wave_y,ax/1000 if flags&1 else '',ay/1000 if flags&1 else '',zx/1000 if (flags&3)==3 else '',zy/1000 if (flags&3)==3 else '',flags,fs,odr,epoch])
                        self.record_count+=1
                        if self.record_count%52==0:self.csv_file.flush()
                    except OSError as exc:self.note(f'CSV 写入失败：{exc}');self.stop_record()
            elif kind=='S':
                tick,irq,samples,readerr,fallback,drop,lcd,hold,rng,light,ok,txerr,rxov=map(int,p[2:])
                self.board_hold=bool(hold);self.board_light=bool(light)
                self.board_snapshot=(irq,samples,readerr,fallback,drop,lcd,hold,rng,light,ok,txerr,rxov)
                self.hold_btn.setText(self.tr('恢复板端显示','Resume Board Display') if hold else self.tr('暂停板端显示','Pause Board Display'))
                self.light_btn.setText(self.tr('关闭背光','Turn Backlight Off') if light else self.tr('开启背光','Turn Backlight On'))
                self.board.setText(
                    (f'Board: Sensor {"OK" if ok else "ERROR"} | LCD {lcd} | IRQ {irq} | Samples {samples} | SPI errors {readerr} | Fallback reads {fallback} | TX drop/errors {drop}/{txerr} | RX overflow {rxov} | Range {rng}')
                    if self.lang == 'en' else
                    (f'板端：传感器 {"正常" if ok else "异常"} | LCD {lcd} | IRQ {irq} | 采集 {samples} | SPI错误 {readerr} | 兜底读取 {fallback} | TX丢弃/错误 {drop}/{txerr} | RX溢出 {rxov} | 范围档位 {rng}')
                )
            elif kind=='P':
                if len(p)==6:
                    try:self.candidate=list(map(int,p[2:]))
                    except ValueError:pass
            elif kind=='G':
                names=['fs','odr','millihz','baud','epoch','session','mask','face','count','nvm','offset_x','offset_y','gain_x','gain_y','calibrated']
                self.config=dict(zip(names,map(int,p[2:])))
                c=self.config
                # Keep the controls synchronized with the actual MCU state.
                # Selecting a value alone is only a pending UI choice; after
                # the MCU confirms the command, the combo reflects the real FS/ODR.
                fs_idx=self.fs_box.findData(c['fs'])
                if fs_idx >= 0 and not self.fs_box.hasFocus():
                    self.fs_box.setCurrentIndex(fs_idx)
                odr_idx=self.odr_box.findData(c['odr'])
                if odr_idx >= 0 and not self.odr_box.hasFocus():
                    self.odr_box.setCurrentIndex(odr_idx)
                if self.baud_switching and c['baud']==self.expected_baud:
                    self.baud_switching=False;self.baud_box.setCurrentText(str(c['baud']));self.note('MCU 已确认新波特率。')
                for w in self.setting_widgets:w.setEnabled(not c['session'] and not self.baud_switching)
                self.actual.setText(
                    (f"Actual: ±{c['fs']/1000:g} g / {c['millihz']/1000:g} Hz / {c['baud']} baud | Calibration {'saved' if c['calibrated'] else 'default'} | Flash {c['nvm']} | Offset ug {c['offset_x']}, {c['offset_y']} | Gain {c['gain_x']/1e6:.6f}, {c['gain_y']/1e6:.6f}")
                    if self.lang == 'en' else
                    (f"实际：±{c['fs']/1000:g} g / {c['millihz']/1000:g} Hz / {c['baud']} baud | 校准 {'已保存' if c['calibrated'] else '默认'} | Flash {c['nvm']} | 偏置ug {c['offset_x']}, {c['offset_y']} | 增益 {c['gain_x']/1e6:.6f}, {c['gain_y']/1e6:.6f}")
                )
            elif kind=='A':
                ident=int(p[2]);cmd=self.pending.pop(ident,None)
                self.note(f'命令 {cmd[1:] if cmd else ident}：{p[3]}')
                if cmd and cmd[1]=='ZERO' and p[3]=='OK':
                    self.note(self.tr('相对置零成功：角度参考与静态加速度基线已同时保存；波形改为围绕 0 mg，绝对校准加速度和 RAW 保留。','Relative zero saved: tilt reference and static acceleration baseline captured. Waveform is now centred around 0 mg; absolute calibrated acceleration and RAW are retained.'))
                if cmd and cmd[1]=='BAUD' and p[3]=='OK' and self.worker:
                    self.expected_baud=cmd[2];self.baud_switching=True;self.switch_deadline=time.monotonic()+3
                    self.worker.commands.put_nowait(('baud',cmd[2]))
                if cmd and p[3]=='ERR':self.note('设置未确认：检查带宽、稳定性、校准流程或 Flash 状态。')
            elif kind=='Z':
                action=p[2] if len(p)>2 else 'UNKNOWN'
                result=p[3] if len(p)>3 else 'UNKNOWN'
                detail=' '.join(p[4:])
                if action=='SET' and result=='WAIT_STABLE':
                    self.note('K3 置零请求已收到：等待传感器进入稳定状态（最多 3 秒）。')
                elif action=='SET' and result=='OK':
                    self.note('K3 相对置零成功：角度零点与波形基线已保存。')
                elif action=='CLEAR' and result=='OK':
                    self.note('K3 长按：已取消相对置零并保存。')
                else:
                    self.note(f'K3 {"置零" if action=="SET" else "清零"}失败：{detail or result}')
            else:self.note(','.join(p))
    def latest_wave_value(self, axis):
        if not self.latest: return 0.0
        return (self.latest[6] if axis == 'X' else self.latest[7]) / 1000.0
    def render(self):
        now=time.monotonic();dt=now-self.rate_time
        if dt>=1:
            self.rate=self.rate_count/dt;self.rate_count=0;self.rate_time=now
        for ident,(sent,verb,value) in list(self.pending.items()):
            if now-sent>5:self.pending.pop(ident);self.note(f'{verb}={value} 应答超时，未确认执行结果。')
        if self.baud_switching and now>self.switch_deadline:
            self.baud_switching=False;self.note('未收到新波特率确认：请断开并按目标波特率重连；复位 MCU 后请使用固件的默认波特率。')
        if self.worker and now-self.last_ping>5 and not self.pending and not self.baud_switching:
            self.last_ping=now;self.send('PING',0)
        fresh=self.worker is not None and self.last_sample_time is not None and now-self.last_sample_time<2
        state_zh='数据正常' if fresh else ('等待/数据超时' if self.worker else '未连接')
        state_en='Data OK' if fresh else ('Waiting / timeout' if self.worker else 'Disconnected')
        zeroed=bool(self.extended and (self.extended[4] & 32))
        zero_zh='波形基线已置零' if zeroed else '波形基线未置零'
        zero_en='Waveform baseline zeroed' if zeroed else 'Waveform baseline not zeroed'
        odr_value=self.config.get('millihz',52000)/1000
        if self.lang == 'en':
            self.stats.setText(f"{state_en} | {zero_en} | Nominal {odr_value:g} Hz | RX {self.rate:.1f} samples/s | Samples {self.received} | Seq gaps {self.gaps} | CRC/format errors {getattr(self,'parser_errors',0)} | Plot {self._plot_fps:.1f} FPS | CSV {self.record_count}")
        else:
            self.stats.setText(f"{state_zh} | {zero_zh} | 标称 {odr_value:g} Hz | 接收 {self.rate:.1f} 样本/s | 样本 {self.received} | 序号缺口 {self.gaps} | CRC/格式错误 {getattr(self,'parser_errors',0)} | 绘图 {self._plot_fps:.1f} FPS | CSV {self.record_count}")
        if self.local_hold:return
        if self.latest:
            rx,ry,ux,uy,cx,cy,wx,wy=self.latest
            ax,ay,zx,zy,flags=self.extended
            for lab,a,raw,ug,corr,angle,rel in zip(self.values,['X','Y'],[rx,ry],[ux,uy],[cx,cy],[ax,ay],[zx,zy]):
                absolute=f'{angle/1000:+.3f}°' if flags&1 and fresh else '无效/不稳定'
                relative=f'{rel/1000:+.3f}°' if (flags&3)==3 and fresh else '--'
                cal_state = self.tr('四位置校准后','4-point calibrated') if self.config.get('calibrated', 0) else self.tr('默认参数输出','Default parameters')
                lab.setText(self.tr(
                    f'{a} {cal_state}: {corr/1000:+.3f} mg\n波形基线值: {self.latest_wave_value(a):+.3f} mg   RAW: {raw}\n绝对角度: {absolute}   相对角度: {relative}'+('' if fresh else '（历史值）'),
                    f'{a} {cal_state}: {corr/1000:+.3f} mg\nWaveform: {self.latest_wave_value(a):+.3f} mg   RAW: {raw}\nAbsolute: {absolute}   Relative: {relative}'+('' if fresh else ' (stale)')
                ))
        else:
            for lab,a in zip(self.values,['X','Y']):lab.setText(self.tr(f'{a}: -- mg\nRAW: --',f'{a}: -- mg\nRAW: --'))
        # Plot at a stable ~30 FPS. Serial reception is independent; the
        # waveform uses MCU baseline-corrected wave_x/wave_y values stored in history.
        h = self.history
        if h:
            latest_t = h[-1][0]

            if now >= self._plot_next_update:
                self._plot_next_update = now + self._plot_update_period
                data = list(h)
                n = len(data)
                if n > self._plot_max_points:
                    # Min/max envelope decimation preserves short vibration
                    # peaks instead of uniformly skipping them.
                    bucket_count = max(1, self._plot_max_points // 5)
                    bucket_size = max(1, math.ceil(n / bucket_count))
                    keep = {0, n - 1}
                    for begin in range(0, n, bucket_size):
                        end = min(n, begin + bucket_size)
                        for col in (1, 2):
                            valid_idx = [i for i in range(begin, end)
                                         if math.isfinite(data[i][col])]
                            if valid_idx:
                                keep.add(min(valid_idx, key=lambda i: data[i][col]))
                                keep.add(max(valid_idx, key=lambda i: data[i][col]))
                        # Keep discontinuities visible; do not fabricate data.
                        gap_index = next((i for i in range(begin, end)
                                           if not math.isfinite(data[i][1]) or
                                           not math.isfinite(data[i][2])), None)
                        if gap_index is not None:
                            keep.add(gap_index)
                    sample = [data[i] for i in sorted(keep)]
                else:
                    sample = data

                xs = [v[0] for v in sample]
                ys = [v[1] for v in sample]  # MCU measurement.wave_ug[0], calibrated and baseline-corrected
                zs = [v[2] for v in sample]  # MCU measurement.wave_ug[1], calibrated and baseline-corrected
                self.curves[0].setData(xs, ys, skipFiniteCheck=True)
                self.curves[1].setData(xs, zs, skipFiniteCheck=True)

                self._plot_frames += 1
                if now - self._plot_fps_time >= 1.0:
                    self._plot_fps = self._plot_frames / (now - self._plot_fps_time)
                    self._plot_frames = 0
                    self._plot_fps_time = now

            # Move the viewport at the same cadence as curve data. Avoid
            # calling setXRange every 16-ms GUI timer tick.
            if now >= self._plot_next_x_update:
                self._plot_next_x_update = now + self._plot_update_period
                right = latest_t
                if self.last_data_host:
                    host_age = max(0.0, min(0.10, now - self.last_data_host))
                    odr_hz = self.config.get('millihz', 52000) / 1000.0
                    if 1.0 <= odr_hz <= 10000.0:
                        right += host_age
                if abs(right - self._plot_last_x_right) >= 0.005:
                    self.plot.setXRange(right - 10.0, right, padding=0)
                    self._plot_last_x_right = right

            # One common Y range for X/Y. Expand quickly; shrink only after
            # two seconds of consistently lower amplitude to avoid scale
            # pumping that looks like vertical waveform jumps.
            if self.range_box.currentIndex() == 0 and now - self._plot_last_y_update >= 0.20:
                cutoff = latest_t - 3.0
                peak = 0.0
                for t, vx, vy in h:
                    if t < cutoff:
                        continue
                    if math.isfinite(vx): peak = max(peak, abs(vx))
                    if math.isfinite(vy): peak = max(peak, abs(vy))
                target = 20.0
                for lim in (20, 50, 100, 200, 500, 1000, 2000, 5000,
                            10000, 20000, 50000, 100000, 200000):
                    target = float(lim)
                    if peak <= target * 0.80:
                        break

                current = self._plot_last_y
                if current <= 0.0 or target > current:
                    self.plot.setYRange(-target, target, padding=0)
                    self._plot_last_y = target
                    self._plot_shrink_since = None
                elif target < current:
                    if self._plot_shrink_since is None:
                        self._plot_shrink_since = now
                    elif now - self._plot_shrink_since >= 2.0:
                        self.plot.setYRange(-target, target, padding=0)
                        self._plot_last_y = target
                        self._plot_shrink_since = None
                else:
                    self._plot_shrink_since = None
                self._plot_last_y_update = now

    def open_calibration(self):
        if self.pending:return
        if self.cal_dialog:self.cal_dialog.show();return
        self.candidate=None;self.cal_dialog=CalibrationDialog(self);self.cal_dialog.show();self.send('CAL_START',0)
    def reset_calibration(self):
        if QtWidgets.QMessageBox.question(
            self,
            self.tr('清空四位置校准','Clear four-position calibration'),
            self.tr('将清除已保存的四位置校准参数，恢复 Offset=0、Gain=1。由于相对置零基于当前校准结果，本操作也会清除相对角度零点和波形基线；完成后如需振动基线归零，请重新执行相对置零。是否继续？',
                    'This clears the saved four-position calibration and restores Offset=0, Gain=1. Because relative zero references the calibrated coordinate system, the relative angle zero and waveform baseline will also be cleared. Apply relative zero again if you need a zero-centred vibration waveform. Continue?')
        )==QtWidgets.QMessageBox.Yes:self.send('CAL_RESET',0)
    def closeEvent(self,event):
        if self.worker:
            self.worker.stop_requested=True
            if not self.worker.wait(1500):
                self.note('正在等待串口线程退出，请稍后关闭。');event.ignore();return
        self.stop_record();event.accept()

def main():
    app=QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    w=Monitor();w.show();sys.exit(app.exec())
if __name__=='__main__':main()
