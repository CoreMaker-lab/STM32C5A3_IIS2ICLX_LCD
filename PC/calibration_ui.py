from PySide6 import QtCore, QtWidgets

class CalibrationDialog(QtWidgets.QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner=owner;self.session_seen=False;self.setWindowTitle('X/Y 四位置校准')
        self.resize(650,460)
        layout=QtWidgets.QVBoxLayout(self)
        intro=QtWidgets.QLabel('按传感器坐标轴依次摆放 X+、X−、Y+、Y−。\n目标轴接近 +1 g 或 −1 g，另一轴接近 0 g。\n每次固定后点击对应采集按钮，连续稳定约 3 秒；晃动会重新计时。\n校准期间自动使用 ±2 g、52 Hz。相对置零不会代替校准。')
        intro.setWordWrap(True);layout.addWidget(intro)
        self.live=QtWidgets.QLabel('等待数据');layout.addWidget(self.live)
        self.buttons=[];self.labels=[]
        for i,name in enumerate(['X+','X−','Y+','Y−']):
            row=QtWidgets.QHBoxLayout();layout.addLayout(row)
            label=QtWidgets.QLabel(name+'：未采集');self.labels.append(label);row.addWidget(label)
            btn=QtWidgets.QPushButton('采集 '+name);btn.clicked.connect(lambda checked=False,f=i:owner.send('CAL_FACE',f))
            btn.setEnabled(False);row.addWidget(btn);self.buttons.append(btn)
        self.progress=QtWidgets.QProgressBar();self.progress.setRange(0,156);layout.addWidget(self.progress)
        self.state=QtWidgets.QLabel('正在请求进入校准模式…');self.state.setWordWrap(True);layout.addWidget(self.state)
        self.apply=QtWidgets.QPushButton('应用并保存到 MCU');self.apply.setEnabled(False)
        self.apply.clicked.connect(self.save);layout.addWidget(self.apply)
        cancel=QtWidgets.QPushButton('退出 / 取消');cancel.clicked.connect(self.close);layout.addWidget(cancel)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(100)
        self.apply_language()
    def apply_language(self):
        en = self.owner.lang == 'en'
        self.setWindowTitle('X/Y Four-position Calibration' if en else 'X/Y 四位置校准')
        intro = ('Place the sensor along X+, X−, Y+, Y− in sequence.\n'
                 'Target axis should be near +1 g or −1 g; the other axis near 0 g.\n'
                 'After fixing each position, click its Capture button and remain stable for about 3 seconds; movement restarts the timer.\n'
                 'Calibration temporarily uses ±2 g and 52 Hz. Relative zero does not replace calibration.'
                 if en else
                 '按传感器坐标轴依次摆放 X+、X−、Y+、Y−。\n目标轴接近 +1 g 或 −1 g，另一轴接近 0 g。\n每次固定后点击对应采集按钮，连续稳定约 3 秒；晃动会重新计时。\n校准期间自动使用 ±2 g、52 Hz。相对置零不会代替校准。')
        self.findChild(QtWidgets.QLabel).setText(intro)
        if en:
            self.apply.setText('Apply and Save to MCU')
        else:
            self.apply.setText('应用并保存到 MCU')
        # The last layout widget is the cancel button.
        cancel = self.findChildren(QtWidgets.QPushButton)[-1]
        cancel.setText('Exit / Cancel' if en else '退出 / 取消')

    def save(self):
        if QtWidgets.QMessageBox.question(self,'Save calibration' if self.owner.lang=='en' else '保存校准','Write the new calibration to the MCU and replace the existing calibration?' if self.owner.lang=='en' else '将新校准参数写入 MCU，并替换原校准。是否继续？')==QtWidgets.QMessageBox.Yes:
            self.owner.send('CAL_APPLY',0)
    def refresh(self):
        o=self.owner;c=o.config;en=o.lang=='en'
        if o.latest:
            live=(f'Uncalibrated X={o.latest[2]/1000:+.3f} mg  Y={o.latest[3]/1000:+.3f} mg\n'
                  f'Calibrated X={o.latest[4]/1000:+.3f} mg  Y={o.latest[5]/1000:+.3f}'
                  if en else
                  f'未校准 X={o.latest[2]/1000:+.3f} mg  Y={o.latest[3]/1000:+.3f} mg\n'
                  f'校准后 X={o.latest[4]/1000:+.3f} mg  Y={o.latest[5]/1000:+.3f} mg')
            self.live.setText(live)
        if not c:
            for b in self.buttons:b.setEnabled(False)
            self.apply.setEnabled(False)
            self.state.setText('Not connected or waiting for MCU configuration.' if en else '未连接或尚未收到 MCU 配置。')
            return
        session,mask,face,count,nvm=c['session'],c['mask'],c['face'],c['count'],c['nvm']
        if session:self.session_seen=True
        names=['X+','X−','Y+','Y−']
        for i,(b,l) in enumerate(zip(self.buttons,self.labels)):
            b.setEnabled(bool(session) and face<0 and not o.pending)
            state=('Complete' if mask&(1<<i) else ('Capturing' if face==i else 'Not captured')) if en else ('完成' if mask&(1<<i) else ('采集中' if face==i else '未采集'))
            l.setText(names[i]+(': ' if en else '：')+state)
            b.setText(('Capture ' if en else '采集 ')+names[i])
        self.progress.setValue(count if face>=0 else (156 if mask else 0))
        self.apply.setEnabled(bool(session) and mask==15 and nvm==0 and not o.pending)
        if not session:
            if en:
                self.state.setText('Calibration mode exited.' if self.session_seen else 'Waiting for MCU to enter calibration mode; close and retry if the command fails.')
            else:
                self.state.setText('已退出校准模式。' if self.session_seen else '等待 MCU 进入校准模式；若命令失败，请关闭后重试。')
        elif nvm!=0:
            self.state.setText((f'Flash unavailable ({nvm}); capture is allowed but saving is disabled. Check EDATA, HAL FLASH and NMI configuration.'
                                if en else f'Flash 不可用（{nvm}），可采集但不能应用保存。检查 EDATA、HAL FLASH 和 NMI 配置。'))
        elif mask==15:
            c=o.candidate
            if en:
                summary=(f'Four-position capture complete.\nOffset: X={c[0]/1000:+.3f} mg, Y={c[1]/1000:+.3f} mg\nGain: X={c[2]/1e6:.6f}, Y={c[3]/1e6:.6f}\n'
                         if c else 'Four-position capture complete.\n')
                self.state.setText(summary+'Click Apply and Save to write to the MCU; close to cancel.')
            else:
                summary=(f'四位置采集完成。\n偏置：X={c[0]/1000:+.3f} mg，Y={c[1]/1000:+.3f} mg\n增益：X={c[2]/1e6:.6f}，Y={c[3]/1e6:.6f}\n'
                         if c else '四位置采集完成。\n')
                self.state.setText(summary+'点击应用并保存写入 MCU；关闭则取消。')
        elif face>=0:
            self.state.setText((f'Capturing: {count}/156. Repeated progress resets indicate wrong orientation or instability.'
                                if en else f'正在采集：{count}/156。进度反复归零表示方向不符或不稳定。'))
        else:
            self.state.setText('Select the next orientation to capture.' if en else '选择下一个方向进行采集。')
    def closeEvent(self,event):
        if self.owner.config.get('session'):
            if self.owner.pending:
                QtWidgets.QMessageBox.information(self,'Waiting for response' if self.owner.lang=='en' else '等待应答','Wait for the current command to complete before exiting.' if self.owner.lang=='en' else '请等待当前命令完成后退出。');event.ignore();return
            self.owner.send('CAL_CANCEL',0)
        self.timer.stop();self.owner.cal_dialog=None;event.accept()
