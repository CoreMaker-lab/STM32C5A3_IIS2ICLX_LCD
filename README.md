# COREMAKER — STM32C5A3RGT6 + IIS2ICLX Dual-Axis Tilt Monitor

**STM32C5A3RGT6 + ST IIS2ICLX | 双轴倾角监测与双轴加速度波形采集**

A dual-axis tilt monitoring and acceleration waveform demonstration based on STM32C5A3RGT6 and ST IIS2ICLX. The MCU performs sensor acquisition, offset/gain correction, tilt estimation, stability evaluation and LCD rendering. The Windows PC application provides serial control, real-time X/Y waveform visualization, calibration, relative zeroing and CSV logging.

基于 STM32C5A3RGT6 与 ST IIS2ICLX 的双轴倾角监测与加速度波形采集方案。MCU 负责传感器采集、Offset/Gain 校准、倾角估算、稳定性判断和 LCD 显示；Windows PC 上位机负责串口控制、X/Y 实时波形显示、四位置校准、相对置零及 CSV 数据记录。

---

## Screenshots / 实物运行截图
<img width="2533" height="1234" alt="image" src="https://github.com/user-attachments/assets/02d352ee-b104-4be6-9443-bd740b7606dc" />



### PC Monitor / PC 双语上位机

<img width="1476" height="1114" alt="image" src="https://github.com/user-attachments/assets/63110fac-7765-4c65-8c72-de8b0b69dbf8" />

------------------------------------------------------------------------
## 项目维护者与联系方式 \| Project Maintainer & Contact

- **Name / 姓名**: Billy
- **交流群 / Discussion Group**: 925643491
- **Email / 邮箱**: <a845656974@outlook.com>
- **Phone / 电话**: +86 15622736378


------------------------------------------------------------------------
### MCU Digital Level / MCU 数字倾角显示
![Digital level](docs/images/device_level.png)

> The screenshots show one demonstration session. The PC example is configured at ±2 g, 104 Hz and 2,000,000 baud; the displayed X/Y relative angles and receive rate are live readings, not guaranteed specifications.  
> 截图为一次实际演示状态。PC 示例配置为 ±2 g、104 Hz、2,000,000 baud；截图中的 X/Y 相对角度和接收速率为当时实时读数，不代表固定规格或精度承诺。

---

## 1. Key Features / 项目功能

### MCU Firmware / MCU 固件
- STM32C5A3RGT6 target; project configuration uses Cortex-M33 at 144 MHz.
- ST IIS2ICLX dual-axis accelerometer, SPI1 interface, data-ready interrupt with polling fallback.
- Selectable full-scale range: ±0.5 g / ±1 g / ±2 g / ±3 g.
- Selectable ODR: 12.5 / 26 / 52 / 104 / 208 / 416 / 833 Hz.
- Offset and gain correction for X/Y acceleration.
- Static / slow-motion tilt estimation using `asin(a/g)` for each sensitive axis.
- Stability and validity checks before presenting tilt as valid.
- ST7796 4.0-inch TFT LCD, landscape 480 × 320 UI.
- Digital level page and X/Y waveform page.
- K1 HOLD, K2 page switch, K3 short-press relative zero / long-press clear.

### Windows PC Application / Windows PC 上位机
- Chinese / English UI.
- COM port refresh, connect / disconnect and runtime baud-rate selection.
- Default UART rate: 2,000,000 baud, 8-N-1.
- Real-time X/Y calibrated acceleration waveform.
- Absolute and relative angle readouts, RAW counts and baseline-corrected waveform values.
- Four-position X+/X-/Y+/Y- calibration and MCU save.
- Relative zeroing for angle reference and waveform baseline.
- CSV recording with raw, corrected, waveform and angle fields.
- Sequence-gap, CRC/format, board SPI and UART transport status indicators.

---

## 2. Hardware and Interfaces / 硬件组成

| Block | Device / Interface | Description |
|---|---|---|
| MCU | STM32C5A3RGT6 | Main controller |
| Sensor | ST IIS2ICLX | Dual-axis accelerometer |
| Sensor interface | SPI1 | Sensor register/data access |
| Data-ready | PB1 EXTI | Interrupt notification; polling fallback is available |
| LCD | ST7796, 4.0-inch TFT | 480 × 320 landscape UI |
| LCD interface | SPI2 | LCD display transport |
| PC interface | USART1 + USB-UART bridge | Windows COM port; screenshot example identifies CH343 |

The board's USB-UART COM port is used for the PC application. Select the CH343/USB-serial COM port shown by Windows Device Manager; do not select an unrelated ST-Link virtual COM port.

PC 通信使用板载 USB-UART 转换接口。请在 Windows 设备管理器中选择对应 CH343 / USB 串口 COM 端口，不要误选无关的 ST-Link 虚拟串口。

---

## 3. PC Quick Start / PC 上位机快速启动

### Requirements / 环境要求
- Windows 10 / 11
- 64-bit Python 3.11 or 3.12
- Python Launcher (`py`)
- USB data cable and the board's USB-UART COM port

Dependencies are listed in `PC/requirements.txt`:
- PySide6
- pyqtgraph
- numpy
- pyserial

### Start / 启动步骤
1. Extract the complete project ZIP and keep the directory structure.
2. Open the `PC/` directory.
3. Run `start.bat`.
4. The script creates `PC/.venv`, installs dependencies and launches `app.py`.
5. Select `中文` or `English`.
6. Click **Refresh Ports**, select the board's CH343 USB-UART COM port.
7. Use **2,000,000 baud** for the initial connection, then click **Connect**.
8. Confirm the status line reports incoming samples and the board reports a healthy sensor state.

首次运行需要联网安装依赖。若启动失败，请确认已安装 64 位 Python 3.11/3.12，并且 `py` 命令可用。

---

## 4. Operating Guide / 基本操作

### Range and ODR / 量程与采样率
- Full scale: ±0.5 g, ±1 g, ±2 g, ±3 g.
- ODR: 12.5, 26, 52, 104, 208, 416, 833 Hz.
- Choose the value and click the corresponding **Set** button. A selected value is only a pending UI choice; wait for the MCU acknowledgement and verify the **Actual** configuration line.
- Higher ODR settings require sufficient UART bandwidth. The default 2 Mbaud setting is recommended when using the upper ODR ranges.

### Four-position Calibration / 四位置校准
1. Connect the board and open **Four-position Calibration**.
2. The firmware temporarily uses ±2 g and 52 Hz for calibration.
3. Capture X+, X-, Y+, Y- in sequence. The target axis should be near +1 g or −1 g; the other axis should be near 0 g (approximately within ±0.15 g).
4. Keep the sensor still during each capture. Each face requires 156 stable samples (about 3 seconds at 52 Hz).
5. When all four faces are complete, review the calculated Offset/Gain and click **Apply and Save to MCU**.
6. After success or cancellation, the firmware attempts to restore the previous range and ODR.

四位置校准用于修正 X/Y 轴 Offset 与 Gain，不等同于相对置零。校准开始时会清除原相对置零参考；校准完成后如需相对角度和波形归零，请重新执行相对置零。

### Relative Zero / 相对置零
- Place the sensor in the desired reference position and wait for valid, stable angle readings.
- Click **Relative Zero (Tilt + Waveform)**. The current angle becomes the relative 0° reference and the current static acceleration is stored as the waveform baseline.
- **Cancel Relative Zero** restores absolute-angle presentation and the un-zeroed waveform.
- On the board: K3 short press requests zeroing; K3 long press (about 0.8 s) clears the relative zero.

### LCD Keys / LCD 按键
| Key | Action |
|---|---|
| K1 short press | Toggle board LCD HOLD / LIVE |
| K2 short press | Switch Digital Level / Waveform page |
| K3 short press | Set relative zero; if not yet stable, firmware waits up to about 3 s |
| K3 long press | Clear relative zero |

The level screen shows a ±0.5° status band, 1° ring spacing and a ±5° bubble view. These are UI display settings, not a guaranteed accuracy specification.

倾角页显示 ±0.5° 状态带、1° 圆环间隔和 ±5° 气泡视图。这些是界面显示参数，不是整机精度保证。

---

## 5. CSV Data / CSV 数据字段

The PC application writes UTF-8-BOM CSV files. Main fields include:

| Field | Meaning |
|---|---|
| `host_utc` | PC UTC timestamp |
| `session_segment` | Session / reboot segment |
| `sequence` | MCU packet sequence |
| `mcu_tick_ms` | MCU millisecond tick |
| `raw_x`, `raw_y` | Raw sensor counts |
| `x_ug`, `y_ug` / `x_mg`, `y_mg` | Converted acceleration before calibration |
| `corrected_x_ug`, `corrected_y_ug` | Offset/Gain corrected acceleration |
| `wave_x_ug`, `wave_y_ug` | Acceleration after waveform-baseline subtraction |
| `absolute_x_deg`, `absolute_y_deg` | Absolute tilt, when valid |
| `relative_x_deg`, `relative_y_deg` | Relative tilt, when zeroed and valid |
| `flags` | Validity, stability, calibration-session and zero-baseline flags |
| `fs_mg` | Full-scale setting |
| `odr_code` | ODR enumeration |
| `config_epoch` | Configuration generation |

Invalid angle fields may be blank by design. Do not interpolate them as if they were valid measurements.

`flags` bit definitions: bit 0 = absolute angle valid; bit 1 = relative-zero mode enabled; bit 2 = angle estimate valid; bit 3 = stability check passed; bit 4 = calibration session active; bit 5 = waveform baseline zero active. `odr_code` mapping: 1=12.5 Hz, 2=26 Hz, 3=52 Hz, 4=104 Hz, 5=208 Hz, 6=416 Hz, 7=833 Hz.

角度无效或不稳定时，CSV 对应角度字段可能留空，这是有意保留的无效状态，不应自动填补成有效测量值。

---

## 6. Measurement Limits / 测量边界

- Tilt is estimated from accelerometer gravity components using `asin(a/g)` on each sensitive axis; it is intended for stationary or slowly changing conditions.
- This is not a full 3D attitude solution and does not use gyroscope fusion.
- Constant linear acceleration cannot be distinguished from gravity by the accelerometer alone.
- Strong vibration, shock, rapid motion, saturation or unsuitable sensor orientation can invalidate or bias the tilt estimate.
- The ±0.5° band shown on the LCD is a display/status threshold, not an accuracy claim. Validate system accuracy on a calibrated angle fixture over the intended temperature and vibration range.

本方案基于加速度计敏感轴分量估算倾角，不是完整三维姿态解算；持续线性加速度、强振动、冲击和快速运动都可能使角度估算失真。±0.5° 是 LCD 状态显示带，不代表整机精度指标。

---

## 7. Troubleshooting / 常见问题

| Symptom | Checks |
|---|---|
| No COM port | Check USB data cable, board power, CH343 driver and the correct USB-UART connector; refresh ports. |
| Connected but no samples | Verify the COM port and baud rate; start with 2,000,000 baud. After an MCU reset, use the firmware default baud rate. |
| Angle invalid / moving | Keep the sensor still; check sensor orientation, range saturation and external acceleration. |
| Calibration progress resets | Verify X+/X-/Y+/Y- orientation, target ±1 g, cross-axis near 0 g and no movement. |
| Relative zero rejected | Wait for valid/stable readings; check NVM/Flash status and make sure calibration mode is not active. |
| CRC errors or sequence gaps | Check baud rate and cable; reduce ODR for comparison; retain CSV and status screenshots. |
| Waveform not centred at 0 mg | Execute Relative Zero; four-position calibration alone does not zero the waveform baseline. |

---

## 8. Project Structure / 工程目录

```text
Project/
├── PC/
│   ├── app.py
│   ├── calibration_ui.py
│   ├── protocol.py
│   ├── requirements.txt
│   ├── start.bat
│   └── test_protocol.py
└── STM32C5A3_IIS2ICLX_cmake/
    ├── main.c / main.h
    ├── sensor_app.c / sensor_app.h
    ├── measurement.c / measurement.h
    ├── lcd_ui.c / lcd_ui.h
    ├── st7796.c / st7796.h
    ├── keys.c / keys.h
    ├── iis2iclx_reg.c / iis2iclx_reg.h
    ├── cal_store.inc
    ├── uart_transport.inc
    ├── generated/
    ├── stm32c5xx_dfp/
    ├── stm32c5xx_drivers/
    └── cmake/
```

### Firmware Build Notes / 固件编译说明
The firmware folder is a CMake project targeting `STM32C5A3RGT6`, Cortex-M33, with the supplied GCC 14.3.1 toolchain configuration. The toolchain expects `arm-none-eabi-gcc` and related tools to be available in `PATH`. Use the project-provided CMake build configuration; verify the selected build type is `debug_GCC_STM32C5A3RGT6` and the target device matches the board before flashing.

固件目录为 CMake 工程，目标器件为 STM32C5A3RGT6，工程配置使用 Cortex-M33 与 GCC 14.3.1 工具链。编译环境需要将 `arm-none-eabi-gcc` 等工具加入 PATH。请使用工程自带 CMake 配置，并确认 Build Type 为 `debug_GCC_STM32C5A3RGT6`、目标器件与实际板卡一致后再下载。

---

## 9. Protocol and Verification / 协议与验证

- PC/MCU transport uses V2 framed ASCII payloads with CRC32 validation.
- PC protocol unit tests included in `PC/test_protocol.py`.
- Verification performed for this documentation release: **9 protocol unit tests passed**.
- This test result verifies the PC protocol parser tests only; it does not replace full hardware, accuracy, environmental or long-duration validation.

PC/MCU 使用带 CRC32 校验的 V2 帧协议。当前工程内 `PC/test_protocol.py` 的 9 项协议单元测试已通过；该结果仅代表 PC 协议解析测试通过，不替代硬件功能、精度、环境适应性或长期运行验证。

---

## License / 许可

No standalone project-level LICENSE file is included in the supplied project. Third-party ST/CMSIS components retain their respective licenses. Add a project license and review third-party terms before redistributing or using the project commercially.

当前工程未附独立的项目级 LICENSE 文件。ST/CMSIS 等第三方组件保留各自许可；如需公开分发或商业使用，请先核实第三方许可并为项目补充明确的 License。

---

**COREMAKER — Shenzhen Xintu Chuangke Electronic Technology Co., Ltd.**
