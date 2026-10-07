"""定时清理：跨平台安装/卸载定时任务。

- macOS：launchd（~/Library/LaunchAgents/com.wechatsweeper.cleaner.plist）
- Linux：crontab（追加一行）
- Windows：计划任务（schtasks）

仅生成"以 dry-run=false、按当前用户配置执行清理"的命令，
用户可先 ``--dry-run`` 验证后再启用。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from wechat_sweeper.utils import current_platform

LABEL = "com.wechatsweeper.cleaner"


def _exe_command() -> str:
    """返回执行清理的命令字符串。"""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return f'"{exe}" clean --yes'
    # 找可执行入口
    exe = shutil.which("wechat-sweeper") or shutil.which("wxs")
    if exe:
        return f'"{exe}" clean --yes'
    return f'"{sys.executable}" -m wechat_sweeper clean --yes'


@dataclass
class ScheduleResult:
    ok: bool
    message: str
    detail: str = ""


def install(interval_hours: int, platform: Optional[str] = None) -> ScheduleResult:
    plat = platform or current_platform()
    if plat == "macos":
        return _install_launchd(interval_hours)
    if plat == "windows":
        return _install_schtasks(interval_hours)
    return _install_cron(interval_hours)


def uninstall(platform: Optional[str] = None) -> ScheduleResult:
    plat = platform or current_platform()
    if plat == "macos":
        return _uninstall_launchd()
    if plat == "windows":
        return _uninstall_schtasks()
    return _uninstall_cron()


def status(platform: Optional[str] = None) -> str:
    plat = platform or current_platform()
    if plat == "macos":
        plist = Path.home() / f"Library/LaunchAgents/{LABEL}.plist"
        if plist.exists():
            return f"已安装：{plist}（重启后或 launchctl load 生效）"
        return "未安装"
    if plat == "windows":
        try:
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", "WeChatSweeper"],
                capture_output=True, text=True,
            )
            return "已安装" if r.returncode == 0 else "未安装"
        except Exception:
            return "无法查询"
    return _cron_status()


# ---------------------------------------------------------------------------

def _install_launchd(interval_hours: int) -> ScheduleResult:
    cmd = _exe_command()
    interval_seconds = max(1, int(interval_hours)) * 3600
    plist_path = Path.home() / f"Library/LaunchAgents/{LABEL}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>{cmd}</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/wechatsweeper.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/wechatsweeper.err</string>
</dict>
</plist>
"""
    plist_path.write_text(plist, encoding="utf-8")
    # 尝试加载
    try:
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True, text=True,
        )
        return ScheduleResult(True, f"已安装定时清理任务（每 {interval_hours} 小时）",
                              str(plist_path))
    except Exception as e:
        return ScheduleResult(True, f"已写入 {plist_path}，但 launchctl 加载失败：{e}",
                              str(plist_path))


def _uninstall_launchd() -> ScheduleResult:
    plist_path = Path.home() / f"Library/LaunchAgents/{LABEL}.plist"
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)],
                       capture_output=True, text=True)
        plist_path.unlink()
        return ScheduleResult(True, "已卸载定时清理任务")
    return ScheduleResult(False, "未找到已安装的定时任务")


def _install_cron(interval_hours: int) -> ScheduleResult:
    cmd = _exe_command()
    hours = max(1, int(interval_hours))
    line = f"0 */{hours} * * * {cmd} >> /tmp/wechatsweeper.log 2>&1"
    # 读取现有 crontab，去重
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except Exception:
        existing = ""
    lines = [l for l in existing.splitlines() if LABEL not in l and "wechat-sweeper" not in l]
    lines.append(f"# WeChatSweeper ({LABEL})")
    lines.append(line)
    new_cron = "\n".join(lines) + "\n"
    proc = subprocess.run(["crontab", "-"], input=new_cron, capture_output=True, text=True)
    if proc.returncode == 0:
        return ScheduleResult(True, f"已安装 cron 定时清理任务（每 {hours} 小时）", line)
    return ScheduleResult(False, f"crontab 写入失败：{proc.stderr}", line)


def _uninstall_cron() -> ScheduleResult:
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except Exception:
        return ScheduleResult(False, "无法读取 crontab")
    lines = [l for l in existing.splitlines()
             if LABEL not in l and "wechat-sweeper" not in l]
    proc = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n",
                          capture_output=True, text=True)
    return ScheduleResult(proc.returncode == 0,
                          "已卸载 cron 定时任务" if proc.returncode == 0 else "卸载失败")


def _cron_status() -> str:
    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        return "已安装" if "wechat-sweeper" in existing else "未安装"
    except Exception:
        return "无法查询"


def _install_schtasks(interval_hours: int) -> ScheduleResult:
    cmd = _exe_command()
    hours = max(1, int(interval_hours))
    proc = subprocess.run(
        ["schtasks", "/Create", "/TN", "WeChatSweeper",
         "/TR", cmd, "/SC", "HOURLY", "/MO", str(hours), "/F"],
        capture_output=True, text=True,
    )
    if proc.returncode == 0:
        return ScheduleResult(True, f"已安装计划任务（每 {hours} 小时）")
    return ScheduleResult(False, f"计划任务创建失败：{proc.stderr}")


def _uninstall_schtasks() -> ScheduleResult:
    proc = subprocess.run(
        ["schtasks", "/Delete", "/TN", "WeChatSweeper", "/F"],
        capture_output=True, text=True,
    )
    return ScheduleResult(proc.returncode == 0,
                          "已卸载计划任务" if proc.returncode == 0 else "未找到计划任务")
