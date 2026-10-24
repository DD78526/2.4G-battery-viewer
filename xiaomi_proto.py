# -*- coding: utf-8 -*-
"""xiaomi_proto.py —— 小米（Xiaomi, VID 0x2717）2.4G 无线鼠标电量读取

现状（实话实说）
----------------
查遍了公开资料，**没有找到小米 2.4G 接收器的电量协议**：
  * Linux 内核 drivers/hid/hid-xiaomi.c 只修正了 Silent Mouse（蓝牙，2717:5014）的侧键描述符，
    不涉及电量；
  * libratbag / piper 不支持小米鼠标（libratbag issue #1800：Mouse X1 2717:50A6）；
  * linux-hardware.org 等硬件库只有 VID/PID 和描述符，没有电量相关的厂商命令。

所以这里 **不编造厂商私有字节**，只做有依据的两件事：

1. 标准 HID 电量字段（USB HID Usage Tables）：
     Generic Device Controls 0x06 / Battery Strength 0x20
     Battery System 0x85 / Absolute(0x01) / Relative(0x66) State of Charge、Battery Level(0x65)
   接收器如果在报告描述符里声明了这些字段，就直接读 Feature Report，
   或者在非系统独占的集合上监听 Input Report 里的这个字段。
   （故意不用 0x06/0x29 RF Signal Strength —— 那是信号强度，不是电量。）

2. 用户自己标定的协议（protocols_user.json，在 app.py 里“手动标定”生成，VID=2717）。
   如果你抓到了自己这款鼠标的电量报文，标定一次以后这里就能读。

已知的小米 VID 0x2717 2.4G 设备（来源：linux-hardware.org / usb.ids / libratbag #1800）：
    5091 / 5094  Mi USB Receiver（小米无线鼠标 / 便携鼠标的接收器）
    500B         Mi Gaming Mouse 接收器（Telink 方案）
    5013 / 5017  Mi Wireless Mouse
    50A6         Mouse X1
都不保证声明了标准电量字段；读不到时界面会明确提示“该型号未公开电量协议”。
"""

from __future__ import annotations

import time
from typing import Optional

from hid_common import DeviceBattery

VID = 0x2717

KNOWN_MODELS = {
    0x5091: "小米 USB 接收器（Mi USB Receiver）",
    0x5094: "小米 USB 接收器（Mi USB Receiver）",
    0x500B: "小米游戏鼠标接收器",
    0x5013: "小米无线鼠标",
    0x5017: "小米无线鼠标",
    0x50A6: "小米鼠标 X1",
}

# (UsagePage, Usage, 说明) —— 只要真正的电量字段
BATTERY_USAGES = [
    (0x0006, 0x0020, "Battery Strength"),
    (0x0085, 0x0001, "Absolute State of Charge"),
    (0x0085, 0x0066, "Relative State of Charge"),
    (0x0085, 0x0065, "Battery Level"),
]

SYSTEM_RESERVED = {(0x0001, 0x0001), (0x0001, 0x0002), (0x0001, 0x0006), (0x0001, 0x0007)}

UNSUPPORTED_HINT = ("该型号未公开电量协议，接收器也没有声明标准 HID 电量字段。"
                    "可以用 app.py 抓包后“手动标定”，之后就能读。")


def model_name(pid: int) -> str:
    return KNOWN_MODELS.get(pid, f"小米设备 2717:{pid:04X}")


def scale(value: int, logical_max: int) -> int:
    if logical_max and logical_max > 0 and logical_max != 100:
        return max(0, min(100, round(value * 100 / logical_max)))
    return max(0, min(100, value))


def match_usage(cap) -> Optional[str]:
    key = (cap.UsagePage, cap.u.NotRange.Usage)
    for page, usage, name in BATTERY_USAGES:
        if key == (page, usage):
            return name
    return None


def _feature_battery(iface, diag: list) -> Optional[DeviceBattery]:
    if not iface.feature_len:
        return None
    from hid_win import HidDevice, HidP_Feature
    with HidDevice(iface.path, write=False) as dev:
        for cap in dev.value_caps(HidP_Feature):
            name = match_usage(cap)
            if not name:
                continue
            report = dev.get_feature_report(cap.ReportID)
            value = dev.usage_value(HidP_Feature, report, cap)
            diag.append(f"  Feature {name} id=0x{cap.ReportID:02X} 值={value} 上限={cap.LogicalMax}")
            if value is None:
                continue
            return DeviceBattery(found=True, online=True, level=scale(value, cap.LogicalMax),
                                 detail=f"标准 HID 电量字段（{name}）")
    return None


def _input_battery(iface, diag: list, seconds: float) -> Optional[DeviceBattery]:
    if not iface.input_len or (iface.usage_page, iface.usage) in SYSTEM_RESERVED:
        return None
    from hid_win import HidDevice, HidP_Input
    with HidDevice(iface.path, write=False) as dev:
        caps = [(c, match_usage(c)) for c in dev.value_caps(HidP_Input)]
        caps = [(c, n) for c, n in caps if n]
        if not caps:
            return None
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            report = dev.read_input(timeout_ms=200)
            if not report:
                continue
            for cap, name in caps:
                if report[0] != cap.ReportID and cap.ReportID:
                    continue
                value = dev.usage_value(HidP_Input, report, cap)
                if value is None:
                    continue
                diag.append(f"  Input {name} id=0x{cap.ReportID:02X} 值={value}")
                return DeviceBattery(found=True, online=True, level=scale(value, cap.LogicalMax),
                                     detail=f"标准 HID 电量字段（{name}，输入报告）")
        diag.append(f"  {iface.describe_usage()} 声明了电量字段，但 {seconds:.1f}s 内没有上报"
                    "（鼠标可能在休眠，动一下再试）")
    return None


def _user_protocol(iface, diag: list) -> Optional[DeviceBattery]:
    try:
        import battery as bt
    except Exception:            # pragma: no cover
        return None
    if not any(s.vid == VID for s in bt.load_user_protocols()):
        return None
    res = bt.strategy_vendor_protocol(iface)
    if res is None:
        return None
    diag.append(f"  用户标定协议：{res.source} {res.detail}")
    if res.ok and res.level is not None:
        chg = True if res.status in ("charging",) else (None if res.status == "unknown" else False)
        return DeviceBattery(found=True, online=True, level=res.level, charging=chg,
                             detail=f"用户标定协议（{res.source}）")
    return None


def read_battery(all_ifaces: Optional[list] = None, listen_seconds: float = 1.5) -> DeviceBattery:
    if all_ifaces is None:
        from hid_win import enumerate_hid
        all_ifaces = enumerate_hid()
    mine = [i for i in all_ifaces if i.vid == VID]
    if not mine:
        return DeviceBattery(found=False, vid=VID, detail="没找到小米 2.4G 接收器（VID 2717）")
    pid = sorted({i.pid for i in mine}, key=lambda p: (p not in KNOWN_MODELS, p))[0]
    diag: list = [f"[Xiaomi] {', '.join(sorted({i.vid_pid for i in mine}))}"]
    errors = []
    for step in (_feature_battery, _user_protocol,
                 lambda i, d: _input_battery(i, d, listen_seconds)):
        for iface in mine:
            try:
                res = step(iface, diag)
            except OSError as e:
                errors.append(str(e))
                continue
            if res is not None:
                res.vid, res.pid = iface.vid, iface.pid
                res.model = model_name(iface.pid)
                res.diag = diag
                return res
    detail = UNSUPPORTED_HINT
    if errors:
        detail += f"（部分接口打开失败：{errors[0]}）"
    return DeviceBattery(found=True, vid=VID, pid=pid, model=model_name(pid),
                         detail=detail, diag=diag)


if __name__ == "__main__":
    r = read_battery()
    print(r.model, r.level, r.detail)
    print("\n".join(r.diag))
