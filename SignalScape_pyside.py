# -*- coding: utf-8 -*-
"""
SignalScape - TDMS数据可视化分析工具 (PySide2 版本)
由 wxPython 版本转换而来，界面经现代美化处理
"""

import sys
import threading
import warnings
import os
import os.path as osp
import csv
import fnmatch
import re
from collections import OrderedDict
import gc

import numpy as np
from nptdms import TdmsFile

# 强制控制台和环境使用 UTF-8（打包后 stdin/stdout/stderr 可能为 None，需判空）
if sys.platform == 'win32':
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if _s is not None:
            try:
                _s.reconfigure(encoding='utf-8', errors='ignore')
            except Exception:
                pass
    os.environ['PYTHONUTF8'] = '1'

from PySide2.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QLineEdit, QTextEdit, QCheckBox,
    QRadioButton, QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTreeWidget, QTreeWidgetItem, QListWidget, QListWidgetItem,
    QProgressBar, QSplitter, QFrame, QMessageBox, QFileDialog, QInputDialog,
    QToolBar, QToolButton, QStatusBar, QMenu, QButtonGroup, QStyle,
    QStyledItemDelegate, QAbstractItemView, QTableView,
    QAction, QShortcut, QSizePolicy, QGraphicsDropShadowEffect, QScrollArea,
)
from PySide2.QtGui import (
    QColor, QFont, QIcon, QPainter, QPen, QBrush,
    QKeySequence,
    QCursor, Qt,
)
from PySide2.QtCore import (
    QTimer, QPoint, QRect, QSize, Signal, Slot, QObject,
)

warnings.filterwarnings("ignore")
os.environ['PIL_WARNINGS'] = '0'

import matplotlib as mpl
import matplotlib.font_manager as fm
mpl.use('Qt5Agg')

# 注册系统中文字体，确保绘图区中文正常显示。
# 说明：Arial 等西文字体不含中文字形，单独作为首选会导致中文显示为方框；
# 因此显式注册系统中文字体并置于字体列表首位，中文/英文均可正常渲染。
_CJK_FONT_PATHS = [
    os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Fonts", "msyh.ttc"),
    os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Fonts", "simhei.ttf"),
    os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "Fonts", "simsun.ttc"),
]
_cjk_name = None
for _fp in _CJK_FONT_PATHS:
    if os.path.exists(_fp):
        try:
            fm.fontManager.addfont(_fp)
            _cjk_name = fm.FontProperties(fname=_fp).get_name()
            break
        except Exception:
            continue

mpl.rcParams.update({
    'path.simplify': True,
    'path.simplify_threshold': 1.0,
    'agg.path.chunksize': 10000,
    'font.sans-serif': ([_cjk_name] + ['Microsoft YaHei', 'SimHei', 'Arial', 'DejaVu Sans']
                        if _cjk_name else
                        ['Microsoft YaHei', 'SimHei', 'Arial', 'DejaVu Sans']),
    'axes.unicode_minus': False,
    'font.size': 9
})
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector


# =============================================================================
# 全局主题样式表
# =============================================================================
STYLESHEET = """
QMainWindow, QDialog { background-color: #f0f2f5; }
QWidget {
    font-family: "Segoe UI", "DejaVu Sans", "Arial", "Microsoft YaHei", "微软雅黑", "SimHei", sans-serif;
    font-size: 13px; color: #2d3436;
}
QPushButton {
    background-color: transparent; color: #4a5568; border: 1px solid #c4cbd8;
    border-radius: 5px; padding: 5px 14px; font-weight: 500; min-height: 24px;
    font-size: 12px;
}
QPushButton:hover { background-color: #e8f0fe; color: #4a6cf7; border-color: #4a6cf7; }
QPushButton:pressed { background-color: #d0e0fd; color: #4a6cf7; border-color: #4a6cf7; }
QPushButton:disabled { background-color: #f0f2f5; color: #b0b8c8; border-color: #e0e4ea; }
QPushButton#secondary { background-color: #e2e8f0; color: #4a5568; border: 1px solid #c4cbd8; }
QPushButton#secondary:hover { background-color: #e8f0fe; color: #4a6cf7; border-color: #4a6cf7; }
/* 弹出对话框（系统文件对话框除外，其由 Windows 绘制）按钮统一为浅灰 + 默认轮廓风格 */
QDialog QPushButton {
    background-color: #e2e8f0; color: #4a5568; border: 1px solid #c4cbd8;
    border-radius: 5px; padding: 5px 14px; font-weight: 500; min-height: 24px;
    font-size: 12px;
}
QDialog QPushButton:hover { background-color: #e8f0fe; color: #4a6cf7; border-color: #4a6cf7; }
QDialog QPushButton:pressed { background-color: #d0e0fd; color: #4a6cf7; border-color: #4a6cf7; }
QDialog QPushButton:disabled { background-color: #f0f2f5; color: #b0b8c8; border-color: #e0e4ea; }
QToolBar {
    background-color: #ffffff; border-bottom: 1px solid #e0e4ea;
    padding: 1px 4px; spacing: 2px;
}
QToolButton {
    background: transparent; border: 1px solid #c4cbd8;
    border-radius: 3px; padding: 2px 8px; color: #4a5568; font-size: 12px;
    font-family: "SimSun", "宋体";
}
QToolBar QPushButton {
    font-family: "SimSun", "宋体";
}
QToolButton:hover { background-color: #e8f0fe; border-color: #4a6cf7; color: #4a6cf7; }
QToolButton:pressed { background-color: #d0e0fd; border-color: #4a6cf7; color: #4a6cf7; }
QToolButton:checked { background-color: #e8f0fe; border-color: #4a6cf7; color: #4a6cf7; }
QLineEdit, QTextEdit, QSpinBox {
    border: 1px solid #d1d5db; border-radius: 6px; padding: 5px 10px;
    background-color: #ffffff; selection-background-color: #4a6cf7;
}
QLineEdit:focus, QTextEdit:focus, QSpinBox:focus { border-color: #4a6cf7; }
QLineEdit:disabled, QTextEdit:disabled { background-color: #f3f4f6; color: #9ca3af; }
QCheckBox { spacing: 8px; color: #4a5568; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 2px solid #c4cbd8; }
QCheckBox::indicator:checked { background-color: #4a6cf7; border-color: #4a6cf7; }
QCheckBox::indicator:hover { border-color: #4a6cf7; }
QRadioButton { spacing: 8px; color: #4a5568; }
QRadioButton::indicator { width: 18px; height: 18px; border-radius: 10px; border: 2px solid #c4cbd8; }
QRadioButton::indicator:checked { background-color: #4a6cf7; border-color: #4a6cf7; }
QProgressBar {
    border: none; border-radius: 6px; background-color: #e8ecf1;
    height: 20px; text-align: center; font-size: 12px; color: #4a5568;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4a6cf7, stop:1 #6c8ffa); border-radius: 6px;
}
QTableWidget {
    background-color: #ffffff; alternate-background-color: #f8f9fb;
    gridline-color: #e8ecf1; border: 1px solid #e0e4ea; border-radius: 8px;
    selection-background-color: #e8f0fe; selection-color: #2d3436; outline: none;
}
QTableWidget::item, QTableView::item { padding: 1px 4px; outline: none; }
QTableWidget::item:hover, QTableView::item:hover { background-color: #f0f4ff; }
QTableWidget::item:focus, QTableView::item:focus { outline: none; border: none; }
QHeaderView::section {
    background-color: #f0f2f5; color: #4a5568; font-weight: 600;
    font-size: 12px; padding: 3px 6px; border: none;
    border-right: 1px solid #e0e4ea; border-bottom: 1px solid #e0e4ea;
}
QHeaderView::section:hover { background-color: #e4e8ee; }
QTreeWidget {
    background-color: #ffffff; border: 1px solid #e0e4ea;
    border-radius: 8px; padding: 2px; outline: none;
}
QTreeWidget::item { padding: 1px 4px; min-height: 18px; }
QTreeWidget::item:hover { background-color: #f0f4ff; }
QTreeWidget::item:selected { background-color: #e8f0fe; color: #2d3436; }
QListWidget {
    background-color: #ffffff; border: 1px solid #e0e4ea;
    border-radius: 8px; outline: none;
}
QListWidget::item { padding: 6px 8px; border-radius: 4px; }
QListWidget::item:hover { background-color: #f0f4ff; }
QListWidget::item:selected { background-color: #e8f0fe; color: #2d3436; }
QLabel { color: #4a5568; }
QLabel#title { font-size: 15px; font-weight: 600; color: #2d3436; }
QSplitter::handle { background-color: #e0e4ea; }
QSplitter::handle:horizontal { width: 2px; }
QSplitter::handle:vertical { height: 2px; }
QSplitter::handle:hover { background-color: #4a6cf7; }
QStatusBar {
    background-color: #ffffff; border-top: 1px solid #e0e4ea;
    color: #718096; font-size: 12px; padding: 2px 10px;
}
QScrollBar:vertical { background-color: #f0f2f5; width: 10px; border-radius: 5px; margin: 0; }
QScrollBar::handle:vertical { background-color: #c4cbd8; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background-color: #a0aec0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background-color: #f0f2f5; height: 10px; border-radius: 5px; }
QScrollBar::handle:horizontal { background-color: #c4cbd8; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background-color: #a0aec0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMenu { background-color: #ffffff; border: 1px solid #e0e4ea; border-radius: 6px; padding: 3px; }
QMenu::item { padding: 4px 28px 4px 28px; border-radius: 3px; font-size: 12px; }
QMenu::item:selected { background-color: #e8f0fe; color: #4a6cf7; }
QMenu::separator { height: 1px; background-color: #e8ecf1; margin: 2px 6px; }
QMenu::indicator { width: 14px; height: 14px; margin-left: 8px; border: 1.5px solid #b0b8c8; border-radius: 3px; background-color: #ffffff; }
QMenu::indicator:checked { border: 1.5px solid #4a6cf7; background-color: #4a6cf7; }
QFrame#card { background-color: #ffffff; border: 1px solid #e8ecf1; border-radius: 10px; }
"""


# =============================================================================
# 工具函数
# =============================================================================
def _set_status_text_safe(status_bar, text):
    """安全更新状态栏文本"""
    if not status_bar:
        return
    try:
        status_bar.showMessage(text)
    except Exception:
        pass


# =============================================================================
# SignalBridge — 跨线程安全通信（替代 QTimer.singleShot）
# =============================================================================
class SignalBridge(QObject):
    """工作线程 → 主线程 信号桥。
    所有信号在 main thread 创建，worker thread 中 emit，
    Qt 的 AutoConnection 自动转为 QueuedConnection 安全投递。
    """
    progress_update = Signal(int, str)   # value, message → 进度条
    busy_start = Signal(str)             # message → 脉冲动画
    status_message = Signal(str)         # text → 状态栏
    load_done = Signal()                 # → 关闭对话框
    load_complete = Signal(str, bool)    # file_path, success → 反馈+回调
    tree_update = Signal(str)            # file_name → 更新通道树
    show_info = Signal(str, str)         # title, message (非阻塞提示)


# =============================================================================
# Config / DataManager
# =============================================================================
class Config:
    """配置常量类"""
    DEFAULT_SAMPLE_TIME = 20.0
    DEFAULT_WINDOW_DURATION = 10.0
    DEFAULT_LINEWIDTH = 0.5
    EFFECTIVE_VALUE_METHODS = OrderedDict([
        ("瞬时值", 0.0),
        ("前后1秒平均值", 1.0),
        ("前后3秒平均值", 3.0),
        ("前后5秒平均值", 5.0),
        ("前后10秒平均值", 10.0),
    ])
    COLOR_PALETTE = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
        "#c49c94", "#f7b6d2", "#c7c7c7",
    ]
    LINESTYLE_MAP = {'实线': '-', '虚线': '--', '点线': ':', '点划线': '-.'}
    LINESTYLE_CHOICES = list(LINESTYLE_MAP.keys())
    LINEWIDTH_CHOICES = ['0.5', '1.0', '1.5', '2.0', '2.5', '3.0']


class DataManager:
    """数据管理类 - 惰性加载TDMS数据"""
    def __init__(self):
        self.files_data = OrderedDict()
        self.tdms_files = {}
        self.file_paths = {}
        self._data_cache = {}
        self.sample_time = Config.DEFAULT_SAMPLE_TIME
        self.effective_value_method = "前后10秒平均值"
        self.effective_value_window = 10.0
        self.show_effective_shadow = False
        self._loading_lock = threading.Lock()
        self.filter_enabled = True
        self.exclude_patterns = ['*_time', '*_status', '*_flag']
        self.skip_fault_params = True
        self.skip_reserve_params = True
        self.skip_predefined_params = True
        self.skip_standby_params = True
        self.skip_idle_params = True
        self.skip_delete_params = True
        self._cancel_load = False
        self._last_excluded_count = 0
        self._last_load_error = None

    def load_tdms_file(self, file_path, progress_callback=None, parent_window=None):
        file_name = osp.basename(file_path)
        if file_name in self.files_data:
            return False
        self.files_data[file_name] = {}
        self.file_paths[file_name] = file_path
        try:
            tdms_file = TdmsFile.open(file_path)
            self.tdms_files[file_name] = tdms_file
            return self._process_tdms_data(tdms_file, file_name, progress_callback, parent_window)
        except Exception as e:
            try:
                tdms_file = TdmsFile.open(file_path, mmap=False)
                self.tdms_files[file_name] = tdms_file
                return self._process_tdms_data(tdms_file, file_name, progress_callback, parent_window)
            except Exception as e_backup:
                self._last_load_error = (file_name, f"{type(e).__name__}: {str(e_backup)}")
                print(f"加载失败: {file_name}: {e_backup}")
            if file_name in self.files_data:
                del self.files_data[file_name]
            if file_name in self.tdms_files:
                del self.tdms_files[file_name]
            return False

    def load_tdms_file_with_progress(self, file_path, parent_window, on_finish_callback=None):
        """启动带进度条的异步文件加载（SignalBridge 跨线程通信）"""
        original_file_name = osp.basename(file_path)
        self._cancel_load = False

        bridge = SignalBridge()
        dialog = ProgressDialog(parent_window, "加载文件",
                                f"准备加载文件:\n{original_file_name}")
        dialog.setWindowModality(Qt.ApplicationModal)

        # 信号 → 对话框
        bridge.progress_update.connect(dialog.update_progress)
        bridge.busy_start.connect(dialog.start_busy)
        bridge.load_done.connect(dialog.finish)
        dialog.load_cancelled.connect(lambda: setattr(self, '_cancel_load', True))
        dialog.load_cancelled.connect(dialog.close_dialog)

        # 信号 → 加载完成后的反馈和回调（主线程安全执行）
        bridge.load_complete.connect(
            lambda fp, ok: self._on_single_load_done(fp, ok, parent_window, original_file_name, on_finish_callback))

        # 状态栏
        main_frame = parent_window
        if hasattr(main_frame, 'status_bar'):
            bridge.status_message.connect(lambda m: _set_status_text_safe(main_frame.status_bar, m))

        # 非阻塞提示
        bridge.show_info.connect(
            lambda t, m: QTimer.singleShot(200, lambda: QMessageBox.information(parent_window, t, m)))

        def target():
            with self._loading_lock:
                if original_file_name in self.files_data and len(self.files_data[original_file_name]) > 0:
                    bridge.show_info.emit("提示", f"文件 '{original_file_name}' 已经打开！")
                    bridge.load_done.emit()
                    return

                def _progress_cb(value, message):
                    if not self._cancel_load:
                        bridge.progress_update.emit(value, message)
                        bridge.status_message.emit(f"正在加载: {original_file_name} ({value}%)")

                bridge.busy_start.emit(f"正在解析文件元数据:\n{original_file_name}\n请稍候...")
                bridge.status_message.emit(f"解析中: {original_file_name}")

                success = self.load_tdms_file(file_path, _progress_cb, parent_window)

                if self._cancel_load:
                    if original_file_name in self.files_data:
                        del self.files_data[original_file_name]
                    if original_file_name in self.tdms_files:
                        del self.tdms_files[original_file_name]
                    bridge.status_message.emit("已取消加载")
                    return

                bridge.status_message.emit(f"文件读取完成: {original_file_name}")
                bridge.load_done.emit()
                bridge.load_complete.emit(file_path, success)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        dialog.show()

    def _on_single_load_done(self, file_path, success, parent_window, original_file_name, on_finish_callback):
        """单文件加载完成回调（主线程执行）"""
        self._show_load_feedback(parent_window, original_file_name)
        if on_finish_callback:
            on_finish_callback(file_path, success)

    def _show_load_feedback(self, parent_window, file_name):
        """加载完成后仅在状态栏提示，不弹出对话框"""
        msg_parts = []
        if self._last_excluded_count > 0:
            msg_parts.append(f"已排除 {self._last_excluded_count} 个通道")
            self._last_excluded_count = 0
        if self._last_load_error and self._last_load_error[0] == file_name:
            msg_parts.append(f"加载失败: {self._last_load_error[1]}")
            self._last_load_error = None
        # 仅在状态栏提示，不弹对话框
        if msg_parts and hasattr(parent_window, 'status_bar'):
            parent_window.status_bar.showMessage(" | ".join(msg_parts))

    def unload_file(self, file_name):
        if file_name in self.files_data:
            del self.files_data[file_name]
        if file_name in self.tdms_files:
            del self.tdms_files[file_name]
        if file_name in self.file_paths:
            del self.file_paths[file_name]
        keys_to_remove = [k for k in self._data_cache if k[0] == file_name]
        for k in keys_to_remove:
            del self._data_cache[k]

    def get_channel_data(self, file_name, group_name, channel_name):
        cache_key = (file_name, group_name, channel_name)
        if cache_key in self._data_cache:
            return self._data_cache[cache_key]
        try:
            channel = self.files_data[file_name][group_name][channel_name]
            data = np.asarray(channel[:])
            self._data_cache[cache_key] = data
            return data
        except KeyError:
            return None

    def should_exclude_channel(self, channel_name, data=None):
        if self.skip_fault_params and '故障' in channel_name:
            return True
        if self.skip_reserve_params and '保留' in channel_name:
            return True
        if self.skip_predefined_params and '预留' in channel_name:
            return True
        if self.skip_standby_params and '备用' in channel_name:
            return True
        if self.skip_idle_params and '空闲' in channel_name:
            return True
        if self.skip_delete_params and '删除' in channel_name:
            return True
        if not self.filter_enabled:
            return False
        for pattern in self.exclude_patterns:
            if self._match_pattern(channel_name, pattern):
                return True
        return False

    def _match_pattern(self, name, pattern):
        return fnmatch.fnmatch(name.lower(), pattern.lower())

    def get_file_stats(self, file_name):
        if file_name not in self.files_data:
            return {"groups": 0, "channels": 0}
        groups = len(self.files_data[file_name])
        channels = sum(len(ch) for ch in self.files_data[file_name].values())
        return {"groups": groups, "channels": channels}

    def clear(self):
        self.files_data.clear()
        self.tdms_files.clear()
        self.file_paths.clear()
        self._data_cache.clear()
        gc.collect()

    def _process_tdms_data(self, tdms_file, file_name, progress_callback, parent_window=None):
        try:
            total_channels = sum(len(group.channels()) for group in tdms_file.groups())
        except Exception:
            total_channels = 0
        loaded_channels = 0
        excluded_count = 0
        last_progress = -1
        for group in tdms_file.groups():
            if self._cancel_load:
                break
            group_name = group.name
            for channel in group.channels():
                if self._cancel_load:
                    break
                channel_name = channel.name
                if self.should_exclude_channel(channel_name, data=None):
                    excluded_count += 1
                    continue
                if total_channels > 0 and progress_callback:
                    loaded_channels += 1
                    progress = 30 + int((loaded_channels / total_channels) * 70)
                    if progress != last_progress:
                        last_progress = progress
                        progress_callback(progress, f"正在加载文件元数据:\n{file_name}\n当前通道: {group_name} / {channel_name}")
                if group_name not in self.files_data[file_name]:
                    self.files_data[file_name][group_name] = OrderedDict()
                self.files_data[file_name][group_name][channel_name] = channel
        if excluded_count > 0:
            # 不弹出阻塞对话框，仅在完成后通过状态栏提示
            self._last_excluded_count = excluded_count
        return True


# =============================================================================
# 自定义表格委托（替代 wx.grid 渲染器）
# =============================================================================
class ColorDelegate(QStyledItemDelegate):
    """颜色列委托 - 绘制圆形色块"""
    def paint(self, painter, option, index):
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#e8f0fe"))
        else:
            painter.fillRect(option.rect, QColor(255, 255, 255))
        color_hex = index.data(Qt.DisplayRole) or "#cccccc"
        color = QColor(color_hex)
        rect = option.rect
        size = min(rect.width() - 12, rect.height() - 12, 22)
        if size > 0:
            cx = rect.x() + (rect.width() - size) // 2
            cy = rect.y() + (rect.height() - size) // 2
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor("#999999"), 1))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(cx, cy, size, size)
        painter.restore()


class CheckboxDelegate(QStyledItemDelegate):
    """复选框列委托 — 16x16 小巧切换开关"""
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        bg = QColor("#e8f0fe") if (option.state & QStyle.State_Selected) else QColor(255, 255, 255)
        painter.fillRect(rect, bg)
        size = 16
        cx = rect.x() + (rect.width() - size) // 2
        cy = rect.y() + (rect.height() - size) // 2
        r = QRect(cx, cy, size, size)
        checked = index.data(Qt.DisplayRole) == "1"
        if checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#4a6cf7"))
            painter.drawRoundedRect(r, 3, 3)
            painter.setPen(QPen(Qt.white, 1.5))
            painter.drawLine(cx + 4, cy + 8, cx + 7, cy + 12)
            painter.drawLine(cx + 7, cy + 12, cx + 13, cy + 4)
        else:
            painter.setPen(QPen(QColor("#c4cbd8"), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(r, 3, 3)
        painter.restore()


class LineStyleDelegate(QStyledItemDelegate):
    """线型列委托 — 所有行使用统一的线宽和长度"""
    def paint(self, painter, option, index):
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#e8f0fe"))
        else:
            painter.fillRect(option.rect, QColor(255, 255, 255))
        linestyle = index.data(Qt.DisplayRole) or "实线"
        rect = option.rect
        # 固定线宽=1.5 和固定长度=40，居中绘制
        y = rect.y() + rect.height() // 2
        line_len = 40
        x1 = rect.x() + (rect.width() - line_len) // 2
        x2 = x1 + line_len
        style_map = {'实线': Qt.SolidLine, '虚线': Qt.DashLine,
                     '点线': Qt.DotLine, '点划线': Qt.DashDotLine}
        pen = QPen(QColor("#333333"), 1.5, style_map.get(linestyle, Qt.SolidLine))
        painter.setPen(pen)
        painter.drawLine(x1, y, x2, y)
        painter.restore()


class ColorPopupWidget(QWidget):
    """颜色选择弹出窗 — 用 paintEvent 自绘色块，避免 QSS 干扰"""
    color_selected = Signal(str)

    def __init__(self, parent, colors):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self._colors = colors
        self._hover_idx = -1
        cols = 6
        rows = (len(colors) + cols - 1) // cols
        self._cols = cols
        self._rows = rows
        self._cell = 36
        self._pad = 8
        w = cols * self._cell + self._pad * 2
        h = rows * self._cell + self._pad * 2
        self.setFixedSize(w, h)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 背景
        p.setPen(QPen(QColor("#e0e4ea"), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
        # 色块
        r0 = self._cell // 2
        for i, hex_code in enumerate(self._colors):
            col = i % self._cols
            row = i // self._cols
            cx = self._pad + col * self._cell + self._cell // 2
            cy = self._pad + row * self._cell + self._cell // 2
            radius = r0 - 5
            # hover 时加蓝色外圈
            if i == self._hover_idx:
                p.setPen(QPen(QColor("#4a6cf7"), 3))
            else:
                p.setPen(QPen(QColor("#cccccc"), 1))
            p.setBrush(QColor(hex_code))
            p.drawEllipse(QPoint(cx, cy), radius, radius)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        idx = self._pos_to_index(pos)
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.update()

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        idx = self._pos_to_index(pos)
        if 0 <= idx < len(self._colors):
            self._select(self._colors[idx])

    def _pos_to_index(self, pos):
        x = pos.x() - self._pad
        y = pos.y() - self._pad
        if x < 0 or y < 0:
            return -1
        col = x // self._cell
        row = y // self._cell
        if col >= self._cols or row >= self._rows:
            return -1
        return row * self._cols + col

    def _select(self, hex_code):
        self.color_selected.emit(hex_code)
        self.close()


class LineStylePopupWidget(QWidget):
    """线型选择弹出窗 — 用 paintEvent 自绘，避免 QSS 干扰"""
    style_selected = Signal(str)

    def __init__(self, parent):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self._items = list(Config.LINESTYLE_MAP.items())
        self._hover_idx = -1
        self._item_h = 30
        self._w = 150
        self.setFixedSize(self._w, len(self._items) * self._item_h + 8)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 背景
        p.setPen(QPen(QColor("#e0e4ea"), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
        # 各项
        style_map = {'-': Qt.SolidLine, '--': Qt.DashLine,
                     ':': Qt.DotLine, '-.': Qt.DashDotLine}
        for i, (name, code) in enumerate(self._items):
            y = 4 + i * self._item_h
            # hover 背景
            if i == self._hover_idx:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#e8f0fe"))
                p.drawRoundedRect(4, y, self._w - 8, self._item_h - 2, 4, 4)
            # 线型示意
            p.setPen(QPen(QColor("#333333"), 2,
                          style_map.get(code, Qt.SolidLine)))
            p.drawLine(14, y + self._item_h // 2, 60, y + self._item_h // 2)
            # 名称
            p.setPen(QColor("#2d3436"))
            font = p.font()
            font.setPointSize(10)
            p.setFont(font)
            p.drawText(70, y, 70, self._item_h - 2,
                       Qt.AlignVCenter | Qt.AlignLeft, name)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        idx = (pos.y() - 4) // self._item_h
        if 0 <= idx < len(self._items) and idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        elif idx < 0 or idx >= len(self._items):
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.update()

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        idx = (pos.y() - 4) // self._item_h
        if 0 <= idx < len(self._items):
            self._select(self._items[idx][0])

    def _select(self, style_name):
        self.style_selected.emit(style_name)
        self.close()


class LineWidthPopupWidget(QWidget):
    """线宽选择弹出窗 — paintEvent 自绘不同粗细的线段"""
    width_selected = Signal(str)

    def __init__(self, parent):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self._items = Config.LINEWIDTH_CHOICES
        self._hover_idx = -1
        self._item_h = 28
        self._w = 120
        self.setFixedSize(self._w, len(self._items) * self._item_h + 8)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#e0e4ea"), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        for i, lw in enumerate(self._items):
            y = 4 + i * self._item_h
            if i == self._hover_idx:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#e8f0fe"))
                p.drawRoundedRect(4, y, self._w - 8, self._item_h - 2, 4, 4)
            w = float(lw)
            p.setPen(QPen(QColor("#333333"), w, Qt.SolidLine))
            p.drawLine(14, y + self._item_h // 2, 50, y + self._item_h // 2)
            p.setPen(QColor("#2d3436"))
            font = p.font()
            font.setPointSize(10)
            p.setFont(font)
            p.drawText(58, y, 50, self._item_h - 2,
                       Qt.AlignVCenter | Qt.AlignLeft, lw)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        idx = (pos.y() - 4) // self._item_h
        if 0 <= idx < len(self._items) and idx != self._hover_idx:
            self._hover_idx = idx
            self.update()
        elif not (0 <= idx < len(self._items)):
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.update()

    def mousePressEvent(self, event):
        pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
        idx = (pos.y() - 4) // self._item_h
        if 0 <= idx < len(self._items):
            self._select(self._items[idx])

    def _select(self, lw):
        self.width_selected.emit(lw)
        self.close()


# =============================================================================
# ProgressDialog
# =============================================================================
class ProgressDialog(QDialog):
    """进度条对话框 — 非模态，不阻塞事件循环"""
    load_cancelled = Signal()

    def __init__(self, parent, title="处理中", message="正在加载文件..."):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowModality(Qt.WindowModal)
        self._import_stopped = False
        self._busy_mode = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("font-size: 13px; color: #4a5568;")
        layout.addWidget(self.message_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(self.cancel_btn, alignment=Qt.AlignRight)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._on_pulse)
        self._pulse_value = 0

    def _on_cancel(self):
        ret = QMessageBox.question(self, "停止导入",
                                   "确定要停止当前文件的导入吗？\n已加载的部分数据将被丢弃。",
                                   QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self._import_stopped = True
            self.load_cancelled.emit()
            self.stop_busy()
            self.hide()

    def update_progress(self, value, message=None):
        """更新进度 — 从主线程调用（通过 QTimer.singleShot）"""
        if self._import_stopped:
            return
        if self._busy_mode:
            self.stop_busy()
        if message:
            self.message_label.setText(message)
        self.progress.setValue(value)

    def start_busy(self, message=None):
        if self._import_stopped:
            return
        if not self._busy_mode:
            self._busy_mode = True
            self._pulse_value = 0
            self.progress.setRange(0, 0)
            self._pulse_timer.start(50)
        if message:
            self.message_label.setText(message)

    def stop_busy(self):
        if self._busy_mode:
            self._busy_mode = False
            self._pulse_timer.stop()
            self.progress.setRange(0, 100)

    def _on_pulse(self):
        if self._pulse_value < 90:
            self._pulse_value += 2
        self.progress.setValue(self._pulse_value)

    def finish(self):
        self.stop_busy()
        self.progress.setValue(100)
        self.hide()

    def close_dialog(self):
        self.stop_busy()
        self.hide()


# =============================================================================
# FilterConfigDialog
# =============================================================================
class FilterConfigDialog(QDialog):
    """数据筛选配置对话框"""
    def __init__(self, parent, data_manager):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("数据筛选设置")
        self.setMinimumSize(420, 320)
        self.data_manager = data_manager
        self._create_ui()
        self._load_settings()
        self.adjustSize()
        pos = QCursor.pos()
        self.move(pos)

    def _create_ui(self):
        # 上下微调按钮置于文本框外部右侧（不覆盖文字）
        self.setStyleSheet("""
            QSpinBox { padding-right: 2px; }
            QSpinBox::up-button {
                subcontrol-origin: margin;
                subcontrol-position: top right;
                right: -20px; width: 18px; height: 16px;
                border: 1px solid #c4cbd8; border-radius: 3px; background: #f0f2f5;
            }
            QSpinBox::down-button {
                subcontrol-origin: margin;
                subcontrol-position: bottom right;
                right: -20px; width: 18px; height: 16px;
                border: 1px solid #c4cbd8; border-radius: 3px; background: #f0f2f5;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #e3e8f0; }
            QSpinBox::up-arrow, QSpinBox::down-arrow { width: 8px; height: 8px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 36, 16)

        self.enable_check = QCheckBox("启用数据筛选")
        layout.addWidget(self.enable_check)

        label = QLabel("排除模式（支持通配符 * 和 ?）:")
        layout.addWidget(label)

        self.pattern_list = QListWidget()
        self.pattern_list.setAlternatingRowColors(True)
        layout.addWidget(self.pattern_list)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("添加")
        self.edit_btn = QPushButton("编辑")
        self.delete_btn = QPushButton("删除")
        self.default_btn = QPushButton("恢复默认")
        self.default_btn.setObjectName("secondary")
        for btn in [self.add_btn, self.edit_btn, self.delete_btn]:
            btn_layout.addWidget(btn)
        btn_layout.addWidget(self.default_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        btn_layout2 = QHBoxLayout()
        btn_layout2.addStretch()
        self.ok_btn = QPushButton("确定")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondary")
        btn_layout2.addWidget(self.ok_btn)
        btn_layout2.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout2)

        self.enable_check.stateChanged.connect(self._on_enable_changed)
        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn.clicked.connect(self._on_delete)
        self.default_btn.clicked.connect(self._on_restore_default)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def _load_settings(self):
        self.enable_check.setChecked(self.data_manager.filter_enabled)
        self.pattern_list.clear()
        for pattern in self.data_manager.exclude_patterns:
            self.pattern_list.addItem(pattern)

    def _on_enable_changed(self, state):
        self.data_manager.filter_enabled = bool(state)

    def _on_add(self):
        text, ok = QInputDialog.getText(self, "添加模式", "请输入排除模式:")
        if ok and text and text not in self.data_manager.exclude_patterns:
            self.data_manager.exclude_patterns.append(text)
            self.pattern_list.addItem(text)

    def _on_edit(self):
        item = self.pattern_list.currentItem()
        if item:
            old = item.text()
            text, ok = QInputDialog.getText(self, "编辑模式", "请输入新的排除模式:", text=old)
            if ok and text:
                idx = self.pattern_list.row(item)
                self.data_manager.exclude_patterns[idx] = text
                item.setText(text)

    def _on_delete(self):
        item = self.pattern_list.currentItem()
        if item:
            idx = self.pattern_list.row(item)
            del self.data_manager.exclude_patterns[idx]
            self.pattern_list.takeItem(idx)

    def _on_restore_default(self):
        ret = QMessageBox.question(self, "确认", "确定要恢复默认设置吗？",
                                   QMessageBox.Yes | QMessageBox.No)
        if ret == QMessageBox.Yes:
            self.data_manager.exclude_patterns = ['*_time', '*_status', '*_flag']
            self.pattern_list.clear()
            for p in self.data_manager.exclude_patterns:
                self.pattern_list.addItem(p)


# =============================================================================
# ImportOptionsDialog
# =============================================================================
class ImportOptionsDialog(QDialog):
    """导入选项设置对话框"""
    def __init__(self, parent, data_manager):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("导入选项")
        self.data_manager = data_manager
        self._create_ui()
        self._load_settings()
        self.adjustSize()
        pos = QCursor.pos()
        self.move(pos)
        self.adjustSize()
        pos = QCursor.pos()
        self.move(pos)

    def _create_ui(self):
        # 上下微调按钮置于文本框外部右侧（不覆盖文字）
        self.setStyleSheet("""
            QSpinBox { padding-right: 2px; }
            QSpinBox::up-button {
                subcontrol-origin: margin;
                subcontrol-position: top right;
                right: -20px; width: 18px; height: 16px;
                border: 1px solid #c4cbd8; border-radius: 3px; background: #f0f2f5;
            }
            QSpinBox::down-button {
                subcontrol-origin: margin;
                subcontrol-position: bottom right;
                right: -20px; width: 18px; height: 16px;
                border: 1px solid #c4cbd8; border-radius: 3px; background: #f0f2f5;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #e3e8f0; }
            QSpinBox::up-arrow, QSpinBox::down-arrow { width: 8px; height: 8px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 36, 16)

        title = QLabel("导入时自动跳过参数名包含以下字样的参数：")
        title.setStyleSheet("font-weight: 600; font-size: 13px; color: #2d3436;")
        layout.addWidget(title)
        layout.addSpacing(10)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color: #e0e4ea; max-height: 1px;")
        layout.addWidget(sep)
        layout.addSpacing(12)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.cb_fault = QCheckBox('故障')
        self.cb_reserve = QCheckBox('保留')
        self.cb_predefined = QCheckBox('预留')
        self.cb_standby = QCheckBox('备用')
        self.cb_idle = QCheckBox('空闲')
        self.cb_delete = QCheckBox('删除')
        grid.addWidget(self.cb_fault, 0, 0)
        grid.addWidget(self.cb_reserve, 0, 1)
        grid.addWidget(self.cb_predefined, 0, 2)
        grid.addWidget(self.cb_standby, 1, 0)
        grid.addWidget(self.cb_idle, 1, 1)
        grid.addWidget(self.cb_delete, 1, 2)
        layout.addLayout(grid)
        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.ok_btn = QPushButton("确定")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondary")
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.ok_btn.clicked.connect(self._on_ok)
        self.cancel_btn.clicked.connect(self._on_cancel)

    def _load_settings(self):
        self.cb_fault.setChecked(self.data_manager.skip_fault_params)
        self.cb_reserve.setChecked(self.data_manager.skip_reserve_params)
        self.cb_predefined.setChecked(self.data_manager.skip_predefined_params)
        self.cb_standby.setChecked(self.data_manager.skip_standby_params)
        self.cb_idle.setChecked(self.data_manager.skip_idle_params)
        self.cb_delete.setChecked(self.data_manager.skip_delete_params)

    def _save_settings(self):
        self.data_manager.skip_fault_params = self.cb_fault.isChecked()
        self.data_manager.skip_reserve_params = self.cb_reserve.isChecked()
        self.data_manager.skip_predefined_params = self.cb_predefined.isChecked()
        self.data_manager.skip_standby_params = self.cb_standby.isChecked()
        self.data_manager.skip_idle_params = self.cb_idle.isChecked()
        self.data_manager.skip_delete_params = self.cb_delete.isChecked()

    def _on_ok(self):
        self._save_settings()
        self.accept()

    def _on_cancel(self):
        self.reject()


# =============================================================================
# EffectiveValueDialog
# =============================================================================
class EffectiveValueDialog(QDialog):
    """有效值获取方式对话框"""
    def __init__(self, parent, data_manager):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("有效值获取方式")
        self.data_manager = data_manager
        self._create_ui()
        self.adjustSize()
        pos = QCursor.pos()
        self.move(pos)

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 36, 16)

        label = QLabel("请选择有效值计算方式：")
        label.setStyleSheet("font-weight: 600; font-size: 13px; color: #2d3436;")
        layout.addWidget(label)
        layout.addSpacing(10)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color: #e0e4ea; max-height: 1px;")
        layout.addWidget(sep)
        layout.addSpacing(12)

        self._radio_group = QButtonGroup(self)
        choices = list(Config.EFFECTIVE_VALUE_METHODS.keys())
        default_idx = choices.index(self.data_manager.effective_value_method)
        self._radio_buttons = []
        for i, choice in enumerate(choices):
            rb = QRadioButton(choice)
            if i == default_idx:
                rb.setChecked(True)
            self._radio_group.addButton(rb, i)
            layout.addWidget(rb)
            self._radio_buttons.append(rb)

        layout.addSpacing(8)
        self.shadow_check = QCheckBox("显示有效值阴影（按窗口宽度）")
        self.shadow_check.setChecked(self.data_manager.show_effective_shadow)
        self.shadow_check.setToolTip("选中后，红蓝竖直线两侧会显示半透明阴影区域，宽度等于有效值计算窗口")
        layout.addWidget(self.shadow_check)
        layout.addSpacing(8)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.ok_btn = QPushButton("确定")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondary")
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def GetSelectedMethod(self):
        choices = list(Config.EFFECTIVE_VALUE_METHODS.keys())
        selected_idx = 0
        for i, rb in enumerate(self._radio_buttons):
            if rb.isChecked():
                selected_idx = i
                break
        return (choices[selected_idx],
                Config.EFFECTIVE_VALUE_METHODS[choices[selected_idx]],
                self.shadow_check.isChecked())


# =============================================================================
# SaveImageDialog
# =============================================================================
class SaveImageDialog(QDialog):
    """保存图像字体设置对话框，含预览功能"""
    def __init__(self, parent, plot_panel):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("图像保存设置")
        self.plot_panel = plot_panel
        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        # 与主界面保持一致：沿用全局 13px 字号，不再单独放大
        layout.setContentsMargins(36, 16, 36, 16)
        layout.setSpacing(12)

        # 坐标轴字体大小（微调按钮置于文本框外部右侧）
        axis_layout = QHBoxLayout()
        axis_layout.setSpacing(10)
        axis_label = QLabel("坐标字体大小:")
        axis_label.setFixedWidth(96)
        axis_layout.addWidget(axis_label)
        self.axis_font_size = QSpinBox()
        self.axis_font_size.setRange(6, 24)
        self.axis_font_size.setValue(8)
        self.axis_font_size.setButtonSymbols(QSpinBox.NoButtons)
        self.axis_font_size.setToolTip("坐标轴标签和刻度文字的大小")
        self.axis_font_size.setMinimumWidth(80)
        axis_layout.addWidget(self.axis_font_size, 1, Qt.AlignVCenter)
        self._make_spin_buttons(self.axis_font_size, axis_layout)
        layout.addLayout(axis_layout)

        # 图例字体大小
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(10)
        legend_label = QLabel("图例文字大小:")
        legend_label.setFixedWidth(96)
        legend_layout.addWidget(legend_label)
        self.legend_font_size = QSpinBox()
        self.legend_font_size.setRange(6, 24)
        self.legend_font_size.setValue(8)
        self.legend_font_size.setButtonSymbols(QSpinBox.NoButtons)
        self.legend_font_size.setToolTip("图例区域会随文字大小自动调整")
        self.legend_font_size.setMinimumWidth(80)
        legend_layout.addWidget(self.legend_font_size, 1, Qt.AlignVCenter)
        self._make_spin_buttons(self.legend_font_size, legend_layout)
        layout.addLayout(legend_layout)

        # 数值变化时实时预览到绘图区（改变尺寸立即对显示生效）
        self.axis_font_size.valueChanged.connect(self._on_preview)
        self.legend_font_size.valueChanged.connect(self._on_preview)

        layout.addSpacing(14)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color: #e0e4ea; max-height: 1px;")
        layout.addWidget(sep)

        layout.addSpacing(14)

        # 按钮区（确定/取消铺满整行）
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.ok_btn = QPushButton("确定")
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("secondary")
        btn_layout.addWidget(self.ok_btn, 1)
        btn_layout.addWidget(self.cancel_btn, 1)
        layout.addLayout(btn_layout)

        self.setMinimumWidth(360)

        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def _make_spin_buttons(self, spin, row_layout):
        """在文本框右侧生成上下微调按钮（一行排列，垂直居中对齐）"""
        btn_style = ("QPushButton { border: 1px solid #c4cbd8; border-radius: 3px; "
                     "background: #f0f2f5; font-size: 12px; color: #4a5568; }"
                     "QPushButton:hover { background: #e8f0fe; border-color: #4a6cf7; color: #4a6cf7; }")
        up = QPushButton("▲")
        down = QPushButton("▼")
        for b in (up, down):
            b.setFixedSize(18, 18)
            b.setStyleSheet(btn_style)
        up.clicked.connect(spin.stepUp)
        down.clicked.connect(spin.stepDown)
        # 直接加入行布局并以垂直居中对齐，确保与文本框上下对齐
        row_layout.addWidget(up, 0, Qt.AlignVCenter)
        row_layout.addWidget(down, 0, Qt.AlignVCenter)

    def _on_preview(self):
        """预览：将当前字体设置实时应用到绘图区"""
        axis_font = self.axis_font_size.value()
        legend_font = self.legend_font_size.value()
        p = self.plot_panel

        p.axes.xaxis.label.set_fontsize(axis_font)
        p.axes.yaxis.label.set_fontsize(axis_font)
        p.axes.tick_params(axis='both', labelsize=axis_font)
        for right_ax in p.right_axes_dict.values():
            right_ax.yaxis.label.set_fontsize(axis_font)
            right_ax.tick_params(axis='y', labelsize=axis_font)

        legend = p.axes.get_legend()
        if legend:
            for text in legend.get_texts():
                text.set_fontsize(legend_font)

        for obj in [p.crosshair_v, p.crosshair_h, p.crosshair_text]:
            if obj is not None:
                obj.set_visible(False)

        p.figure.tight_layout(pad=1.0)
        p.canvas.draw()

    def get_settings(self):
        return {
            'axis_font_size': self.axis_font_size.value(),
            'legend_font_size': self.legend_font_size.value()
        }


# =============================================================================
# MatplotlibPlotPanel
# =============================================================================
class MatplotlibPlotPanel(QWidget):
    """Matplotlib绘图面板"""

    def __init__(self, parent, on_vertical_lines_changed_callback):
        super().__init__(parent)
        self.on_vertical_lines_changed = on_vertical_lines_changed_callback

        self.current_plots = {}
        self.original_data = {}
        self.red_line = None
        self.blue_line = None
        self.red_line_x = None
        self.blue_line_x = None
        self.red_shadow = None
        self.blue_shadow = None
        self.span_selector = None
        self.dragging = None
        self.right_axes_dict = {}
        self.x_max = Config.DEFAULT_WINDOW_DURATION
        self.crosshair_v = None
        self.crosshair_h = None
        self.crosshair_text = None

        self._create_ui()
        self._setup_event_bindings()

    def _create_ui(self):
        self.figure = Figure(figsize=(10, 6), dpi=120)
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setParent(self)

        toolbar_panel = self._create_toolbar()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar_panel)
        layout.addWidget(self.canvas, 1)

    def _create_toolbar(self):
        panel = QWidget(self)
        panel.setStyleSheet("""
            QWidget { background-color: #ffffff; border-bottom: 1px solid #e0e4ea; }
            QLabel { border: none; background: transparent; color: #4a5568; }
            QCheckBox { border: none; background: transparent; color: #4a5568; spacing: 4px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 1.5px solid #c4cbd8; }
            QCheckBox::indicator:checked { background-color: #4a6cf7; border-color: #4a6cf7; }
            QCheckBox::indicator:hover { border-color: #4a6cf7; }
            QPushButton#tool_btn { background-color: transparent; color: #4a5568; border: 1px solid #c4cbd8; border-radius: 5px; font-size: 13px; padding: 5px 10px; font-weight: 500; }
            QPushButton#tool_btn:hover { background-color: #e8f0fe; color: #4a6cf7; border-color: #4a6cf7; }
        """)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)
        # 绘图区工具栏（导出数据/保存图像按钮区域）
        panel.setFixedHeight(45)

        # 工具按钮
        tools = [("导出数据", self.on_export_data),
                 ("保存图像", self.on_save_image),
                 ("导出有效值", self.on_export_effective_values)]
        for label, handler in tools:
            btn = QPushButton(label)
            btn.setObjectName("tool_btn")
            btn.clicked.connect(handler)
            layout.addWidget(btn)

        layout.addStretch()

        # 窗口时长
        layout.addWidget(QLabel("窗口时长(s):"))
        self.window_duration = QLineEdit("10.0")
        self.window_duration.setFixedWidth(90)
        self.window_duration.returnPressed.connect(self._on_window_duration_changed)
        self.window_duration.editingFinished.connect(self._on_window_duration_changed)
        layout.addWidget(self.window_duration)

        layout.addSpacing(10)

        # 竖直线控制
        layout.addWidget(QLabel("竖直线:"))
        self.red_line_check = QCheckBox("红色")
        self.red_line_check.setChecked(False)
        self.red_line_check.stateChanged.connect(self._on_red_line_toggle)
        layout.addWidget(self.red_line_check)
        self.blue_line_check = QCheckBox("蓝色")
        self.blue_line_check.setChecked(False)
        self.blue_line_check.stateChanged.connect(self._on_blue_line_toggle)
        layout.addWidget(self.blue_line_check)

        layout.addSpacing(6)
        self.show_shadow_check = QCheckBox("有效值阴影")
        self.show_shadow_check.setToolTip("选中后，红蓝竖直线两侧会显示半透明阴影区域")
        self.show_shadow_check.stateChanged.connect(self._on_shadow_toggle)
        layout.addWidget(self.show_shadow_check)

        return panel

    def _on_shadow_toggle(self, state):
        main_frame = self.window()
        if hasattr(main_frame, 'data_manager'):
            main_frame.data_manager.show_effective_shadow = bool(state)
            self._update_vertical_lines()

    def sync_shadow_check(self):
        main_frame = self.window()
        if hasattr(main_frame, 'data_manager'):
            self.show_shadow_check.setChecked(main_frame.data_manager.show_effective_shadow)

    def _setup_event_bindings(self):
        self.canvas.mpl_connect('button_press_event', self._on_mouse_press)
        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_motion)
        self.canvas.mpl_connect('button_release_event', self._on_mouse_release)
        self.canvas.mpl_connect('button_press_event', self._on_navigation)
        self.canvas.mpl_connect('scroll_event', self._on_scroll)

    def plot(self, plots_data, parameters, show_actual_value_channels=None, top_channels=None):
        if show_actual_value_channels is None:
            show_actual_value_channels = set()
        if top_channels is None:
            top_channels = set()

        self._clear_plot()

        if len(plots_data) == 1:
            y_raw = plots_data[0]['y_data']
            if np.min(y_raw) == np.max(y_raw) and plots_data[0]['name'] not in show_actual_value_channels:
                show_actual_value_channels.add(plots_data[0]['name'])

        self._prepare_plot_data(plots_data, parameters, show_actual_value_channels, top_channels)
        self._setup_plot_appearance()
        self.axes.set_xlim(0, self.x_max)
        for right_ax in self.right_axes_dict.values():
            right_ax.set_xlim(0, self.x_max)
        self._auto_scale_y()
        self._update_vertical_lines()
        self._finalize_plot()

    def _clear_plot(self):
        self.axes.clear()
        for ax in self.right_axes_dict.values():
            ax.remove()
        self.right_axes_dict.clear()
        self.current_plots.clear()
        self.original_data.clear()
        self.crosshair_v = None
        self.crosshair_h = None
        self.crosshair_text = None
        self.red_shadow = None
        self.blue_shadow = None

    def _prepare_plot_data(self, plots_data, parameters, show_actual_value_channels, top_channels):
        max_x = max((np.max(pd['x_data']) for pd in plots_data if len(pd['x_data']) > 0),
                    default=0)
        if max_x > 0:
            self.window_duration.setText(f"{max_x:.2f}")
            self.x_max = max_x
        else:
            self.x_max = Config.DEFAULT_WINDOW_DURATION

        normal_plots, top_plots = [], []
        for plot_data in plots_data:
            plot_info = self._create_plot_info(plot_data, parameters, show_actual_value_channels, top_channels)
            if plot_info['is_top']:
                top_plots.append(plot_info)
            else:
                normal_plots.append(plot_info)
        self._draw_plots(normal_plots + top_plots, parameters, show_actual_value_channels)

    @staticmethod
    def _downsample(x, y, threshold=4000):
        n = len(x)
        if n <= threshold:
            return x, y
        out_x = np.empty(threshold)
        out_y = np.empty(threshold)
        out_x[0] = x[0]; out_y[0] = y[0]
        out_x[-1] = x[-1]; out_y[-1] = y[-1]
        bucket_size = (n - 2) / (threshold - 2)
        a = 0
        for i in range(threshold - 2):
            s = int(np.floor(i * bucket_size) + 1)
            e = int(np.floor((i + 1) * bucket_size) + 1)
            e = min(e, n - 1)
            ns = int(np.floor((i + 1) * bucket_size) + 1)
            ne = int(np.floor((i + 2) * bucket_size) + 1)
            ne = min(ne, n)
            avg_x = x[ns:ne].mean()
            avg_y = y[ns:ne].mean()
            ax, ay = x[a], y[a]
            area = np.abs((ax - avg_x) * (y[s:e] - ay) - (ax - x[s:e]) * (avg_y - ay))
            a = s + int(np.argmax(area))
            out_x[i + 1] = x[a]
            out_y[i + 1] = y[a]
        return out_x, out_y

    def _create_plot_info(self, plot_data, parameters, show_actual_value_channels, top_channels):
        name = plot_data['name']
        simple_name = self._extract_simple_name(name)
        self.original_data[name] = {'x': plot_data['x_data'], 'y': plot_data['y_data']}
        param = parameters.get(name, {})
        color = param.get('color', '#1f77b4')
        linestyle = param.get('linestyle', '-')
        linewidth = float(param.get('linewidth', Config.DEFAULT_LINEWIDTH))
        legend_name = param.get('legend_name', simple_name)
        show_actual = name in show_actual_value_channels
        is_top = name in top_channels
        y_data = plot_data['y_data']
        y_min, y_max = np.min(y_data), np.max(y_data)
        if self._is_percent_mode() and not show_actual:
            if y_max != y_min:
                y_data = (y_data - y_min) / (y_max - y_min) * 100
            else:
                y_data = np.full_like(y_data, 100.0)
        return {
            'x_data': plot_data['x_data'], 'y_data': y_data, 'name': name,
            'display_name': simple_name, 'legend_name': legend_name,
            'color': color, 'linestyle': linestyle, 'linewidth': linewidth,
            'show_actual': show_actual, 'is_top': is_top,
            'original_data': plot_data['y_data'], 'is_constant': (y_max == y_min)
        }

    def _draw_plots(self, plots, parameters, show_actual_value_channels):
        for plot_info in plots:
            if not plot_info['show_actual'] or self._is_percent_mode():
                line = self._draw_single_plot(plot_info)
                if line:
                    self.current_plots[plot_info['name']] = line
        self._create_right_axes(parameters, show_actual_value_channels)

    def _create_right_axes(self, parameters, show_actual_value_channels):
        actual_value_channels = [
            name for name in parameters.keys()
            if name in show_actual_value_channels and not self._is_percent_mode()
        ]
        for i, channel_name in enumerate(actual_value_channels):
            if channel_name not in self.original_data:
                continue
            right_ax = self.axes.twinx()
            offset = 60 * (i + 1)
            right_ax.spines['right'].set_position(('outward', offset))
            color = parameters[channel_name].get('color', '#1f77b4')
            right_ax.spines['right'].set_color(color)
            right_ax.tick_params(axis='y', colors=color)
            right_ax.yaxis.label.set_color(color)
            simple_name = self._extract_simple_name(channel_name)
            legend_name = parameters[channel_name].get('legend_name', simple_name)
            right_ax.set_ylabel(legend_name, fontsize=8)
            right_ax.set_xlim(self.axes.get_xlim())
            self.right_axes_dict[channel_name] = right_ax
            self._draw_actual_value(right_ax, channel_name, parameters)

    def _draw_actual_value(self, right_ax, channel_name, parameters):
        channel_data = self.original_data[channel_name]
        param = parameters[channel_name]
        color = param.get('color', '#1f77b4')
        linestyle = param.get('linestyle', '-')
        linewidth = float(param.get('linewidth', Config.DEFAULT_LINEWIDTH))
        main_frame = self.window()
        is_top = channel_name in getattr(main_frame.param_panel, 'top_channels', set())
        zorder = 10 if is_top else 1
        simple_name = self._extract_simple_name(channel_name)
        legend_name = param.get('legend_name', simple_name)
        label_parts = [legend_name]
        if not self._is_percent_mode():
            label_parts.append("实际值")
        label = " ".join(label_parts)
        line, = right_ax.plot(*self._downsample(channel_data['x'], channel_data['y']),
                              label=label, color=color, linestyle=linestyle,
                              linewidth=linewidth, zorder=zorder)
        self.current_plots[channel_name] = line

    def _draw_single_plot(self, plot_info):
        zorder = 10 if plot_info['is_top'] else 1
        x_data, y_data = self._downsample(plot_info['x_data'], plot_info['y_data'])
        line, = self.axes.plot(
            x_data, y_data,
            label=f"{plot_info['legend_name']}",
            color=plot_info['color'], linestyle=plot_info['linestyle'],
            linewidth=plot_info['linewidth'], zorder=zorder
        )
        return line

    def _setup_plot_appearance(self):
        self.axes.set_xlabel('时间 (s)', fontsize=9)
        self.axes.set_ylabel('百分比 (%)' if self._is_percent_mode() else '数值', fontsize=9)
        self.axes.grid(True, alpha=0.3)
        if self.current_plots:
            lines = list(self.current_plots.values())
            labels = [line.get_label() for line in lines]
            legend = self.axes.legend(lines, labels, loc='upper right', fontsize=8)
            for leg_line in legend.get_lines():
                leg_line.set_linewidth(1.0)
        if self.span_selector:
            self.span_selector.disconnect_events()
        self.span_selector = SpanSelector(self.axes, self._on_span_select, 'horizontal',
                                          useblit=True, props=dict(alpha=0.15, facecolor='#4a6cf7'))

    def _finalize_plot(self):
        self.figure.tight_layout(pad=1.0)
        self.canvas.draw()

    def _is_percent_mode(self):
        main_frame = self.window()
        return not bool(getattr(main_frame.param_panel, 'show_actual_value_channels', set()))

    def _extract_simple_name(self, display_name):
        return display_name.split('|')[1] if '|' in display_name else display_name

    def _on_window_duration_changed(self):
        try:
            duration = float(self.window_duration.text())
            if duration > 0:
                self.x_max = duration
                self.axes.set_xlim(0, self.x_max)
                for right_ax in self.right_axes_dict.values():
                    right_ax.set_xlim(0, self.x_max)
                self.canvas.draw()
                self._update_zoom_status(0, self.x_max, is_duration_change=True)
        except (ValueError, TypeError):
            current_range = self.axes.get_xlim()
            self.window_duration.setText(f"{current_range[1]:.2f}")

    def _on_span_select(self, xmin, xmax):
        if abs(xmax - xmin) < 1e-10:
            center = xmin
            span = max(0.1, center * 0.1)
            xmin, xmax = center - span / 2, center + span / 2
        self.axes.set_xlim(xmin, xmax)
        for right_ax in self.right_axes_dict.values():
            right_ax.set_xlim(xmin, xmax)
        self.canvas.draw()
        self._update_zoom_status(xmin, xmax)

    def _on_mouse_press(self, event):
        if event.inaxes != self.axes:
            return
        if hasattr(event, 'dblclick') and event.dblclick:
            return
        if self.red_line and self._is_near_line(event.xdata, self.red_line_x):
            self.dragging = 'red'
            if self.span_selector:
                self.span_selector.set_active(False)
        elif self.blue_line and self._is_near_line(event.xdata, self.blue_line_x):
            self.dragging = 'blue'
            if self.span_selector:
                self.span_selector.set_active(False)
        else:
            if self.span_selector:
                self.span_selector.set_active(True)

    def _on_mouse_motion(self, event):
        if event.inaxes != self.axes or event.xdata is None or event.ydata is None:
            self._hide_crosshair()
            return
        if self.dragging:
            if self.dragging == 'red':
                self.red_line_x = event.xdata
            elif self.dragging == 'blue':
                self.blue_line_x = event.xdata
            self._update_vertical_lines()
            self._hide_crosshair()
            return
        self._update_crosshair(event.xdata, event.ydata)

    def _update_crosshair(self, x, y):
        if self.crosshair_v is None:
            self.crosshair_v = self.axes.axvline(x=x, color='gray', linewidth=0.5, linestyle='--', alpha=0.6, zorder=20)
        else:
            self.crosshair_v.set_xdata([x, x])
            self.crosshair_v.set_visible(True)
        if self.crosshair_h is None:
            self.crosshair_h = self.axes.axhline(y=y, color='gray', linewidth=0.5, linestyle='--', alpha=0.6, zorder=20)
        else:
            self.crosshair_h.set_ydata([y, y])
            self.crosshair_h.set_visible(True)
        label = f"X={x:.4f}s  Y={y:.4f}"
        if self.crosshair_text is None:
            self.crosshair_text = self.axes.text(
                0.02, 0.98, label, transform=self.axes.transAxes,
                fontsize=8, ha='left', va='top',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.85),
                zorder=25)
        else:
            self.crosshair_text.set_text(label)
            self.crosshair_text.set_visible(True)
        self.canvas.draw_idle()

    def _hide_crosshair(self):
        for obj in [self.crosshair_v, self.crosshair_h, self.crosshair_text]:
            if obj:
                obj.set_visible(False)
        if any([self.crosshair_v, self.crosshair_h, self.crosshair_text]):
            self.canvas.draw_idle()

    def _on_mouse_release(self, event):
        if self.dragging:
            if self.span_selector:
                self.span_selector.set_active(True)
            self.dragging = None

    def _on_navigation(self, event):
        if hasattr(event, 'dblclick') and event.dblclick and event.inaxes == self.axes:
            self._reset_zoom()

    def _on_scroll(self, event):
        if event.inaxes is None:
            return
        target_ax = event.inaxes
        y_min, y_max = target_ax.get_ylim()
        y_range = y_max - y_min
        if abs(y_range) < 1e-15:
            return
        scale_factor = 0.8 if event.button == 'up' else 1.25
        y_center = event.ydata if event.ydata is not None else (y_min + y_max) / 2
        ratio = (y_center - y_min) / y_range
        new_range = y_range * scale_factor
        new_y_min = y_center - new_range * ratio
        new_y_max = y_center + new_range * (1 - ratio)
        target_ax.set_ylim(new_y_min, new_y_max)
        self.canvas.draw_idle()
        main_frame = self.window()
        if hasattr(main_frame, 'status_bar'):
            zoom_action = "放大" if event.button == 'up' else "缩小"
            axis_name = "主Y轴" if target_ax is self.axes else "右侧Y轴"
            status_text = f"Y轴{zoom_action} | {axis_name}范围: {new_y_min:.4f} ~ {new_y_max:.4f}"
            main_frame.status_bar.showMessage(status_text)

    def _on_red_line_toggle(self, state):
        if self.red_line_check.isChecked() and self.red_line_x is None:
            x_range = self.axes.get_xlim()
            self.red_line_x = x_range[0] + (x_range[1] - x_range[0]) * 0.3
        self._update_vertical_lines()

    def _on_blue_line_toggle(self, state):
        if self.blue_line_check.isChecked() and self.blue_line_x is None:
            x_range = self.axes.get_xlim()
            self.blue_line_x = x_range[0] + (x_range[1] - x_range[0]) * 0.7
        self._update_vertical_lines()

    def _update_vertical_lines(self):
        for obj in [self.red_line, self.blue_line,
                    getattr(self, 'red_time_text', None),
                    getattr(self, 'blue_time_text', None),
                    self.red_shadow, self.blue_shadow]:
            if obj and hasattr(obj, 'remove'):
                try:
                    obj.remove()
                except Exception:
                    pass
        self.red_line = self.blue_line = None
        self.red_time_text = self.blue_time_text = None
        self.red_shadow = self.blue_shadow = None

        ylim = self.axes.get_ylim()
        xlim = self.axes.get_xlim()
        y_top = ylim[1] - (ylim[1] - ylim[0]) * 0.05

        main_frame = self.window()
        show_shadow = getattr(main_frame.data_manager, 'show_effective_shadow', False)
        window_size = getattr(main_frame.data_manager, 'effective_value_window', 0.0)

        if self.red_line_check.isChecked() and self.red_line_x is not None:
            if show_shadow and window_size > 0:
                self.red_shadow = self.axes.axvspan(
                    self.red_line_x - window_size, self.red_line_x + window_size,
                    alpha=0.12, color='red', zorder=5)
            self.red_line = self.axes.axvline(x=self.red_line_x, color='red',
                                              linewidth=1, linestyle='-', zorder=10, alpha=0.8)
            self.red_time_text = self.axes.text(
                self.red_line_x + (xlim[1]-xlim[0])*0.005, y_top,
                f"{self.red_line_x:.3f}s", color='red', fontsize=8,
                ha='left', va='bottom', fontweight='bold', zorder=11)

        if self.blue_line_check.isChecked() and self.blue_line_x is not None:
            if show_shadow and window_size > 0:
                self.blue_shadow = self.axes.axvspan(
                    self.blue_line_x - window_size, self.blue_line_x + window_size,
                    alpha=0.12, color='blue', zorder=5)
            self.blue_line = self.axes.axvline(x=self.blue_line_x, color='blue',
                                               linewidth=1, linestyle='-', zorder=10, alpha=0.8)
            self.blue_time_text = self.axes.text(
                self.blue_line_x + (xlim[1]-xlim[0])*0.005, y_top,
                f"{self.blue_line_x:.3f}s", color='blue', fontsize=8,
                ha='left', va='bottom', fontweight='bold', zorder=11)

        self.on_vertical_lines_changed(self.red_line_x, self.blue_line_x)
        self.canvas.draw()

    def _is_near_line(self, x, line_x, threshold=0.01):
        if line_x is None:
            return False
        x_range = self.axes.get_xlim()
        return abs(x - line_x) < (x_range[1] - x_range[0]) * threshold

    def _reset_zoom(self):
        if not self.original_data:
            x_min, x_max = 0, Config.DEFAULT_WINDOW_DURATION
            self.axes.set_xlim(x_min, x_max)
            for right_ax in self.right_axes_dict.values():
                right_ax.set_xlim(x_min, x_max)
            self.canvas.draw()
            return
        try:
            max_time = 0
            for channel_data in self.original_data.values():
                if len(channel_data['x']) > 0:
                    channel_max = np.max(channel_data['x'])
                    max_time = max(max_time, channel_max)
            self.x_max = max_time
            self.window_duration.setText(f"{self.x_max:.2f}")
            self.axes.set_xlim(0, self.x_max)
            for right_ax in self.right_axes_dict.values():
                right_ax.set_xlim(0, self.x_max)
            self._auto_scale_y()
            self.canvas.draw()
            self._update_zoom_status(0, self.x_max, is_reset=True)
        except Exception:
            self.x_max = Config.DEFAULT_WINDOW_DURATION
            self.axes.set_xlim(0, self.x_max)
            for right_ax in self.right_axes_dict.values():
                right_ax.set_xlim(0, self.x_max)
            self.canvas.draw()

    def _auto_scale_y(self):
        if not self.current_plots:
            return
        y_min, y_max = float('inf'), float('-inf')
        for name, line in self.current_plots.items():
            if name not in self.right_axes_dict:
                ydata = line.get_ydata()
                if len(ydata) > 0:
                    y_min = min(y_min, float(np.min(ydata)))
                    y_max = max(y_max, float(np.max(ydata)))
        if y_min != float('inf'):
            if abs(y_max - y_min) < 1e-10:
                y_min, y_max = y_min - 0.1, y_max + 0.1
            else:
                margin = (y_max - y_min) * 0.05
                y_min, y_max = y_min - margin, y_max + margin
            self.axes.set_ylim(y_min, y_max)
        for channel_name, right_ax in self.right_axes_dict.items():
            if channel_name in self.original_data:
                y_data = self.original_data[channel_name]['y']
                y_min, y_max = np.min(y_data), np.max(y_data)
                if abs(y_max - y_min) < 1e-10:
                    y_min, y_max = y_min - 0.1, y_max + 0.1
                else:
                    margin = (y_max - y_min) * 0.05
                    y_min, y_max = y_min - margin, y_max + margin
                right_ax.set_ylim(y_min, y_max)

    def _update_zoom_status(self, xmin, xmax, is_reset=False, is_duration_change=False):
        try:
            main_frame = self.window()
            if not hasattr(main_frame, 'status_bar'):
                return
            duration = xmax - xmin
            if is_reset:
                status_text = f"缩放已复原 | 数据范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s"
            elif is_duration_change:
                status_text = f"窗口时长已设置 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s"
            else:
                data_duration = self.x_max
                zoom_ratio = data_duration / duration if duration > 0 else 1.0
                visible_points = 0
                if hasattr(self, 'original_data') and self.original_data:
                    for channel_data in self.original_data.values():
                        x_data = channel_data['x']
                        visible_points = max(visible_points, np.sum((x_data >= xmin) & (x_data <= xmax)))
                if visible_points > 0:
                    status_text = f"已缩放 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s | 缩放: {zoom_ratio:.1f}x | 数据点: {visible_points}"
                else:
                    status_text = f"已缩放 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s | 缩放: {zoom_ratio:.1f}x"
            main_frame.status_bar.showMessage(status_text)
        except Exception:
            pass

    def on_export_data(self):
        if not self.original_data:
            QMessageBox.information(self, "提示", "没有数据可导出")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "导出数据", "", "CSV files (*.csv);;All files (*.*)")
        if file_path:
            try:
                self._export_data_advanced(file_path)
                QMessageBox.information(self, "成功", f"数据已导出到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出数据失败: {str(e)}")

    def on_export_effective_values(self):
        if not self.current_plots:
            QMessageBox.information(self, "提示", "没有数据可导出")
            return
        has_red_line = self.red_line_x is not None
        has_blue_line = self.blue_line_x is not None
        if not has_red_line and not has_blue_line:
            QMessageBox.information(self, "提示", "请先添加红色或蓝色竖直线")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "导出有效值", "", "CSV files (*.csv);;All files (*.*)")
        if file_path:
            try:
                self._export_effective_values_csv(file_path, has_red_line, has_blue_line)
                QMessageBox.information(self, "成功", f"有效值已导出到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出有效值失败: {str(e)}")

    def on_save_image(self):
        if not self.current_plots:
            QMessageBox.information(self, "提示", "没有图像可保存")
            return
        old_xlabel = self.axes.xaxis.label.get_fontsize()
        old_ylabel = self.axes.yaxis.label.get_fontsize()
        old_tick_label = self.axes.xaxis.get_ticklabels()
        old_tick_size = old_tick_label[0].get_fontsize() if old_tick_label else 9
        legend = self.axes.get_legend()
        old_legend_size = legend.get_texts()[0].get_fontsize() if legend and legend.get_texts() else 8
        crosshair_state = []
        for obj in [self.crosshair_v, self.crosshair_h, self.crosshair_text]:
            if obj is not None:
                crosshair_state.append((obj, obj.get_visible()))
                obj.set_visible(False)

        dlg = SaveImageDialog(self, self)
        result = dlg.exec_()
        settings = dlg.get_settings() if result == QDialog.Accepted else None

        if result != QDialog.Accepted:
            self.axes.xaxis.label.set_fontsize(old_xlabel)
            self.axes.yaxis.label.set_fontsize(old_ylabel)
            self.axes.tick_params(axis='both', labelsize=old_tick_size)
            for right_ax in self.right_axes_dict.values():
                right_ax.yaxis.label.set_fontsize(old_ylabel)
                right_ax.tick_params(axis='y', labelsize=old_tick_size)
            if legend:
                for text in legend.get_texts():
                    text.set_fontsize(old_legend_size)
            for obj, was_visible in crosshair_state:
                obj.set_visible(was_visible)
            self.figure.tight_layout(pad=1.0)
            self.canvas.draw()
            return

        axis_font = settings['axis_font_size']
        legend_font = settings['legend_font_size']
        self.axes.xaxis.label.set_fontsize(axis_font)
        self.axes.yaxis.label.set_fontsize(axis_font)
        self.axes.tick_params(axis='both', labelsize=axis_font)
        for right_ax in self.right_axes_dict.values():
            right_ax.yaxis.label.set_fontsize(axis_font)
            right_ax.tick_params(axis='y', labelsize=axis_font)
        if legend:
            for text in legend.get_texts():
                text.set_fontsize(legend_font)
        self.figure.tight_layout(pad=1.0)
        self.canvas.draw()

        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存图像", "",
            "PNG files (*.png);;JPEG files (*.jpg);;PDF files (*.pdf);;All files (*.*)")
        if file_path:
            try:
                self.figure.savefig(file_path, dpi=300, bbox_inches='tight')
                QMessageBox.information(self, "成功", f"图像已保存到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存图像失败: {str(e)}")

        self.axes.xaxis.label.set_fontsize(old_xlabel)
        self.axes.yaxis.label.set_fontsize(old_ylabel)
        self.axes.tick_params(axis='both', labelsize=old_tick_size)
        for right_ax in self.right_axes_dict.values():
            right_ax.yaxis.label.set_fontsize(old_ylabel)
            right_ax.tick_params(axis='y', labelsize=old_tick_size)
        if legend:
            for text in legend.get_texts():
                text.set_fontsize(old_legend_size)
        for obj, was_visible in crosshair_state:
            obj.set_visible(was_visible)
        self.figure.tight_layout(pad=1.0)
        self.canvas.draw()

    def _export_data_advanced(self, file_path):
        if not self.original_data:
            return
        main_frame = self.window()
        param_panel = main_frame.param_panel
        sample_time_map = {}
        for i in range(param_panel.grid.rowCount()):
            name_item = param_panel.grid.item(i, 0)
            if name_item and name_item.text():
                try:
                    sample_time_map[name_item.text()] = float(param_panel.grid.item(i, 1).text())
                except (ValueError, AttributeError):
                    sample_time_map[name_item.text()] = Config.DEFAULT_SAMPLE_TIME

        groups = {}
        for channel_name, channel_data in self.original_data.items():
            sample_time = sample_time_map.get(channel_name, Config.DEFAULT_SAMPLE_TIME)
            display_name = self._extract_simple_name(channel_name)
            if sample_time not in groups:
                groups[sample_time] = []
            groups[sample_time].append({
                'name': display_name, 'data': channel_data['y'], 'length': len(channel_data['y'])
            })

        with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile)
            headers = []
            group_info = []
            sorted_sample_times = sorted(groups.keys())
            for sample_time in sorted_sample_times:
                channels = groups[sample_time]
                if headers:
                    headers.append("")
                headers.append(f"时间({sample_time}ms)")
                headers.extend(ch['name'] for ch in channels)
                group_info.append({
                    'sample_time': sample_time, 'channels': channels,
                    'max_length': max(ch['length'] for ch in channels)
                })
            writer.writerow(headers)
            overall_max_length = max(info['max_length'] for info in group_info) if group_info else 0
            for i in range(overall_max_length):
                row = []
                for info in group_info:
                    if row:
                        row.append("")
                    sample_time = info['sample_time']
                    channels = info['channels']
                    if i < info['max_length']:
                        row.append(f"{i * sample_time / 1000.0:.6f}")
                        for channel in channels:
                            if i < channel['length']:
                                row.append(f"{channel['data'][i]:.6f}")
                            else:
                                row.append("")
                    else:
                        row.append("")
                        for _ in channels:
                            row.append("")
                writer.writerow(row)

    def _export_effective_values_csv(self, file_path, has_red_line, has_blue_line):
        main_frame = self.window()
        param_panel = main_frame.param_panel
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile)
            parameter_names = []
            red_values, red_effective_values = [], []
            blue_values, blue_effective_values = [], []
            for i in range(param_panel.grid.rowCount()):
                display_item = param_panel.grid.item(i, 0)
                if not display_item or not display_item.text():
                    continue
                display_name = display_item.text()
                legend_item = param_panel.grid.item(i, 7)
                legend_name = legend_item.text().strip() if legend_item else ""
                if not legend_name:
                    legend_name = self._extract_simple_name(display_name)
                parameter_names.append(legend_name)
                if has_red_line:
                    red_values.append(param_panel.grid.item(i, 13).text() if param_panel.grid.item(i, 13) else "")
                    red_effective_values.append(param_panel.grid.item(i, 15).text() if param_panel.grid.item(i, 15) else "")
                if has_blue_line:
                    blue_values.append(param_panel.grid.item(i, 14).text() if param_panel.grid.item(i, 14) else "")
                    blue_effective_values.append(param_panel.grid.item(i, 16).text() if param_panel.grid.item(i, 16) else "")
            headers = ["参数名称"] + parameter_names
            writer.writerow(headers)
            if has_red_line:
                writer.writerow([f"红轴数值({self.red_line_x:.3f}s)"] + red_values)
                writer.writerow([f"红轴有效值({self.red_line_x:.3f}s)"] + red_effective_values)
            if has_blue_line:
                writer.writerow([f"蓝轴数值({self.blue_line_x:.3f}s)"] + blue_values)
                writer.writerow([f"蓝轴有效值({self.blue_line_x:.3f}s)"] + blue_effective_values)

    def clear_plot(self):
        self._clear_plot()
        self.axes.set_xlabel('时间 (s)', fontsize=9)
        self.axes.set_ylabel('数值', fontsize=9)
        self.axes.grid(True, alpha=0.3)
        self.axes.set_xlim(0, self.x_max)
        self.figure.tight_layout()
        self.canvas.draw()
        self.red_line_x = self.blue_line_x = None
        self.red_line_check.setChecked(False)
        self.blue_line_check.setChecked(False)
        self._update_vertical_lines()


# =============================================================================
# FrozenTableWidget - 支持冻结左侧列的 QTableWidget
# =============================================================================
class FrozenTableWidget(QTableWidget):
    """冻结左侧 N 列，水平滚动时保持可见。

    冻结视图共享主表格的 model 和 selectionModel，
    自动同步垂直滚动、行高、选择状态。
    """

    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self._frozen_col_count = 0
        self._frozen_view = QTableView(self)
        self._frozen_view.setModel(self.model())
        self._frozen_view.setSelectionModel(self.selectionModel())
        self._frozen_view.setFocusPolicy(Qt.NoFocus)
        self._frozen_view.verticalHeader().hide()
        self._frozen_view.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self._frozen_view.setAlternatingRowColors(self.alternatingRowColors())
        self._frozen_view.setSelectionBehavior(self.selectionBehavior())
        self._frozen_view.setSelectionMode(self.selectionMode())
        self._frozen_view.hide()
        # 冻结视图不显示自身滚动条（滚动由主表同步）
        self._frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 同步垂直滚动（双向）
        self.verticalScrollBar().valueChanged.connect(
            self._frozen_view.verticalScrollBar().setValue)
        self._frozen_view.verticalScrollBar().valueChanged.connect(
            self.verticalScrollBar().setValue)

        # 同步行高
        self.verticalHeader().sectionResized.connect(self._on_row_resized)
        # 同步默认行高
        self._frozen_view.verticalHeader().setDefaultSectionSize(
            self.verticalHeader().defaultSectionSize())
        # 监听行插入，同步新行行高
        self.model().rowsInserted.connect(self._on_rows_inserted)

    # ---- 公共接口 ----

    def setFrozenColumnCount(self, count):
        """设置冻结的列数（0 = 不冻结）"""
        self._frozen_col_count = count
        if count > 0:
            self._update_frozen_columns()
            self._update_frozen_view_geometry()
            self._frozen_view.show()
        else:
            self._frozen_view.hide()

    def frozenColumnCount(self):
        return self._frozen_col_count

    def frozenView(self):
        """返回冻结视图，供外部设置右键菜单等"""
        return self._frozen_view

    # ---- 内部同步 ----

    def _update_frozen_columns(self):
        total = self.columnCount()
        for col in range(total):
            self._frozen_view.setColumnHidden(col, col >= self._frozen_col_count)
        for col in range(self._frozen_col_count):
            self._frozen_view.setColumnWidth(col, self.columnWidth(col))
        # 同步所有行高
        for row in range(self.rowCount()):
            self._frozen_view.setRowHeight(row, self.rowHeight(row))

    def _on_rows_inserted(self, _parent, first, last):
        """新行插入时同步行高"""
        for row in range(first, last + 1):
            self._frozen_view.setRowHeight(row, self.rowHeight(row))

    def _on_row_resized(self, row, _old, new_size):
        self._frozen_view.setRowHeight(row, new_size)

    def _update_frozen_view_geometry(self):
        if self._frozen_col_count == 0:
            return
        frozen_width = sum(self.columnWidth(c) for c in range(self._frozen_col_count))
        # 从 y=0 开始，覆盖表头 + 内容区域，使表头也冻结
        header_h = self.horizontalHeader().height() if self.horizontalHeader().isVisible() else 0
        # 冻结视图从垂直表头(行号列)右侧开始，避免覆盖行号
        vh_w = self.verticalHeader().width()
        self._frozen_view.setGeometry(
            vh_w, 0, frozen_width, header_h + self.viewport().height())
        # 同步表头高度
        self._frozen_view.horizontalHeader().setFixedHeight(header_h)

    # ---- 重写父类方法，保持冻结视图同步 ----

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_frozen_view_geometry()

    def setColumnWidth(self, col, width):
        super().setColumnWidth(col, width)
        if col < self._frozen_col_count:
            self._frozen_view.setColumnWidth(col, width)
            self._update_frozen_view_geometry()

    def setColumnHidden(self, col, hidden):
        super().setColumnHidden(col, hidden)
        if col < self._frozen_col_count:
            self._frozen_view.setColumnHidden(col, hidden)
            self._update_frozen_view_geometry()

    def setAlternatingRowColors(self, enable):
        super().setAlternatingRowColors(enable)
        self._frozen_view.setAlternatingRowColors(enable)

    def setDefaultRowHeight(self, height):
        """设置默认行高，同时同步到冻结视图"""
        self.verticalHeader().setDefaultSectionSize(height)
        self._frozen_view.verticalHeader().setDefaultSectionSize(height)

    def setSelectionBehavior(self, behavior):
        super().setSelectionBehavior(behavior)
        self._frozen_view.setSelectionBehavior(behavior)

    def setSelectionMode(self, mode):
        super().setSelectionMode(mode)
        self._frozen_view.setSelectionMode(mode)

    def setStyleSheet(self, sheet):
        super().setStyleSheet(sheet)
        # 冻结视图去掉圆角边框，表头与主表头无缝衔接
        self._frozen_view.setStyleSheet(
            "QTableView { border: none; border-radius: 0; }"
            "QHeaderView::section { border: none; }")


# =============================================================================
# PlaceholderLineEdit - 支持自定义 placeholder 颜色的 QLineEdit
# =============================================================================
class PlaceholderLineEdit(QLineEdit):
    """Qt5 中 QSS/QPalette 无法设置 placeholder 颜色，通过 paintEvent 自定义绘制"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ph_color = QColor("#999999")
        self._ph_text = ""

    def setPlaceholderText(self, text):
        self._ph_text = text
        self.update()

    def setPlaceholderColor(self, color):
        self._ph_color = QColor(color)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.text() and self._ph_text:
            painter = QPainter(self)
            painter.setPen(self._ph_color)
            rect = self.cursorRect()
            painter.drawText(rect.x(),
                             rect.y() + (rect.height() - self.fontMetrics().height()) // 2
                             + self.fontMetrics().ascent(),
                             self._ph_text)


# =============================================================================
# ParameterGridPanel
# =============================================================================
class ParameterGridPanel(QWidget):
    """参数表格面板"""

    COLUMNS = [
        "参数名称", "采样间隔(ms)", "绘制曲线", "显示实际值", "曲线颜色",
        "曲线线型", "线宽", "图例名称", "最大值", "最小值", "区域均值",
        "区域最大值", "区域最小值", "红轴数值", "蓝轴数值",
        "红轴有效值", "蓝轴有效值"
    ]
    COL_SIZES = [120, 70, 50, 55, 50, 50, 45, 120, 55, 55, 55, 55, 55, 55, 55, 55, 55]

    def __init__(self, parent, on_parameter_changed_callback):
        super().__init__(parent)
        self.on_parameter_changed = on_parameter_changed_callback
        self.show_actual_value_channels = set()
        self.top_channels = set()
        self._channel_mapping = {}
        self._suppress_redraw = False
        self._next_color_index = 0

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._auto_resize_columns)

        self._create_ui()

    def _create_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 0, 0, 0)

        self.grid = FrozenTableWidget(0, len(self.COLUMNS))
        self.grid.setHorizontalHeaderLabels(self.COLUMNS)
        self.grid.setAlternatingRowColors(True)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        # 显示行号列（行表头）：每一行前显示行号
        vh = self.grid.verticalHeader()
        vh.setVisible(True)
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setFixedWidth(42)
        vh.setDefaultAlignment(Qt.AlignCenter)
        self.grid.setCornerButtonEnabled(True)
        self.grid.setDefaultRowHeight(30)
        self.grid.setShowGrid(True)

        # 设置初始列宽（稍后由 resizeEvent 按比例重新分配）
        for i, size in enumerate(self.COL_SIZES):
            self.grid.setColumnWidth(i, size)
        self.grid.horizontalHeader().setStretchLastSection(False)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

        # 延迟一次自动调整列宽（等待窗口布局完成）
        QTimer.singleShot(100, self._auto_resize_columns)

        # 设置特殊列委托
        self.grid.setItemDelegateForColumn(2, CheckboxDelegate(self.grid))
        self.grid.setItemDelegateForColumn(3, CheckboxDelegate(self.grid))
        self.grid.setItemDelegateForColumn(4, ColorDelegate(self.grid))
        self.grid.setItemDelegateForColumn(5, LineStyleDelegate(self.grid))

        # 线宽列使用 QComboBox 编辑器（通过 setCellWidget 或委托）
        # 为简化，使用普通文本编辑 + 下拉选项
        # 统计列设为只读（通过 Flags）
        self.grid.itemChanged.connect(self._on_cell_changed)
        self.grid.cellDoubleClicked.connect(self._on_cell_double_click)
        self.grid.cellClicked.connect(self._on_cell_left_click)
        self.grid.customContextMenuRequested.connect(self._on_context_menu)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)

        # 冻结参数名称列（第0列），默认不生效，可由右键菜单开启
        self.grid.setFrozenColumnCount(0)
        # 冻结视图也支持右键菜单
        frozen_view = self.grid.frozenView()
        frozen_view.setContextMenuPolicy(Qt.CustomContextMenu)
        frozen_view.customContextMenuRequested.connect(self._on_frozen_context_menu)

        # 表头右键菜单 - 列显示设置
        self.grid.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.horizontalHeader().customContextMenuRequested.connect(self._on_header_context_menu)

        layout.addWidget(self.grid)

    def resizeEvent(self, event):
        """窗口尺寸变化时，按比例自动分配所有列宽，确保全部显示"""
        super().resizeEvent(event)
        self._resize_timer.start(80)

    def _auto_resize_columns(self):
        """按 COL_SIZES 比例分配列宽，使所有可见列都能在可见区域显示"""
        total_width = self.grid.viewport().width()
        if total_width <= 0:
            return
        # 只计算可见列的比例
        visible_cols = [(i, s) for i, s in enumerate(self.COL_SIZES) if not self.grid.isColumnHidden(i)]
        if not visible_cols:
            return
        total_ratio = sum(s for _, s in visible_cols)
        scrollbar_w = 20  # 预留垂直滚动条宽度
        available = total_width - scrollbar_w
        if available <= 0:
            return
        for i, ratio in visible_cols:
            w = int(available * ratio / total_ratio)
            self.grid.setColumnWidth(i, max(w, 40))  # 最小宽度 40

    def _on_header_context_menu(self, pos):
        """表头右键 - 列显示设置"""
        header = self.grid.horizontalHeader()
        self._show_column_settings_menu(header.viewport().mapToGlobal(pos))

    def _show_column_settings_menu(self, global_pos):
        """显示列设置菜单，可勾选要显示的列"""
        menu = QMenu(self)
        show_all = menu.addAction("显示所有列")
        auto_fit = menu.addAction("宽度适应")
        freeze_action = menu.addAction("冻结参数名称列")
        freeze_action.setCheckable(True)
        freeze_action.setChecked(self.grid.frozenColumnCount() > 0)
        menu.addSeparator()
        col_actions = {}
        for col, name in enumerate(self.COLUMNS):
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(not self.grid.isColumnHidden(col))
            col_actions[col] = act
        chosen = menu.exec_(global_pos)
        if chosen == show_all:
            for col in range(len(self.COLUMNS)):
                self.grid.setColumnHidden(col, False)
            self._auto_resize_columns()
        elif chosen == auto_fit:
            self.grid.resizeColumnsToContents()
            for i in range(self.grid.columnCount()):
                if not self.grid.isColumnHidden(i):
                    self.grid.setColumnWidth(i, max(self.grid.columnWidth(i), 50))
        elif chosen == freeze_action:
            self.grid.setFrozenColumnCount(1 if freeze_action.isChecked() else 0)
        elif chosen is not None:
            for col, act in col_actions.items():
                if act == chosen:
                    self.grid.setColumnHidden(col, not act.isChecked())
                    break
            self._auto_resize_columns()

    def _on_context_menu(self, pos):
        item = self.grid.itemAt(pos)
        global_pos = self.grid.viewport().mapToGlobal(pos)
        if item:
            row = item.row()
            self._show_cell_menu(row, global_pos)
        else:
            self._show_blank_area_menu(global_pos)

    def _on_frozen_context_menu(self, pos):
        """冻结列右键菜单 - 转发到单元格菜单"""
        view = self.grid.frozenView()
        index = view.indexAt(pos)
        if index.isValid():
            row = index.row()
            global_pos = view.viewport().mapToGlobal(pos)
            self._show_cell_menu(row, global_pos)

    def _show_blank_area_menu(self, global_pos):
        menu = QMenu(self)
        clear_action = menu.addAction("清除全部参数")
        menu.addSeparator()
        col_setting_action = menu.addAction("列显示设置...")
        menu.addSeparator()
        refresh_action = menu.addAction("刷新表格")
        action = menu.exec_(global_pos)
        if action == clear_action:
            self._on_clear_all_parameters()
        elif action == col_setting_action:
            self._show_column_settings_menu(global_pos)
        elif action == refresh_action:
            self._on_refresh_grid()

    def _show_cell_menu(self, row, global_pos):
        channel_name_item = self.grid.item(row, 0)
        if not channel_name_item:
            return
        channel_name = channel_name_item.text()
        menu = QMenu(self)
        is_top_display = channel_name in self.top_channels
        top_text = "✓ 置顶图层" if is_top_display else "置顶图层"
        top_action = menu.addAction(top_text)
        menu.addSeparator()
        remove_action = menu.addAction("取消绘制")
        action = menu.exec_(global_pos)
        if action == top_action:
            self._on_toggle_top_display(row)
        elif action == remove_action:
            self._on_remove_channel(row)

    def _get_next_color(self):
        if not Config.COLOR_PALETTE:
            return "#FF0000"
        color = Config.COLOR_PALETTE[self._next_color_index]
        self._next_color_index = (self._next_color_index + 1) % len(Config.COLOR_PALETTE)
        return color

    def _on_clear_all_parameters(self):
        if self.grid.rowCount() > 0:
            ret = QMessageBox.question(self, "确认清除",
                                       "确定要清除所有参数吗？此操作不可撤销！",
                                       QMessageBox.Yes | QMessageBox.No,
                                       QMessageBox.No)
            if ret == QMessageBox.Yes:
                self.clear()
                if self.on_parameter_changed:
                    self.on_parameter_changed()
                main_frame = self.window()
                if hasattr(main_frame, 'status_bar'):
                    main_frame.status_bar.showMessage("已清除所有参数")
        else:
            QMessageBox.information(self, "提示", "参数表格中没有任何参数可清除")

    def _on_refresh_grid(self):
        self.grid.viewport().update()
        main_frame = self.window()
        if hasattr(main_frame, 'status_bar'):
            main_frame.status_bar.showMessage("表格已刷新")

    def add_channel(self, display_name, full_path=None):
        row = self.grid.rowCount()
        self.grid.insertRow(row)
        next_color = self._get_next_color()
        legend_default = display_name.split('|')[1] if '|' in display_name else display_name

        items = [
            display_name, "20", "1", "0", next_color,
            Config.LINESTYLE_CHOICES[0], Config.LINEWIDTH_CHOICES[0], legend_default,
            "", "", "", "", "", "", "", "", ""
        ]
        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            if col in (0, 8, 9, 10, 11, 12, 13, 14, 15, 16):
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if col in (2, 3, 4, 5, 6):
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            # 居中对齐
            if col in (1, 6):
                item.setTextAlignment(Qt.AlignCenter)
            # 右对齐（统计列：最大值、最小值及其后所有列）
            if col >= 8:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.grid.setItem(row, col, item)

        if full_path:
            self._channel_mapping[display_name] = full_path
        self.grid.scrollToItem(self.grid.item(row, 0))
        main_frame = self.window()
        if hasattr(main_frame, 'status_bar'):
            main_frame.status_bar.showMessage(f"已添加参数: {display_name} | 颜色: {next_color}")
        if self.on_parameter_changed:
            self.on_parameter_changed()

    def get_visible_channels(self):
        result = set()
        for i in range(self.grid.rowCount()):
            item0 = self.grid.item(i, 0)
            item2 = self.grid.item(i, 2)
            if item0 and item0.text() and item2 and item2.text() == "1":
                result.add(item0.text())
        return result

    def get_show_actual_value_channels(self):
        result = set()
        for i in range(self.grid.rowCount()):
            item0 = self.grid.item(i, 0)
            item3 = self.grid.item(i, 3)
            if item0 and item0.text() and item3 and item3.text() == "1":
                result.add(item0.text())
        return result

    def _get_full_path(self, display_name):
        return self._channel_mapping.get(display_name)

    def clear(self):
        self.grid.setRowCount(0)
        self.show_actual_value_channels.clear()
        self.top_channels.clear()
        self._channel_mapping.clear()
        self._next_color_index = 0

    def _on_cell_changed(self, item):
        if self._suppress_redraw:
            return
        row, col = item.row(), item.column()
        if col == 1:
            new_value = item.text()
            name_item = self.grid.item(row, 0)
            if name_item:
                full_path = self._get_full_path(name_item.text())
                if full_path:
                    file_name = full_path.split('/')[0]
                    for i in range(self.grid.rowCount()):
                        if i == row:
                            continue
                        other_name_item = self.grid.item(i, 0)
                        if other_name_item:
                            other_full = self._get_full_path(other_name_item.text())
                            if other_full and other_full.split('/')[0] == file_name:
                                self._suppress_redraw = True
                                other_item = self.grid.item(i, 1)
                                if other_item:
                                    other_item.setText(new_value)
                                self._suppress_redraw = False
        if self.on_parameter_changed:
            self.on_parameter_changed()

    def _on_cell_left_click(self, row, col):
        if col in (2, 3):
            item = self.grid.item(row, col)
            if item:
                current = item.text()
                new_value = "1" if current != "1" else "0"
                self._suppress_redraw = True
                item.setText(new_value)
                self._suppress_redraw = False
                self.grid.viewport().update()
                if self.on_parameter_changed:
                    self.on_parameter_changed()
        elif col == 4:
            self._show_color_popup(row, col)
        elif col == 5:
            self._show_linestyle_popup(row, col)
        elif col == 6:
            self._show_linewidth_popup(row, col)

    def _show_color_popup(self, row, col):
        item = self.grid.item(row, col)
        if not item:
            return
        popup = ColorPopupWidget(self.grid, Config.COLOR_PALETTE)

        def on_select(hex_code):
            self._suppress_redraw = True
            item.setText(hex_code)
            self._suppress_redraw = False
            if self.on_parameter_changed:
                self.on_parameter_changed()

        popup.color_selected.connect(on_select)
        rect = self.grid.visualRect(self.grid.model().index(row, col))
        pos = self.grid.viewport().mapToGlobal(rect.center())
        popup.move(pos.x() - popup.width() // 2, pos.y() + rect.height() // 2 + 4)
        popup.show()

    def _show_linestyle_popup(self, row, col):
        item = self.grid.item(row, col)
        if not item:
            return
        popup = LineStylePopupWidget(self.grid)

        def on_select(style_name):
            self._suppress_redraw = True
            item.setText(style_name)
            self._suppress_redraw = False
            if self.on_parameter_changed:
                self.on_parameter_changed()

        popup.style_selected.connect(on_select)
        rect = self.grid.visualRect(self.grid.model().index(row, col))
        pos = self.grid.viewport().mapToGlobal(rect.center())
        popup.move(pos.x() - popup.width() // 2, pos.y() + rect.height() // 2 + 4)
        popup.show()

    def _show_linewidth_popup(self, row, col):
        item = self.grid.item(row, col)
        if not item:
            return
        popup = LineWidthPopupWidget(self.grid)

        def on_select(lw):
            self._suppress_redraw = True
            item.setText(lw)
            self._suppress_redraw = False
            if self.on_parameter_changed:
                self.on_parameter_changed()

        popup.width_selected.connect(on_select)
        rect = self.grid.visualRect(self.grid.model().index(row, col))
        pos = self.grid.viewport().mapToGlobal(rect.center())
        popup.move(pos.x() - popup.width() // 2, pos.y() + rect.height() // 2 + 4)
        popup.show()

    def _on_toggle_top_display(self, row):
        item = self.grid.item(row, 0)
        if not item:
            return
        channel_name = item.text()
        if channel_name in self.top_channels:
            self.top_channels.remove(channel_name)
        else:
            self.top_channels.add(channel_name)
        if self.on_parameter_changed:
            self.on_parameter_changed()

    def _on_remove_channel(self, row):
        item = self.grid.item(row, 0)
        if not item:
            return
        channel_name = item.text()
        if channel_name in self.show_actual_value_channels:
            self.show_actual_value_channels.remove(channel_name)
        if channel_name in self.top_channels:
            self.top_channels.remove(channel_name)
        if channel_name in self._channel_mapping:
            del self._channel_mapping[channel_name]
        self.grid.removeRow(row)
        if self.on_parameter_changed:
            self.on_parameter_changed()

    def update_statistics(self, plots_data):
        channel_data_map = {pd['name']: pd for pd in plots_data}
        for i in range(self.grid.rowCount()):
            item = self.grid.item(i, 0)
            if not item or not item.text() or item.text() not in channel_data_map:
                continue
            y_data = channel_data_map[item.text()]['y_data']
            max_val, min_val = np.max(y_data), np.min(y_data)
            self._set_cell(i, 8, f"{float(max_val):.4f}")
            self._set_cell(i, 9, f"{float(min_val):.4f}")

    def _set_cell(self, row, col, text):
        self._suppress_redraw = True
        item = self.grid.item(row, col)
        if item:
            item.setText(text)
        else:
            new_item = QTableWidgetItem(text)
            new_item.setFlags(new_item.flags() & ~Qt.ItemIsEditable)
            if col >= 8:
                new_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.grid.setItem(row, col, new_item)
        self._suppress_redraw = False

    def update_vertical_line_values(self, red_line_x, blue_line_x):
        main_frame = self.window()
        if not hasattr(main_frame, 'plot_panel'):
            return
        plot_panel = main_frame.plot_panel
        for i in range(self.grid.rowCount()):
            item = self.grid.item(i, 0)
            if not item or not item.text():
                continue
            channel_name = item.text()
            for col in range(10, 13):
                self._set_cell(i, col, "")
            if red_line_x is not None:
                red_value = self._get_original_value(plot_panel, channel_name, red_line_x)
                self._set_cell(i, 13, red_value)
                red_effective = self._calculate_effective_value(plot_panel, channel_name, red_line_x)
                self._set_cell(i, 15, red_effective)
            else:
                self._set_cell(i, 13, "")
                self._set_cell(i, 15, "")
            if blue_line_x is not None:
                blue_value = self._get_original_value(plot_panel, channel_name, blue_line_x)
                self._set_cell(i, 14, blue_value)
                blue_effective = self._calculate_effective_value(plot_panel, channel_name, blue_line_x)
                self._set_cell(i, 16, blue_effective)
            else:
                self._set_cell(i, 14, "")
                self._set_cell(i, 16, "")
            if red_line_x is not None and blue_line_x is not None:
                region_start, region_end = sorted([red_line_x, blue_line_x])
                region_stats = self._get_region_statistics(plot_panel, channel_name, region_start, region_end)
                if region_stats:
                    self._set_cell(i, 10, f"{float(region_stats['mean']):.4f}")
                    self._set_cell(i, 11, f"{float(region_stats['max']):.4f}")
                    self._set_cell(i, 12, f"{float(region_stats['min']):.4f}")

    def _calculate_effective_value(self, plot_panel, channel_name, line_x):
        if not hasattr(plot_panel, 'original_data') or channel_name not in plot_panel.original_data:
            return "N/A"
        main_frame = self.window()
        window_size = getattr(main_frame.data_manager, 'effective_value_window', 5.0)
        channel_data = plot_panel.original_data[channel_name]
        x_data, y_data = channel_data['x'], channel_data['y']
        if len(x_data) == 0:
            return "N/A"
        if window_size == 0.0:
            idx = np.argmin(np.abs(x_data - line_x))
            if abs(x_data[idx] - line_x) < 0.1:
                return f"{float(y_data[idx]):.4f}"
            return "N/A"
        start_time, end_time = line_x - window_size, line_x + window_size
        mask = (x_data >= start_time) & (x_data <= end_time)
        window_data = y_data[mask]
        if len(window_data) == 0:
            return "N/A"
        return f"{float(np.mean(window_data)):.4f}"

    def _get_region_statistics(self, plot_panel, channel_name, start_x, end_x):
        if not hasattr(plot_panel, 'original_data') or channel_name not in plot_panel.original_data:
            return None
        channel_data = plot_panel.original_data[channel_name]
        x_data, y_data = channel_data['x'], channel_data['y']
        if len(x_data) == 0:
            return None
        mask = (x_data >= start_x) & (x_data <= end_x)
        region_data = y_data[mask]
        if len(region_data) == 0:
            return None
        return {'mean': np.mean(region_data), 'max': np.max(region_data),
                'min': np.min(region_data), 'count': len(region_data)}

    def _get_original_value(self, plot_panel, channel_name, time_x):
        if not hasattr(plot_panel, 'original_data') or channel_name not in plot_panel.original_data:
            return "N/A"
        channel_data = plot_panel.original_data[channel_name]
        x_data, y_data = channel_data['x'], channel_data['y']
        if len(x_data) == 0:
            return "N/A"
        idx = np.argmin(np.abs(x_data - time_x))
        time_diff = abs(x_data[idx] - time_x)
        return f"{float(y_data[idx]):.4f}" if time_diff <= 0.1 else "N/A"

    def _on_cell_double_click(self, row, col):
        # 可编辑列：采样间隔(1)、图例名称(7) — 线宽(6) 为下拉选择
        if col not in (1, 7):
            return
        item = self.grid.item(row, col)
        if item:
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            # 居中对齐采样间隔
            if col == 1:
                item.setTextAlignment(Qt.AlignCenter)
            self.grid.editItem(item)
            if col == 1:
                def _align_editor():
                    editor = self.grid.viewport().findChild(QLineEdit)
                    if editor:
                        editor.setAlignment(Qt.AlignCenter)
                QTimer.singleShot(0, _align_editor)


# =============================================================================
# UserGuideDialog
# =============================================================================
class UserGuideDialog(QDialog):
    """使用教程对话框——左侧目录树 + 右侧内容区 + 上下页导航"""

    GUIDE_SECTIONS = [
        ("快速入门", [
            "欢迎使用 SignalScape - TDMS 数据可视化分析工具。",
            "【声明】本软件仅限内部使用，禁止对外分发与商业用途。",
            "",
            "本软件用于加载、筛选、绘制和分析 NI TDMS 格式的测试数据文件，支持多文件对比、交互式绘图、统计分析及数据导出。",
            "",
            "基本工作流程：",
            "    1. 点击「打开TDMS文件」或「批量打开」加载数据文件",
            "    2. 在左侧通道树中双击通道，将其加入下方参数表格",
            "    3. 勾选参数表格中的「绘制曲线」列即可在绘图区显示曲线",
            "    4. 使用红蓝竖直线、范围选择、滚轮缩放等工具进行分析",
            "    5. 通过「导出数据」「保存图像」「导出有效值」输出结果",
            "",
            "按钮快捷键（括号内为快捷键，全局生效）：",
            "    打开TDMS文件 (Ctrl+O)    批量打开 (Ctrl+B)    导入选项 (Ctrl+I)",
            "    有效值计算方式 (Ctrl+E)  数据筛选设置 (Ctrl+F)  使用教程 (F1)",
        ]),
        ("数据文件加载", [
            "「打开TDMS文件」按钮",
            "    加载单个 .tdms 文件。若已有文件打开，会询问是「仅打开新文件」还是「添加新文件」。",
            "",
            "「批量打开」按钮",
            "    一次选择多个 .tdms 文件批量加载，带进度提示。",
            "",
            "导入过程说明：",
            "    软件采用惰性加载策略——导入时只读取文件元数据（组/通道名称），不读取具体数据。",
            "    数据在首次绘制时才按需读取并缓存，从而加快大文件导入速度。",
            "",
            "若文件加载失败，软件会自动尝试诊断恢复加载方式（禁用内存映射），并弹出详细错误报告。",
        ]),
        ("导入选项", [
            "「导入选项」按钮",
            "    设置导入时自动跳过的参数名，减少无用参数，加快后续操作。",
            "",
            "参数名包含以下字样（按名称过滤，不读数据，速度最快）：",
            "    故障 / 保留 / 预留 / 备用 / 空闲 / 删除",
            "    勾选后，参数名含对应字样的通道在导入时即被排除，不显示在通道树中。",
            "",
            "修改导入选项后，若过滤选项有变化且有已加载文件，软件会询问是否重新加载以应用新规则。",
        ]),
        ("数据筛选设置", [
            "「数据筛选设置」按钮",
            "    管理通配符排除模式（支持 * 和 ?）。默认排除 *_time、*_status、*_flag 等通道。",
            "",
            "操作说明：",
            "    · 添加：输入新的通配符模式，如 *_temp 排除所有以 _temp 结尾的通道",
            "    · 编辑：修改选中的模式",
            "    · 删除：移除选中的模式",
            "    · 恢复默认：还原为初始的三条排除规则",
            "",
            "「启用数据筛选」复选框可一键开关通配符过滤，而不删除已配置的模式。",
            "注意：关键词过滤（故障/删除等）独立于此开关，始终生效。",
        ]),
        ("有效值计算方式", [
            "「有效值计算方式」按钮",
            "    设置红/蓝竖直线处的有效值计算窗口大小。",
            "",
            "可选方式：",
            "    · 前后10秒平均值（默认）：以竖直线为中心，取 ±10 秒内数据的均值",
            "    · 前后5秒平均值：±5 秒窗口均值",
            "    · 前后3秒平均值：±3 秒窗口均值",
            "    · 前后1秒平均值：±1 秒窗口均值",
            "    · 瞬时值：仅取竖直线所在时刻的单点值",
            "",
            "有效值会显示在参数表格的「红轴有效值」「蓝轴有效值」列，并可通过「导出有效值」按钮导出 CSV。",
            "",
            "显示有效值阴影：",
            "    勾选后，红蓝竖直线两侧会显示半透明阴影区域，宽度等于有效值计算窗口。",
        ]),
        ("通道树与搜索", [
            "左侧通道树",
            "    以「文件 → 组 → 通道」三级结构展示所有已加载的通道。",
            "    · 双击文件/组节点：展开或折叠",
            "    · 双击通道节点：将其加入下方参数表格",
            "    · 右键文件节点：可卸载该文件",
            "",
            "搜索框",
            "    在搜索框输入关键字（不区分大小写），实时过滤通道树。",
            "    匹配范围包括文件名、组名、通道名。清空搜索框可恢复完整树结构。",
        ]),
        ("参数表格", [
            "下方参数表格——管理待绘制的通道及其样式",
            "",
            "可编辑列（采样间隔/绘制曲线/显示实际值/曲线颜色/曲线线型/线宽/图例名称）：",
            "    直接点击对应单元格即可编辑，修改后自动重绘。",
            "",
            "各列说明：",
            "    · 参数名称：显示通道名（多文件时带文件序号前缀）",
            "    · 采样间隔(ms)：决定 X 轴时间轴的计算，修改某通道会联动同文件所有通道",
            "    · 绘制曲线：勾选则在绘图区显示该通道曲线",
            "    · 显示实际值：勾选则为该通道创建独立右侧 Y 轴",
            "    · 曲线颜色：点击弹出调色板选择",
            "    · 曲线线型：点击弹出线型预览选择",
            "    · 线宽：下拉选择 0.5 ~ 3.0",
            "",
            "右键菜单：",
            "    · 置顶图层：将该通道曲线绘制在最上层",
            "    · 取消绘制：从表格中移除该通道",
        ]),
        ("绘图与交互", [
            "绘图区——Matplotlib 交互式图表",
            "",
            "显示模式：",
            "    · 百分比模式（默认）：所有通道归一化到 0~100%，便于对比波形",
            "    · 实际值模式：当有通道勾选「显示实际值」时自动切换",
            "",
            "鼠标交互：",
            "    · 移动鼠标：显示十字光标及坐标标签",
            "    · 拖拽选区：水平框选放大该区域",
            "    · 双击：复原缩放到完整数据范围",
            "    · 滚轮：以鼠标位置为中心缩放 Y 轴",
            "",
            "竖直线工具：",
            "    勾选「红色」「蓝色」复选框显示竖直线，可直接拖拽移动。",
        ]),
        ("数据导出", [
            "绘图区工具栏提供三个导出按钮：",
            "",
            "「导出数据」",
            "    将当前绘制通道的原始数据导出为 CSV。按采样间隔分组。",
            "",
            "「导出有效值」",
            "    将参数表格中所有通道的红/蓝轴数值及有效值导出为 CSV。",
            "",
            "「保存图像」",
            "    将当前绘图保存为 PNG/JPG/PDF。保存前可设置字体大小，支持实时预览。",
        ]),
        ("状态栏", [
            "窗口底部状态栏显示当前操作状态，如加载进度、缩放信息、通道数量等。",
            "    缩放时会显示当前范围、时长、缩放比例及可见数据点数。",
        ]),
        ("快捷操作技巧", [
            "1. 快速分析某时刻值：勾选红色竖直线，拖到目标位置，参数表格「红轴数值」列即显示各通道瞬时值。",
            "",
            "2. 对比区域统计：同时勾选红蓝竖直线，拖到区间两端，「区域均值/最大/最小」列自动计算。",
            "",
            "3. 多文件对比：批量打开多个文件后，参数名会带文件序号前缀。",
            "",
            "4. 加快导入：在「导入选项」中勾选更多关键词过滤项，可减少无用参数显示。",
            "",
            "5. 卸载文件：在通道树中右键文件节点选择「卸载文件」，可释放内存。",
            "",
            "6. 采样间隔联动：修改某通道的采样间隔，同文件的所有通道会同步更新。",
        ]),
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setWindowTitle("SignalScape 使用教程")
        self.resize(900, 640)
        self._current_index = 0
        self._closing = False
        self._create_ui()
        self._select_section(0)

    def _create_ui(self):
        central = QWidget(self)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 左侧目录
        left_panel = QWidget()
        left_panel.setStyleSheet("background-color: #f8f9fb;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 8, 12)

        title = QLabel("  目  录")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #3c5a8c; padding: 4px;")
        left_layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet("""
            QTreeWidget { background-color: transparent; border: none; }
        """)
        for section_title, _ in self.GUIDE_SECTIONS:
            child = QTreeWidgetItem([section_title])
            self.tree.addTopLevelItem(child)
        self.tree.expandAll()
        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.tree.itemClicked.connect(self._on_tree_select)
        left_layout.addWidget(self.tree)

        # 右侧内容
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 12, 12, 12)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #28466e;")
        right_layout.addWidget(self.title_label)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #e0e4ea; max-height: 1px;")
        right_layout.addWidget(line)

        self.content_ctrl = QTextEdit()
        self.content_ctrl.setReadOnly(True)
        self.content_ctrl.setStyleSheet("""
            QTextEdit { background-color: #ffffff; border: none; font-size: 13px; }
        """)
        right_layout.addWidget(self.content_ctrl)

        # 导航按钮
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("◀ 上一页")
        self.prev_btn.setObjectName("secondary")
        self.next_btn = QPushButton("下一页 ▶")
        self.next_btn.setObjectName("secondary")
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondary")
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.next_btn)
        nav_layout.addStretch()
        nav_layout.addWidget(close_btn)
        right_layout.addLayout(nav_layout)

        self.prev_btn.clicked.connect(lambda checked: self._navigate(-1))
        self.next_btn.clicked.connect(lambda checked: self._navigate(1))
        close_btn.clicked.connect(lambda checked: self.accept())

        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 3)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(central)

    def _on_tree_select(self, item):
        if self._closing:
            return
        for i in range(self.tree.topLevelItemCount()):
            if self.tree.topLevelItem(i) is item:
                self._select_section(i)
                return

    def _navigate(self, delta):
        new_idx = self._current_index + delta
        if 0 <= new_idx < len(self.GUIDE_SECTIONS):
            self._select_section(new_idx)

    def _select_section(self, index):
        self._current_index = index
        title, lines = self.GUIDE_SECTIONS[index]
        self.title_label.setText(title)

        # 渲染内容为 HTML，支持 **粗体**
        html_parts = []
        for line in lines:
            if line == "":
                html_parts.append("<br>")
            else:
                # 转义 HTML 特殊字符
                escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                # 处理 **粗体**
                escaped = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', escaped)
                # 空格缩进
                escaped = escaped.replace("    ", "&nbsp;&nbsp;&nbsp;&nbsp;")
                html_parts.append(escaped + "<br>")
        self.content_ctrl.setHtml("<div style='font-family: \"Segoe UI\", \"DejaVu Sans\", \"Microsoft YaHei\", \"SimHei\", sans-serif; font-size: 13px; color: #2d3436; line-height: 1.6;'>" + "".join(html_parts) + "</div>")

        # 同步树选中
        if not self._closing:
            if 0 <= index < self.tree.topLevelItemCount():
                self.tree.setCurrentItem(self.tree.topLevelItem(index))

        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < len(self.GUIDE_SECTIONS) - 1)


# =============================================================================
# HoverButton
# =============================================================================
class HoverButton(QPushButton):
    """无边框按钮——默认透明，鼠标悬停时显示底色"""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px 12px;
                color: #4a5568;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #e8f0fe;
                border-color: #c5d8f7;
                color: #4a6cf7;
            }
            QPushButton:pressed {
                background-color: #d0e0fd;
            }
        """)


# =============================================================================
# SignalScapeMainWindow
# =============================================================================
class SignalScapeMainWindow(QMainWindow):
    """主窗口类"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SignalScape - TDMS数据可视化工具")

        self.data_manager = DataManager()

        # 防抖定时器
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.timeout.connect(self._on_redraw_timer)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._perform_search)

        self._create_ui()
        self._create_button_bar()
        self._create_status_bar()
        self._setup_shortcuts()
        self.showMaximized()

    def _create_button_bar(self):
        """创建按钮栏"""
        bar = QToolBar(self)
        bar.setMovable(False)
        bar.setIconSize(QSize(16, 16))
        bar.setStyleSheet("""
            QToolBar { background-color: #ffffff; border-bottom: 1px solid #e0e4ea; padding: 2px 8px; spacing: 4px; }
        """)

        buttons = [
            ("打开TDMS文件", self._on_open, "Ctrl+O"),
            ("批量打开", self._on_batch_open, "Ctrl+B"),
            ("导入选项", self._on_import_options, "Ctrl+I"),
            ("有效值计算方式", self._on_effective_value_settings, "Ctrl+E"),
            ("数据筛选设置", self._on_filter_settings, "Ctrl+F"),
            ("使用教程", self._on_show_guide, "F1"),
        ]

        for i, (name, handler, key_text) in enumerate(buttons):
            if i in (2, 5):
                bar.addSeparator()
            btn = HoverButton(f"{name} ({key_text})", bar)
            btn.setToolTip(f"{name}    快捷键: {key_text}")
            btn.clicked.connect(handler)
            bar.addWidget(btn)

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)

    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_splitter_proportions()

    def _setup_shortcuts(self):
        shortcuts = [
            ("Ctrl+O", self._on_open),
            ("Ctrl+B", self._on_batch_open),
            ("Ctrl+I", self._on_import_options),
            ("Ctrl+E", self._on_effective_value_settings),
            ("Ctrl+F", self._on_filter_settings),
            ("F1", self._on_show_guide),
        ]
        for key, handler in shortcuts:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(handler)

    def _on_filter_settings(self):
        dlg = FilterConfigDialog(self, self.data_manager)
        dlg.exec_()

    def _on_show_guide(self):
        dlg = UserGuideDialog(self)
        dlg.exec_()

    def _create_ui(self):
        """创建主界面"""
        central = QWidget()
        self.setCentralWidget(central)

        self.main_splitter = QSplitter(Qt.Horizontal)
        left_panel = self._create_left_panel()
        right_panel = self._create_right_panel()
        self.main_splitter.addWidget(left_panel)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setChildrenCollapsible(False)
        # 延迟到窗口显示后按比例设置分割位置
        QTimer.singleShot(50, self._update_splitter_proportions)
        self.main_splitter.splitterMoved.connect(lambda: setattr(self, '_user_resized', True))
        self._user_resized = False

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.main_splitter)

    def _update_splitter_proportions(self):
        """按 25%:75% 的比例设置左右分割区"""
        if self._user_resized:
            return
        total = self.main_splitter.width()
        if total > 0:
            left = int(total * 0.25)
            self.main_splitter.setSizes([left, total - left])

    def _create_left_panel(self):
        panel = QWidget()
        panel.setStyleSheet("background-color: #f8f9fb;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 搜索框
        search_layout = QHBoxLayout()
        search_label = QLabel(" 搜索：")
        search_label.setStyleSheet("font-size: 13px; color: #4a5568;")
        search_layout.addWidget(search_label)
        self.search_ctrl = PlaceholderLineEdit()
        self.search_ctrl.setPlaceholderText("输入关键字过滤通道...")
        self.search_ctrl.textChanged.connect(self._on_search_text_change)
        self.search_ctrl.setFixedHeight(28)
        self.search_ctrl.setStyleSheet("padding: 3px 10px;")
        search_layout.addWidget(self.search_ctrl)
        layout.addLayout(search_layout)

        # 通道树
        self.channel_tree = QTreeWidget()
        self.channel_tree.setHeaderHidden(True)
        layout.addWidget(self.channel_tree, 1)

        self.channel_tree.itemDoubleClicked.connect(self._on_channel_activated)
        self.channel_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.channel_tree.customContextMenuRequested.connect(self._on_tree_context_menu)

        return panel

    def _on_tree_context_menu(self, pos):
        item = self.channel_tree.itemAt(pos)
        if not item:
            return
        # 仅文件节点（顶层节点）显示右键菜单
        parent = item.parent()
        if parent is None and item.childCount() > 0:
            menu = QMenu(self)
            unload_action = menu.addAction("卸载文件")
            action = menu.exec_(self.channel_tree.viewport().mapToGlobal(pos))
            if action == unload_action:
                self._on_unload_file(item)

    def _on_search_text_change(self):
        self._search_timer.start(250)

    def _perform_search(self):
        search_term = self.search_ctrl.text().strip()
        if not search_term:
            self._rebuild_full_tree()
            self.status_bar.showMessage("就绪")
            return

        self.channel_tree.clear()
        matched_count = 0
        search_term_lower = search_term.lower()

        for file_name, groups in self.data_manager.files_data.items():
            file_item = None
            file_matched = search_term_lower in file_name.lower()
            if file_matched:
                file_item = QTreeWidgetItem([file_name])
                self.channel_tree.addTopLevelItem(file_item)
                matched_count += 1

            for group_name, channels in groups.items():
                group_item = None
                group_matched = search_term_lower in group_name.lower()
                if group_matched:
                    if not file_item:
                        file_item = QTreeWidgetItem([file_name])
                        self.channel_tree.addTopLevelItem(file_item)
                    group_item = QTreeWidgetItem([group_name])
                    file_item.addChild(group_item)
                    matched_count += 1

                for channel_name in channels.keys():
                    if search_term_lower in channel_name.lower():
                        if not file_item:
                            file_item = QTreeWidgetItem([file_name])
                            self.channel_tree.addTopLevelItem(file_item)
                        if not group_item:
                            group_item = QTreeWidgetItem([group_name])
                            file_item.addChild(group_item)
                        ch_item = QTreeWidgetItem([channel_name])
                        group_item.addChild(ch_item)
                        matched_count += 1

            if file_item:
                self.channel_tree.expandItem(file_item)
                for i in range(file_item.childCount()):
                    self.channel_tree.expandItem(file_item.child(i))

        if matched_count > 0:
            self.status_bar.showMessage(f"搜索: '{search_term}' | 找到 {matched_count} 个结果")
        else:
            self.status_bar.showMessage(f"搜索: '{search_term}' | 未找到匹配项")
            no_item = QTreeWidgetItem(["无匹配项"])
            no_item.setForeground(0, QColor(150, 150, 150))
            self.channel_tree.addTopLevelItem(no_item)

    def _create_right_panel(self):
        panel = QWidget()
        right_splitter = QSplitter(Qt.Vertical)

        self.plot_panel = MatplotlibPlotPanel(right_splitter, self._on_vertical_lines_changed)
        self.param_panel = ParameterGridPanel(right_splitter, self._on_parameter_changed)

        right_splitter.addWidget(self.plot_panel)
        right_splitter.addWidget(self.param_panel)
        right_splitter.setChildrenCollapsible(False)
        QTimer.singleShot(100, lambda: right_splitter.setSizes([600, 300]))

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(right_splitter)
        return panel

    def _on_open(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开TDMS文件", "", "TDMS files (*.tdms);;All files (*.*)")
        if file_path:
            self._handle_file_open(file_path)

    def _on_batch_open(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "批量打开TDMS文件", "", "TDMS files (*.tdms);;All files (*.*)")
        if not file_paths:
            return

        bridge = SignalBridge()
        progress_dialog = ProgressDialog(self, "批量加载", f"正在批量加载 {len(file_paths)} 个文件")
        progress_dialog.setWindowModality(Qt.ApplicationModal)
        bridge.progress_update.connect(progress_dialog.update_progress)
        bridge.load_done.connect(progress_dialog.close_dialog)
        bridge.tree_update.connect(self._update_channel_tree)
        bridge.status_message.connect(self.status_bar.showMessage)
        bridge.show_info.connect(
            lambda t, m: QTimer.singleShot(100, lambda: QMessageBox.information(self, t, m)))

        progress_dialog.show()
        bridge.progress_update.emit(0, f"正在批量加载 {len(file_paths)} 个文件")

        total = len(file_paths)
        success_count = [0]
        error_msgs = []
        self.data_manager._cancel_load = False
        progress_dialog.load_cancelled.connect(lambda: setattr(self.data_manager, '_cancel_load', True))
        progress_dialog.load_cancelled.connect(progress_dialog.close_dialog)

        def worker():
            self.data_manager._last_excluded_count = 0
            self.data_manager._last_load_error = None
            for i, file_path in enumerate(file_paths):
                if self.data_manager._cancel_load:
                    break
                file_name = osp.basename(file_path)
                progress = int((i / total) * 100)
                bridge.progress_update.emit(progress, f"正在加载: {file_name}")
                if file_name in self.data_manager.files_data:
                    continue
                if self.data_manager.load_tdms_file(file_path, parent_window=self):
                    bridge.tree_update.emit(file_name)
                    success_count[0] += 1
                elif self.data_manager._last_load_error:
                    error_msgs.append(f"{file_name}: {self.data_manager._last_load_error[1]}")
                    self.data_manager._last_load_error = None
            total_excluded = self.data_manager._last_excluded_count
            self.data_manager._last_excluded_count = 0
            bridge.progress_update.emit(100, "批量加载完成")
            if self.data_manager._cancel_load:
                feedback = f"已取消 | 成功加载 {success_count[0]}/{len(file_paths)} 个文件"
            else:
                feedback = f"已成功加载 {success_count[0]}/{total} 个文件"
            if total_excluded > 0:
                feedback += f" | 已排除 {total_excluded} 个通道"
            if error_msgs:
                feedback += " | 加载失败: " + "; ".join(error_msgs[:3])
            bridge.status_message.emit(feedback)
            bridge.load_done.emit()

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _handle_file_open(self, file_path):
        file_name = osp.basename(file_path)
        if file_name in self.data_manager.files_data:
            QMessageBox.information(self, "提示", f"文件 '{file_name}' 已经打开！")
            return
        if self.data_manager.files_data:
            result = self._show_file_open_dialog()
            if result == 0:  # 仅打开新文件
                self.data_manager.clear()
                self.channel_tree.clear()
                self.param_panel.clear()
                self.plot_panel.clear_plot()
            elif result == 2:  # 取消
                return
            # result == 1: 添加新文件

        def on_load_finished(loaded_file_path, success):
            if success:
                self._update_channel_tree(osp.basename(loaded_file_path))
                self._update_status_after_load(osp.basename(loaded_file_path))
                self.status_bar.showMessage(f"已加载: {osp.basename(loaded_file_path)}")
            else:
                QMessageBox.critical(self, "错误", f"加载文件失败: {osp.basename(loaded_file_path)}")
                self.status_bar.showMessage("文件加载失败")

        self.data_manager.load_tdms_file_with_progress(
            file_path, parent_window=self, on_finish_callback=on_load_finished)

    def _show_file_open_dialog(self):
        """返回 0=仅打开新文件, 1=添加新文件, 2=取消"""
        file_count = len(self.data_manager.files_data)
        current_files = ", ".join(list(self.data_manager.files_data.keys())[:3])
        if file_count > 3:
            current_files += f" 等 {file_count} 个文件"
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("打开文件选项")
        msg_box.setText(f"当前已打开 {file_count} 个文件:\n{current_files}\n\n请选择打开方式:")
        btn_new = msg_box.addButton("仅打开新文件", QMessageBox.ButtonRole.AcceptRole)
        btn_add = msg_box.addButton("添加新文件", QMessageBox.ButtonRole.AcceptRole)
        btn_cancel = msg_box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        msg_box.exec_()
        clicked = msg_box.clickedButton()
        if clicked is btn_new:
            return 0
        elif clicked is btn_add:
            return 1
        return 2

    def _update_status_after_load(self, file_name):
        stats = self.data_manager.get_file_stats(file_name)
        status_text = f"已加载: {file_name} | 组数: {stats['groups']} | 通道数: {stats['channels']} | 就绪"
        self.status_bar.showMessage(status_text)

    def _on_effective_value_settings(self):
        dlg = EffectiveValueDialog(self, self.data_manager)
        if dlg.exec_() == QDialog.Accepted:
            method_name, window, show_shadow = dlg.GetSelectedMethod()
            self.data_manager.effective_value_method = method_name
            self.data_manager.effective_value_window = window
            self.data_manager.show_effective_shadow = show_shadow
            self.status_bar.showMessage(f"有效值计算方法: {method_name}")
            self._update_effective_values()
            self.plot_panel.sync_shadow_check()
            self.plot_panel._update_vertical_lines()

    def _on_import_options(self):
        dlg = ImportOptionsDialog(self, self.data_manager)
        result = dlg.exec_()
        changed = False
        if result == QDialog.Accepted:
            dm = self.data_manager
            old_values = (dm.skip_fault_params, dm.skip_reserve_params, dm.skip_predefined_params,
                          dm.skip_standby_params, dm.skip_idle_params, dm.skip_delete_params)
            dlg._save_settings()
            new_values = (dm.skip_fault_params, dm.skip_reserve_params, dm.skip_predefined_params,
                          dm.skip_standby_params, dm.skip_idle_params, dm.skip_delete_params)
            changed = (old_values != new_values)
        if changed and self.data_manager.files_data:
            ret = QMessageBox.question(self, "应用导入选项",
                                       "导入选项已更新。\n\n要重新加载当前文件以应用新的过滤规则吗？",
                                       QMessageBox.Yes | QMessageBox.No)
            if ret == QMessageBox.Yes:
                self._reload_all_files()

    def _reload_all_files(self):
        file_paths = list(self.data_manager.file_paths.values())
        if not file_paths:
            return
        self.data_manager.clear()
        self.channel_tree.clear()
        self.param_panel.clear()
        self.plot_panel.clear_plot()

        bridge = SignalBridge()
        progress_dialog = ProgressDialog(self, "重新加载", f"正在重新加载 {len(file_paths)} 个文件")
        progress_dialog.setWindowModality(Qt.ApplicationModal)
        bridge.progress_update.connect(progress_dialog.update_progress)
        bridge.load_done.connect(progress_dialog.close_dialog)
        bridge.tree_update.connect(self._update_channel_tree)
        bridge.status_message.connect(self.status_bar.showMessage)

        progress_dialog.show()
        total = len(file_paths)
        success_count = [0]
        self.data_manager._cancel_load = False
        progress_dialog.load_cancelled.connect(lambda: setattr(self.data_manager, '_cancel_load', True))
        progress_dialog.load_cancelled.connect(progress_dialog.close_dialog)

        def worker():
            for i, file_path in enumerate(file_paths):
                if self.data_manager._cancel_load:
                    break
                fn = osp.basename(file_path)
                p = int((i / total) * 100)
                bridge.progress_update.emit(p, f"正在加载: {fn}")
                if self.data_manager.load_tdms_file(file_path, parent_window=self):
                    bridge.tree_update.emit(fn)
                    success_count[0] += 1
            bridge.progress_update.emit(100, "重新加载完成")
            bridge.status_message.emit(f"已重新加载 {success_count[0]}/{total} 个文件")
            bridge.load_done.emit()

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _update_effective_values(self):
        if hasattr(self.plot_panel, 'red_line_x') or hasattr(self.plot_panel, 'blue_line_x'):
            self._on_vertical_lines_changed(
                getattr(self.plot_panel, 'red_line_x', None),
                getattr(self.plot_panel, 'blue_line_x', None))

    def _on_channel_activated(self, item):
        if not item:
            return
        parent = item.parent()
        root = self.channel_tree.invisibleRootItem()
        # 顶层节点（文件节点）：展开/折叠
        if parent is None or parent is root:
            idx = self.channel_tree.indexFromItem(item)
            if self.channel_tree.isExpanded(idx):
                self.channel_tree.collapseItem(item)
            else:
                self.channel_tree.expandItem(item)
            return
        # 通道节点（无子节点）
        if item.childCount() == 0:
            self._add_channel_to_grid(item)

    def _add_channel_to_grid(self, item):
        channel_name = item.text(0)
        parent = item.parent()
        if parent is None:
            return
        group_name = parent.text(0)
        file_item = parent.parent()
        if file_item is None:
            return
        file_name = file_item.text(0)
        full_path = f"{file_name}/{group_name}/{channel_name}"
        display_name = self._generate_display_name(channel_name, file_name)

        # 检查是否已存在
        exists = any(
            self.param_panel.grid.item(i, 0) and self.param_panel.grid.item(i, 0).text() == display_name
            for i in range(self.param_panel.grid.rowCount())
        )
        if not exists:
            self.param_panel.add_channel(display_name, full_path)
            self.status_bar.showMessage(f"已选择: {display_name}")
            self._redraw_timer.stop()
            self._plot_selected_channels()

    def _generate_display_name(self, channel_name, file_name):
        if len(self.data_manager.files_data) > 1:
            file_list = list(self.data_manager.files_data.keys())
            file_index = file_list.index(file_name) + 1
            return f"文件{file_index}|{channel_name}"
        return channel_name

    def _on_unload_file(self, file_item):
        file_name = file_item.text(0)
        ret = QMessageBox.question(self, "确认卸载",
                                   f"确定要卸载文件 '{file_name}' 吗？相关的参数将被清除。",
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.No)
        if ret == QMessageBox.Yes:
            removed_count = self._remove_channels_from_grid(file_name)
            self.data_manager.unload_file(file_name)
            idx = self.channel_tree.indexOfTopLevelItem(file_item)
            self.channel_tree.takeTopLevelItem(idx)
            self._redraw_timer.stop()
            self._plot_selected_channels()
            status_text = f"已卸载文件: {file_name}"
            if removed_count > 0:
                status_text += f" | 已移除 {removed_count} 个相关参数"
            remaining_files = len(self.data_manager.files_data)
            status_text += f" | 剩余文件: {remaining_files}"
            self.status_bar.showMessage(status_text)

    def _remove_channels_from_grid(self, file_name):
        rows_to_remove = []
        removed_count = 0
        for i in range(self.param_panel.grid.rowCount()):
            item = self.param_panel.grid.item(i, 0)
            if not item or not item.text():
                continue
            if self._is_channel_from_file(item.text(), file_name):
                rows_to_remove.append(i)
        for i in sorted(rows_to_remove, reverse=True):
            item = self.param_panel.grid.item(i, 0)
            if item:
                channel_name = item.text()
                if channel_name in self.param_panel.show_actual_value_channels:
                    self.param_panel.show_actual_value_channels.remove(channel_name)
                if channel_name in self.param_panel.top_channels:
                    self.param_panel.top_channels.remove(channel_name)
                if channel_name in self.param_panel._channel_mapping:
                    del self.param_panel._channel_mapping[channel_name]
            self.param_panel.grid.removeRow(i)
            removed_count += 1
        return removed_count

    def _is_channel_from_file(self, channel_name, file_name):
        if channel_name in self.param_panel._channel_mapping:
            full_path = self.param_panel._channel_mapping[channel_name]
            return full_path.startswith(file_name + "/")
        return False

    def _on_parameter_changed(self):
        self._redraw_timer.start(150)

    def _on_redraw_timer(self):
        self._plot_selected_channels()

    def _on_vertical_lines_changed(self, red_line_x=None, blue_line_x=None):
        self.param_panel.update_vertical_line_values(red_line_x, blue_line_x)

    def _plot_selected_channels(self):
        if not self.param_panel.grid.rowCount():
            self.plot_panel.clear_plot()
            return
        plots_data = []
        parameters = {}
        visible_channels = self.param_panel.get_visible_channels()
        for i in range(self.param_panel.grid.rowCount()):
            item0 = self.param_panel.grid.item(i, 0)
            if not item0 or not item0.text() or item0.text() not in visible_channels:
                continue
            full_path = self.param_panel._get_full_path(item0.text())
            if not full_path:
                continue
            param_info = self._get_channel_parameters(i, item0.text(), full_path)
            if param_info:
                parameters[item0.text()] = param_info
        for display_name, param_info in parameters.items():
            channel_data = self._get_channel_data(param_info['full_path'])
            if channel_data is not None:
                time_axis = np.arange(len(channel_data)) * param_info['sample_time'] / 1000.0
                plots_data.append({'x_data': time_axis, 'y_data': channel_data, 'name': display_name})
        if plots_data:
            show_actual_channels = self.param_panel.get_show_actual_value_channels()
            self.plot_panel.plot(plots_data, parameters, show_actual_channels, self.param_panel.top_channels)
            self.param_panel.update_statistics(plots_data)
            visible_count = len(visible_channels)
            plotted_count = len(plots_data)
            self.status_bar.showMessage(f"可见通道: {visible_count} | 已绘制: {plotted_count} | 就绪")
        else:
            self.plot_panel.clear_plot()

    def _get_channel_parameters(self, row, display_name, full_path):
        try:
            sample_time = float(self.param_panel.grid.item(row, 1).text())
        except (ValueError, AttributeError):
            sample_time = Config.DEFAULT_SAMPLE_TIME
        try:
            linewidth = float(self.param_panel.grid.item(row, 6).text())
        except (ValueError, AttributeError):
            linewidth = Config.DEFAULT_LINEWIDTH
        linestyle_item = self.param_panel.grid.item(row, 5)
        linestyle = linestyle_item.text() if linestyle_item else "实线"
        linestyle_val = Config.LINESTYLE_MAP.get(linestyle, '-')
        legend_item = self.param_panel.grid.item(row, 7)
        legend_name = legend_item.text().strip() if legend_item else ""
        if not legend_name:
            legend_name = display_name.split('|')[1] if '|' in display_name else display_name
        color_item = self.param_panel.grid.item(row, 4)
        color = color_item.text() if color_item else "#1f77b4"
        return {
            'sample_time': sample_time, 'color': color, 'linestyle': linestyle_val,
            'linewidth': linewidth, 'legend_name': legend_name, 'full_path': full_path
        }

    def _get_channel_data(self, full_path):
        parts = full_path.split('/')
        if len(parts) == 3:
            file_name, group_name, channel_name = parts
            return self.data_manager.get_channel_data(file_name, group_name, channel_name)
        return None

    def _update_channel_tree(self, file_name):
        if file_name not in self.data_manager.files_data:
            return
        file_item = QTreeWidgetItem([file_name])
        self.channel_tree.addTopLevelItem(file_item)
        for group_name, channels in self.data_manager.files_data[file_name].items():
            group_item = QTreeWidgetItem([group_name])
            file_item.addChild(group_item)
            for channel_name in channels.keys():
                ch_item = QTreeWidgetItem([channel_name])
                group_item.addChild(ch_item)
        self.channel_tree.expandItem(file_item)

    def _rebuild_full_tree(self):
        self.channel_tree.clear()
        if not self.data_manager.files_data:
            return
        for file_name in self.data_manager.files_data.keys():
            self._update_channel_tree(file_name)


# =============================================================================
# 主入口
# =============================================================================
def _resolve_app_icon():
    """兼容 开发环境 / onedir 目录版 / onefile 单文件版 三种情况下定位 Dashboard.ico"""
    candidates = []
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):                       # 单文件版
            candidates.append(os.path.join(sys._MEIPASS, "Dashboard.ico"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "Dashboard.ico"))  # 目录版
    else:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "Dashboard.ico"))
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def main():
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    # 修复任务栏图标（PyInstaller 单文件版从临时目录运行会导致任务栏图标错乱）
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p("SignalScape.App.1.0"))
    except Exception:
        pass

    # Qt5 需要手动设置 DPI 缩放（Qt6 默认启用高 DPI 缩放）
    # 获取屏幕 DPI 并设置 QT_SCALE_FACTOR，确保 QSS 中的 px 单位正确缩放
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi > 0:
            os.environ['QT_SCALE_FACTOR'] = str(dpi / 96.0)
    except Exception:
        os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    app.setApplicationName("SignalScape")

    # 修复标题栏/任务栏图标
    icon_path = _resolve_app_icon()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    window = SignalScapeMainWindow()
    if icon_path:
        window.setWindowIcon(QIcon(icon_path))
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
