# 设备电量查看器

Windows 上读取 2.4G 无线外设电量的小工具。**纯 ctypes 调系统 DLL，零第三方依赖**——
不用 hidapi、不用 pystray、不用 Pillow、不用 pywin32，装了 Python 就能跑。

## 支持设备

| 设备 | 读取方式 |
|---|---|
| ATK / VXE 无线鼠标（`373B:1216`） | 厂商协议：usage page `0xFF05`，Report ID `0x08`，请求 `7D 72 02 00 01 07 01`，电量取回复第 7 字节 |
| DARKRIM SHADOW 耳机（`3654:6901`，杰理方案 dongle） | 逆向的私有 TLV 协议：`CRC16-CCITT-FALSE` over `帧[1:10+len]`（大端），TLV `0x01` 即电量 |
| 其它设备 | 自动回退：标准 HID 电量 usage → 厂商协议表（Endgame / VAXEE / Nordic）→ 罗技 HID++ → 手动标定 |

## 三个入口

| 文件 | 作用 |
|---|---|
| `我的设备电量.bat` | **主界面**：两张卡片显示电量，底部可调刷新间隔、开关开机自启、重建桌面链接 |
| `电量托盘.bat` | 任务栏常驻两个数字图标（鼠标 / 耳机），右键图标打开主界面 |
| `启动电量查看器.bat` | 完整调试版：列出全部 HID 设备，可转储 Feature Report、探测 Report ID、手动标定协议 |

命令行也够用：

```bash
python my_devices.py --once          # 读一次就退出
python my_devices.py --install-links # 在桌面重建软连接
python my_devices.py --autostart status
python app.py --list                 # 列出所有 HID 设备与接口
python app.py --battery              # 读取所有设备电量
```

## 环境要求

- Windows 10 / 11
- Python 3.10+（需要 `tkinter`，官方安装包默认自带）

## 目录说明

| 文件 | 说明 |
|---|---|
| `hid_win.py` | HID 底层：枚举接口、Feature Report 读写、异步 Input Report、字段解析 |
| `battery.py` | 多策略电量读取 + 厂商协议表 + 手动标定 |
| `darkrim_proto.py` | DARKRIM 杰理方案私有协议（帧构造 / CRC / TLV 解析） |
| `bt_battery.py` | 蓝牙耳机 HFP 电量（未公开 PnP 属性） |
| `my_devices.py` | 简洁主界面 |
| `tray_app.py` | 托盘程序（`Shell_NotifyIconW` + `SetTimer`，空闲几乎不占 CPU） |
| `tray_common.py` | 配置、开机自启（启动文件夹快捷方式）、进程间消息 |
| `win_icon.py` | 点阵数字 → ICO → HICON（图标就是电量数字） |
| `win_link.py` | 软连接：符号链接 / 目录 junction / 硬链接，按权限自动降级 |
| `win_shell.py` | 已知文件夹路径 + 用 ctypes COM 创建 `.lnk` |
| `app.py` | 完整调试版界面 |
| `PROMPT.md` | 把整个项目整理成一份可复用的提示词（含协议与踩坑） |

## 两个值得一提的实现细节

1. **同一 HID 句柄上并发"阻塞读 + 写"会直接杀掉进程**（连异常栈都没有）。
   正确做法是独立的 `FILE_FLAG_OVERLAPPED` 读句柄 + 事件超时 + `CancelIoEx`。
2. **销毁托盘窗口后必须 `PostQuitMessage(0)`**。只调 `DestroyWindow` 会留下
   "窗口和图标都没了、但进程还活着"的僵尸进程，它占着单实例锁，导致之后再启动都没反应。

更多坑见 `PROMPT.md`。

## 隐私

- **不联网**：代码里没有任何 http / socket / urllib / 遥测调用，所有读取都在本地 HID 层完成。
- **不写日志**：默认不产生任何日志文件；只有 `--debug` 时才往控制台打印。
- **不上传**：设备序列号、地址等信息只在内存中使用，不落盘。

## 说明

私有协议部分是通过逆向厂商软件 + 抓包分析得到的，仅供学习与个人使用。
