import wx
import wx.grid
import threading
import warnings
import os
import os.path as osp
import csv
import fnmatch
import re
import matplotlib as mpl
from collections import OrderedDict
import gc

# 抑制 libpng iCCP sRGB 警告（来自 matplotlib 内嵌 PNG 资源，不影响功能）
warnings.filterwarnings('ignore', message='.*iCCP.*')
os.environ['PIL_WARNINGS'] = '0'  # 关闭 PIL/Pillow 的 iCCP 警告

# 配置matplotlib
mpl.use('WXAgg')
mpl.rcParams.update({
    'path.simplify': True,
    'path.simplify_threshold': 1.0,
    'agg.path.chunksize': 10000,
    'font.sans-serif': ['SimHei', 'Microsoft YaHei', 'DejaVu Sans'],
    'axes.unicode_minus': False,
    'font.size': 9
})

from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector


# ---------------------------------------------------------------------------
# 延迟加载 numpy / nptdms —— 启动时不导入，首次打开文件时再加载，以加快启动速度
# ---------------------------------------------------------------------------
_data_modules_loaded = False


def ensure_data_modules(progress_callback=None):
    """按需导入 numpy 和 nptdms。

    progress_callback(value, message): 进度回调，value 报告 0-30 区间，
    预留 30-100 给后续文件加载阶段。
    """
    global _data_modules_loaded
    if _data_modules_loaded:
        return

    # 阶段1: numpy (0-15%)
    if progress_callback:
        progress_callback(5, "正在加载 numpy 模块...")
    import numpy as np
    globals()['np'] = np
    if progress_callback:
        progress_callback(15, "numpy 模块加载完成")

    # 阶段2: nptdms (15-30%)
    if progress_callback:
        progress_callback(20, "正在加载 nptdms 模块...")
    from nptdms import TdmsFile
    globals()['TdmsFile'] = TdmsFile
    if progress_callback:
        progress_callback(30, "nptdms 模块加载完成")

    _data_modules_loaded = True


def _set_status_text_safe(status_bar, text, field_index=0):
    """安全更新状态栏文本（单字段状态栏直接设置，不会被截断）。"""
    if not status_bar:
        return
    try:
        fields = status_bar.GetFieldsCount()
        if field_index < fields:
            status_bar.SetStatusText(text, field_index)
    except Exception:
        pass
        # 测量失败时回退到直接设置文本
        try:
            status_bar.SetStatusText(text, field_index)
        except Exception:
            pass


class Config:
    """配置常量类"""
    DEFAULT_SAMPLE_TIME = 20.0
    DEFAULT_WINDOW_DURATION = 10.0
    DEFAULT_LINEWIDTH = 0.5
    EFFECTIVE_VALUE_METHODS = {
        "瞬时值": 0.0,
        "前后1秒平均值": 1.0,
        "前后3秒平均值": 3.0,
        "前后5秒平均值": 5.0,
        "前后10秒平均值": 10.0
    }
    COLOR_PALETTE = [
        "#1f77b4",  # tableau blue
        "#ff7f0e",  # tableau orange
        "#2ca02c",  # tableau green
        "#d62728",  # tableau red
        "#9467bd",  # tableau purple
        "#8c564b",  # tableau brown
        "#e377c2",  # tableau pink
        "#7f7f7f",  # tableau gray
        "#bcbd22",  # tableau olive
        "#17becf",  # tableau cyan
        "#aec7e8",  # light blue
        "#ffbb78",  # light orange
        "#98df8a",  # light green
        "#ff9896",  # light red
        "#c5b0d5",  # light purple
        "#c49c94",  # light brown
        "#f7b6d2",  # light pink
        "#c7c7c7",  # light gray
    ]
    LINESTYLE_MAP = {
        '实线': '-',
        '虚线': '--',
        '点线': ':',
        '点划线': '-.'
    }
    LINESTYLE_CHOICES = list(LINESTYLE_MAP.keys())
    LINEWIDTH_CHOICES = ['0.5', '1.0', '1.5', '2.0', '2.5', '3.0']


class DataManager:
    """数据管理类 - 惰性加载TDMS数据"""
    def __init__(self):
        self.files_data = OrderedDict()
        self.tdms_files = {}  # 保持 TdmsFile 对象打开，支持惰性读取
        self.file_paths = {}  # 文件名 → 完整路径，用于重新加载
        self._data_cache = {}  # 通道数据缓存（按需读取后缓存），键为 (file,group,channel)，值为 ndarray
        self.sample_time = Config.DEFAULT_SAMPLE_TIME
        self.effective_value_method = "前后10秒平均值"
        self.effective_value_window = 10.0
        self.show_effective_shadow = False  # 是否在竖直线处显示有效值阴影
        self._loading_lock = threading.Lock()
        self.filter_enabled = True
        self.exclude_patterns = ['*_time', '*_status', '*_flag']
        # 导入过滤选项（默认全部启用）
        self.skip_fault_params = True
        self.skip_reserve_params = True
        self.skip_predefined_params = True
        self.skip_standby_params = True
        self.skip_idle_params = True
        self.skip_delete_params = True
        # 导入取消标记
        self._cancel_load = False


    def load_tdms_file(self, file_path: str, progress_callback=None) -> bool:
        """
        真正的文件加载逻辑，含主要加载与诊断恢复路径。
        """
        file_name = osp.basename(file_path)
        # 在主线程中预注册文件名
        if file_name in self.files_data:
            return False
        self.files_data[file_name] = {}
        self.file_paths[file_name] = file_path  # 保存完整路径用于重新加载

        # --- 主要加载方法（惰性加载：只读元数据，不读数据） ---
        try:
            # 保持 TdmsFile 打开（不用 with），后续按需读取数据
            tdms_file = TdmsFile.open(file_path)
            self.tdms_files[file_name] = tdms_file
            return self._process_tdms_data(tdms_file, file_name, progress_callback)

        except (Exception, KeyError) as e:
            print(f"--- 主要加载方式失败: {file_name} ---")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")
            print("-----------------------------------------\n")
            print("尝试诊断恢复加载方式（禁用内存映射）...")

            # --- 尝试诊断恢复加载方法 ---
            try:
                # 禁用内存映射 (mmap=False)，仍保持文件打开支持惰性读取
                tdms_file = TdmsFile.open(file_path, mmap=False)
                self.tdms_files[file_name] = tdms_file
                print("诊断恢复加载方式成功！")
                return self._process_tdms_data(tdms_file, file_name, progress_callback)

            except (Exception, KeyError) as e_backup:
                # --- 两种方式都失败，进行详细诊断并清理 ---
                print(f"--- 诊断恢复加载方式也失败: {file_name} ---")
                print(f"错误类型: {type(e_backup).__name__}")
                print(f"错误信息: {str(e_backup)}")

            # 进行更深入的元数据诊断
            print("\n--- 正在进行文件诊断 ---")
            try:
                # 尝试只读取元数据，看看是否是数据部分的问题
                with TdmsFile.open(file_path, read_metadata_only=True) as tdms_meta:
                    print("文件元数据可以读取。")
                    print(f"包含的组: {[g.name for g in tdms_meta.groups()]}")
            except Exception as e_meta:
                print(f"文件元数据也读取失败: {str(e_meta)}")

            print("--- 诊断结束 ---\n")

            # 清理可能已部分加载的数据
            if file_name in self.files_data:
                del self.files_data[file_name]
            if file_name in self.tdms_files:
                del self.tdms_files[file_name]

            # 在UI上显示一个详细的错误报告
            final_error_msg = (
                f"加载文件失败: {file_name}\n\n"
                f"主要加载错误:\n{type(e).__name__}: {str(e)}\n\n"
                f"诊断恢复加载错误:\n{type(e_backup).__name__}: {str(e_backup)}\n\n"
                f"请检查文件是否损坏，或尝试重命名文件（避免使用方括号[]等特殊字符）。"
            )
            wx.CallAfter(wx.MessageBox, final_error_msg, "文件加载错误", wx.OK | wx.ICON_ERROR)
            return False

    def load_tdms_file_with_progress(self, file_path: str, parent_window, on_finish_callback=None) -> None:
        """启动带进度条的异步文件加载。"""
        original_file_name = osp.basename(file_path)
        self._cancel_load = False  # 重置取消标记
        dialog = ProgressDialog(parent_window, "加载文件", f"准备加载文件:\n{original_file_name}")

        def progress_callback(value, message):
            if self._cancel_load:
                return
            wx.CallAfter(dialog.update, value, message)
            # 状态栏显示简洁进度（文件名+百分比）
            main_frame = parent_window.GetTopLevelParent() if hasattr(parent_window, 'GetTopLevelParent') else parent_window
            if hasattr(main_frame, 'status_bar'):
                wx.CallAfter(_set_status_text_safe, main_frame.status_bar, f"正在加载: {original_file_name} ({value}%)", 0)

        def target():
            with self._loading_lock:
                if original_file_name in self.files_data and len(self.files_data[original_file_name]) > 0:
                    wx.CallAfter(dialog.close)
                    wx.CallAfter(wx.MessageBox, f"文件 '{original_file_name}' 已经打开！", "提示",
                                 wx.OK | wx.ICON_INFORMATION)
                    return

                # 模块导入阶段：延迟加载 numpy / nptdms（仅首次打开文件时执行）
                ensure_data_modules(progress_callback)

                # 元数据解析阶段：启动脉冲动画（此阶段无法预知进度）
                wx.CallAfter(dialog.start_busy, f"正在解析文件元数据:\n{original_file_name}\n请稍候...")
                # 状态栏同步显示（单字段状态栏，完整显示文件名）
                main_frame = parent_window.GetTopLevelParent() if hasattr(parent_window, 'GetTopLevelParent') else parent_window
                if hasattr(main_frame, 'status_bar'):
                    wx.CallAfter(_set_status_text_safe, main_frame.status_bar, f"解析中: {original_file_name}", 0)

                success = self.load_tdms_file(file_path, progress_callback)

                if self._cancel_load:
                    # 用户取消了导入→清理已加载的脏数据
                    if original_file_name in self.files_data:
                        del self.files_data[original_file_name]
                    if original_file_name in self.tdms_files:
                        del self.tdms_files[original_file_name]
                    if hasattr(main_frame, 'status_bar'):
                        wx.CallAfter(main_frame.status_bar.SetStatusText, "已取消加载", 0)
                    return

                wx.CallAfter(dialog.finish)  # 正常完成，关闭对话框
                # 状态栏显示完成信息
                if hasattr(main_frame, 'status_bar'):
                    wx.CallAfter(_set_status_text_safe, main_frame.status_bar, f"文件读取完成: {original_file_name}", 0)
                if on_finish_callback:
                    wx.CallAfter(on_finish_callback, file_path, success)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        # ShowModal 在主线程调用
        result = dialog.ShowModal()
        if result == wx.ID_CANCEL:
            self._cancel_load = True  # 通知工作线程停止
        dialog.Destroy()


    # --- unload_file 等其他方法保持不变 ---
    def unload_file(self, file_name: str):
        """卸载文件"""
        if file_name in self.files_data:
            del self.files_data[file_name]
        if file_name in self.tdms_files:
            del self.tdms_files[file_name]
        if file_name in self.file_paths:
            del self.file_paths[file_name]
        # 清理该文件的缓存
        keys_to_remove = [k for k in self._data_cache if k[0] == file_name]
        for k in keys_to_remove:
            del self._data_cache[k]
        gc.collect()

    def get_channel_data(self, file_name: str, group_name: str, channel_name: str):
        """获取通道数据（惰性读取 + 缓存：首次访问从文件读取，后续从缓存返回）"""
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

    def should_exclude_channel(self, channel_name: str, data=None) -> bool:
        """检查通道是否应该被排除（keyword + pattern 两级过滤）"""
        # 第一级：关键词过滤（独立于 filter_enabled，始终生效）
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
        # 第二级：通配符模式过滤
        if not self.filter_enabled:
            return False
        for pattern in self.exclude_patterns:
            if self._match_pattern(channel_name, pattern):
                return True
        return False

    def _match_pattern(self, name: str, pattern: str) -> bool:
        """通配符匹配"""
        return fnmatch.fnmatch(name.lower(), pattern.lower())

    def get_file_stats(self, file_name: str):
        """获取文件统计信息"""
        if file_name not in self.files_data:
            return {"groups": 0, "channels": 0}
        groups = len(self.files_data[file_name])
        channels = sum(len(channels) for channels in self.files_data[file_name].values())
        return {"groups": groups, "channels": channels}


    def clear(self):
        """清空所有数据"""
        self.files_data.clear()
        self.tdms_files.clear()
        self.file_paths.clear()
        self._data_cache.clear()
        gc.collect()

    def _process_tdms_data(self, tdms_file, file_name, progress_callback):
        """处理已打开的TdmsFile对象——元数据先行策略（参考 NI 官方 TDMS 读取策略）。

        导入阶段只读取元数据（组/通道名称），不读取任何波形数据：
          · 关键词过滤（故障/保留/预留...）——纯名称匹配，不读数据
          · 通配符模式过滤（*_time / *_status...）——纯名称匹配，不读数据
        通道对象引用存入 files_data，左侧参数树即可生效。
        具体波形数据延迟到双击绘图时由 get_channel_data 按需读取并缓存。
        """
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
                # 检查取消标记（用户关闭了导入对话框）
                if self._cancel_load:
                    break
                channel_name = channel.name

                # 关键词 + 模式过滤（纯名称匹配，不读数据）
                if self.should_exclude_channel(channel_name, data=None):
                    excluded_count += 1
                    continue

                # 进度更新，仅在整数进度变化时回调
                if total_channels > 0 and progress_callback:
                    loaded_channels += 1
                    progress = 30 + int((loaded_channels / total_channels) * 70)
                    if progress != last_progress:
                        last_progress = progress
                        display_message = (
                            f"正在加载文件元数据:\n{file_name}\n"
                            f"当前通道: {group_name} / {channel_name}"
                        )
                        progress_callback(progress, display_message)

                # 只存通道对象引用，不读取波形数据（元数据先行）
                if group_name not in self.files_data[file_name]:
                    self.files_data[file_name][group_name] = OrderedDict()
                self.files_data[file_name][group_name][channel_name] = channel

        if excluded_count > 0:
            wx.CallAfter(wx.MessageBox, f"已排除 {excluded_count} 个通道", "筛选信息", wx.OK | wx.ICON_INFORMATION)

        return True


class ColorRenderer(wx.grid.GridCellRenderer):
    """颜色渲染器——仅显示颜色方块，无文字"""
    def __init__(self):
        super().__init__()

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        color_hex = grid.GetCellValue(row, col)
        swatch = wx.Rect(rect.x + 4, rect.y + 4, rect.width - 8, rect.height - 8)
        try:
            dc.SetBrush(wx.Brush(wx.Colour(color_hex)))
        except Exception:
            dc.SetBrush(wx.Brush(wx.Colour(200, 200, 200)))
        dc.SetPen(wx.Pen(wx.Colour(100, 100, 100), 1))
        dc.DrawRoundedRectangle(swatch, 3)

    def GetBestSize(self, grid, attr, dc, row, col):
        return wx.Size(60, 24)

    def Clone(self):
        return ColorRenderer()


class ColorPopup(wx.PopupTransientWindow):
    """颜色选择弹出窗——点击外部自动消失（非阻塞事件驱动）"""
    def __init__(self, parent, on_select, on_dismiss):
        super().__init__(parent, wx.BORDER_SIMPLE)
        self._on_select = on_select
        self._on_dismiss = on_dismiss
        self._dismissing = False
        self.SetBackgroundColour(wx.Colour(245, 245, 245))
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(245, 245, 245))
        rows, cols = 6, 3
        gs = wx.GridSizer(rows, cols, 1, 1)
        for hex_code in Config.COLOR_PALETTE:
            b = wx.Panel(panel, size=(64, 32))
            try:
                b.SetBackgroundColour(wx.Colour(hex_code))
            except Exception:
                pass
            b.SetToolTip(hex_code)
            b.Bind(wx.EVT_LEFT_DOWN, lambda e, h=hex_code: self._select(h))
            b.Bind(wx.EVT_ENTER_WINDOW, lambda e: e.GetEventObject().SetWindowStyleFlag(wx.BORDER_SIMPLE))
            b.Bind(wx.EVT_LEAVE_WINDOW, lambda e: e.GetEventObject().SetWindowStyleFlag(wx.BORDER_NONE))
            gs.Add(b, 0)
        panel.SetSizer(gs)
        panel.Bind(wx.EVT_LEFT_DOWN, lambda e: self.Dismiss())
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.ALL, 2)
        self.SetSizer(sizer)
        self.Fit()

    def _select(self, hex_code):
        self._on_select(hex_code)
        self.Dismiss()

    def Dismiss(self):
        """关闭弹窗并通知 dismiss 回调"""
        if not self._dismissing:
            self._dismissing = True
            super().Dismiss()
            wx.CallAfter(self._on_dismiss)


class ColorEditor(wx.grid.GridCellEditor):
    """颜色编辑器——点击弹出颜色方块窗，不选时保留原色"""
    def __init__(self):
        super().__init__()
        self._value = None

    def Create(self, parent, id, evtHandler):
        self.SetControl(wx.Control(parent, id, size=(1, 1)))

    def BeginEdit(self, row, col, grid):
        self._value = grid.GetCellValue(row, col)
        wx.CallAfter(self._show_popup, row, col, grid)
        return None

    def _show_popup(self, row, col, grid):
        param_panel = grid.GetParent()
        while param_panel and not hasattr(param_panel, '_suppress_redraw'):
            param_panel = param_panel.GetParent()
        selected = [False]
        def on_select(hex_code):
            selected[0] = True
            if param_panel:
                param_panel._suppress_redraw = True
            grid.SetCellValue(row, col, hex_code)
            if param_panel:
                param_panel._suppress_redraw = False
            grid.ForceRefresh()
        def on_dismiss():
            if not selected[0]:
                if param_panel:
                    param_panel._suppress_redraw = True
                grid.SetCellValue(row, col, self._value)
                if param_panel:
                    param_panel._suppress_redraw = False
            grid.ForceRefresh()
            if selected[0] and param_panel and param_panel.on_parameter_changed:
                param_panel.on_parameter_changed()
            popup.Destroy()
        popup = ColorPopup(grid, on_select, on_dismiss)
        cell_rect = grid.CellToRect(row, col)
        screen_pos = grid.ClientToScreen(cell_rect.GetBottomRight())
        popup.SetPosition(screen_pos)
        popup.Show()

    def EndEdit(self, row, col, grid, oldVal):
        pass
    def ApplyEdit(self, row, col, grid):
        pass
    def Clone(self):
        return ColorEditor()


class LineStyleRenderer(wx.grid.GridCellRenderer):
    """线型渲染器——仅绘制线型示意，无文字"""

    def __init__(self):
        super().__init__()

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        dc.SetBackgroundMode(wx.SOLID)
        dc.SetBrush(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(rect)

        linestyle = grid.GetCellValue(row, col)
        line_y = rect.y + rect.height // 2
        line_start = rect.x + 5
        line_end = rect.x + rect.width - 5

        pen_styles = {
            '实线': wx.SOLID,
            '虚线': wx.SHORT_DASH,
            '点线': wx.DOT,
            '点划线': wx.DOT_DASH
        }

        pen_style = pen_styles.get(linestyle, wx.SOLID)
        dc.SetPen(wx.Pen(wx.BLACK, 2, pen_style))
        dc.DrawLine(line_start, line_y, line_end, line_y)

    def Clone(self):
        return LineStyleRenderer()


class LineStylePreview(wx.Panel):
    """线型预览面板——绘制线型示意，无文字"""
    def __init__(self, parent, matplot_style, size=(180, 28)):
        super().__init__(parent, size=size)
        self.matplot_style = matplot_style
        self._hover = False
        self.SetBackgroundColour(wx.Colour(255, 255, 255))
        self.SetMinSize(size)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

    def _on_enter(self, event):
        self._hover = True
        self.Refresh()

    def _on_leave(self, event):
        self._hover = False
        self.Refresh()

    def _on_paint(self, event):
        dc = wx.PaintDC(self)
        w, h = self.GetClientSize()
        bg = wx.Colour(230, 240, 255) if self._hover else wx.Colour(255, 255, 255)
        dc.SetBackground(wx.Brush(bg))
        dc.Clear()

        style_map = {
            '-': wx.SOLID,
            '--': wx.SHORT_DASH,
            ':': wx.DOT,
            '-.': wx.DOT_DASH,
        }
        pen_style = style_map.get(self.matplot_style, wx.SOLID)
        dc.SetPen(wx.Pen(wx.Colour(50, 50, 50), 2, pen_style))
        y = h // 2
        dc.DrawLine(10, y, w - 10, y)


class LineStylePopup(wx.PopupTransientWindow):
    """线型选择弹出窗——点击外部自动消失（非阻塞事件驱动）"""
    def __init__(self, parent, on_select, on_dismiss):
        super().__init__(parent, wx.BORDER_SIMPLE)
        self._on_select = on_select
        self._on_dismiss = on_dismiss
        self._dismissing = False
        self.SetBackgroundColour(wx.Colour(245, 245, 245))
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(245, 245, 245))

        line_styles = list(Config.LINESTYLE_MAP.items())
        gs = wx.GridSizer(len(line_styles), 1, 2, 2)
        for name, code in line_styles:
            b = LineStylePreview(panel, code, size=(180, 32))
            b.SetToolTip(name)
            b.Bind(wx.EVT_LEFT_DOWN, lambda e, h=name: self._select(h))
            gs.Add(b, 0)
        panel.SetSizer(gs)
        panel.Bind(wx.EVT_LEFT_DOWN, lambda e: self.Dismiss())
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.ALL, 4)
        self.SetSizer(sizer)
        self.Fit()

    def _select(self, style_name):
        self._on_select(style_name)
        self.Dismiss()

    def Dismiss(self):
        """关闭弹窗并通知 dismiss 回调"""
        if not self._dismissing:
            self._dismissing = True
            super().Dismiss()
            wx.CallAfter(self._on_dismiss)


class CheckboxRenderer(wx.grid.GridCellRenderer):
    """复选框渲染器"""

    def __init__(self):
        super().__init__()

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        if isSelected:
            dc.SetBrush(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)
        else:
            dc.SetBrush(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(rect)

        value = grid.GetCellValue(row, col)
        is_checked = value == "1"

        checkbox_size = 16
        checkbox_rect = wx.Rect(
            rect.x + (rect.width - checkbox_size) // 2,
            rect.y + (rect.height - checkbox_size) // 2,
            checkbox_size,
            checkbox_size
        )

        dc.SetPen(wx.Pen(wx.BLACK, 1))
        dc.SetBrush(wx.Brush(wx.WHITE))
        dc.DrawRectangle(checkbox_rect)

        if is_checked:
            dc.SetPen(wx.Pen(wx.BLACK, 2))
            points = [
                wx.Point(checkbox_rect.x + 3, checkbox_rect.y + 8),
                wx.Point(checkbox_rect.x + 7, checkbox_rect.y + 12),
                wx.Point(checkbox_rect.x + 13, checkbox_rect.y + 4)
            ]
            dc.DrawLines(points)

    def GetBestSize(self, grid, attr, dc, row, col):
        return wx.Size(100, 20)

    def Clone(self):
        return CheckboxRenderer()


class ProgressDialog(wx.Dialog):
    """进度条对话框 - 稳定的大尺寸版本"""

    def __init__(self, parent, title="处理中", message="正在加载文件..."):
        best_width = max(400, parent.GetTextExtent(message).width + 100)
        super().__init__(parent, title=title, size=(best_width, 200),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.parent = parent
        self._import_stopped = False  # 是否因用户关闭而停止

        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- 消息文本框 ---
        self.message_ctrl = wx.TextCtrl(
            panel,
            value=message,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH | wx.NO_BORDER | wx.TE_WORDWRAP
        )
        self.message_ctrl.SetBackgroundColour(panel.GetBackgroundColour())
        self.message_ctrl.SetCanFocus(False)
        main_sizer.Add(self.message_ctrl, 1, wx.ALL | wx.EXPAND, 10)

        # --- 进度条容器面板 ---
        self.progress_panel = wx.Panel(panel)
        main_sizer.Add(self.progress_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        self.gauge = wx.Gauge(self.progress_panel, range=100, style=wx.GA_HORIZONTAL)

        # 百分比文本 (已隐藏)
        self.progress_label = wx.StaticText(self.progress_panel, label="0%", style=wx.ALIGN_CENTER)
        self.progress_label.Hide()

        panel.SetSizer(main_sizer)
        self.progress_panel.Bind(wx.EVT_SIZE, self.on_progress_panel_resize)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Centre()
        wx.CallAfter(self.on_progress_panel_resize)

        # 脉冲动画（用于不可预知进度的阶段，如元数据解析）
        self._pulse_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_pulse_timer, self._pulse_timer)
        self._pulse_value = 0
        self._busy_mode = False

    def _on_close(self, event):
        """用户点击 X 关闭按钮——确认后停止导入"""
        result = wx.MessageBox("确定要停止当前文件的导入吗？\n已加载的部分数据将被丢弃。",
                               "停止导入", wx.YES_NO | wx.ICON_QUESTION)
        if result == wx.YES:
            self._import_stopped = True
            if self.IsModal():
                self.EndModal(wx.ID_CANCEL)
            else:
                self.Destroy()
        # 选 NO 则不关闭

    def on_progress_panel_resize(self, event=None):
        """当容器面板尺寸变化时，更新进度条尺寸"""
        panel_size = self.progress_panel.GetSize()
        self.gauge.SetSize(panel_size)
        if event:
            event.Skip()

    def update(self, value, message=None):
        """更新进度"""
        # 切换出忙碌模式
        if self._busy_mode:
            self.stop_busy()
        try:
            if message and self.message_ctrl:
                self.message_ctrl.SetValue(message)
        except RuntimeError:
            pass
        try:
            if self.gauge:
                self.gauge.SetValue(value)
            self.progress_panel.Refresh()
        except RuntimeError:
            pass

    def start_busy(self, message=None):
        """启动忙碌模式（脉冲动画，用于不可预知进度的阶段）"""
        if not self._busy_mode:
            self._busy_mode = True
            self._pulse_value = 0
            self._pulse_timer.Start(50)  # 每50ms更新一次
        if message:
            try:
                self.message_ctrl.SetValue(message)
            except RuntimeError:
                pass

    def stop_busy(self):
        """停止忙碌模式"""
        if self._busy_mode:
            self._busy_mode = False
            self._pulse_timer.Stop()

    def _on_pulse_timer(self, event):
        """脉冲定时器回调——缓慢匀速前进，到达90%后停住等待完成"""
        if self._pulse_value < 90:
            self._pulse_value += 2
        try:
            if self.gauge:
                self.gauge.SetValue(self._pulse_value)
        except RuntimeError:
            pass

    def finish(self):
        """导入正常完成——关闭对话框（返回 wx.ID_OK）"""
        self.stop_busy()
        try:
            if self.gauge:
                self.gauge.SetValue(100)
        except RuntimeError:
            pass
        try:
            if self.IsModal():
                self.EndModal(wx.ID_OK)
            else:
                self.Destroy()
        except RuntimeError:
            # ShowModal 已返回且对话框已 Destroy 后，队列中残留的 CallAfter 会进入此路径
            pass

    def close(self):
        """关闭对话框"""
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()

class FilterConfigDialog(wx.Dialog):
    """数据筛选配置对话框"""
    def __init__(self, parent, data_manager):
        super().__init__(parent, title="数据筛选设置", size=(400, 300))
        self.data_manager = data_manager
        self._create_ui()
        self._load_settings()

    def _create_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 启用筛选复选框
        self.enable_check = wx.CheckBox(panel, label="启用数据筛选")
        sizer.Add(self.enable_check, 0, wx.ALL, 5)

        # 排除模式列表
        list_label = wx.StaticText(panel, label="排除模式（支持通配符 * 和 ?）:")
        sizer.Add(list_label, 0, wx.ALL, 5)

        self.pattern_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.pattern_list.InsertColumn(0, "模式", width=350)
        sizer.Add(self.pattern_list, 1, wx.EXPAND | wx.ALL, 5)

        # 按钮面板
        btn_panel = wx.Panel(panel)
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.add_btn = wx.Button(btn_panel, label="添加")
        self.edit_btn = wx.Button(btn_panel, label="编辑")
        self.delete_btn = wx.Button(btn_panel, label="删除")
        self.default_btn = wx.Button(btn_panel, label="恢复默认")

        btn_sizer.Add(self.add_btn)
        btn_sizer.Add(self.edit_btn)
        btn_sizer.Add(self.delete_btn)
        btn_sizer.Add(self.default_btn)
        btn_panel.SetSizer(btn_sizer)

        sizer.Add(btn_panel, 0, wx.EXPAND | wx.ALL, 5)

        # 确定取消按钮
        btn_sizer2 = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(panel, wx.ID_OK, label="确定")
        self.cancel_btn = wx.Button(panel, wx.ID_CANCEL, label="取消")
        btn_sizer2.Add(self.ok_btn)
        btn_sizer2.Add(self.cancel_btn)
        sizer.Add(btn_sizer2, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

        panel.SetSizer(sizer)

        # 绑定事件
        self.enable_check.Bind(wx.EVT_CHECKBOX, self._on_enable_changed)
        self.add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit)
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        self.default_btn.Bind(wx.EVT_BUTTON, self._on_restore_default)

    def _load_settings(self):
        """加载当前设置"""
        self.enable_check.SetValue(self.data_manager.filter_enabled)
        self.pattern_list.DeleteAllItems()
        for pattern in self.data_manager.exclude_patterns:
            self.pattern_list.Append([pattern])

    def _on_enable_changed(self, event):
        """启用状态改变事件"""
        self.data_manager.filter_enabled = self.enable_check.GetValue()

    def _on_add(self, event):
        """添加新模式"""
        dlg = wx.TextEntryDialog(self, "请输入排除模式:", "添加模式")
        if dlg.ShowModal() == wx.ID_OK:
            pattern = dlg.GetValue()
            if pattern and pattern not in self.data_manager.exclude_patterns:
                self.data_manager.exclude_patterns.append(pattern)
                self.pattern_list.Append([pattern])
        dlg.Destroy()

    def _on_edit(self, event):
        """编辑选中的模式"""
        index = self.pattern_list.GetFirstSelected()
        if index != -1:
            old_pattern = self.pattern_list.GetItemText(index)
            dlg = wx.TextEntryDialog(self, "请输入新的排除模式:", "编辑模式", old_pattern)
            if dlg.ShowModal() == wx.ID_OK:
                new_pattern = dlg.GetValue()
                if new_pattern:
                    self.data_manager.exclude_patterns[index] = new_pattern
                    self.pattern_list.SetItem(index, 0, new_pattern)
            dlg.Destroy()

    def _on_delete(self, event):
        """删除选中的模式"""
        index = self.pattern_list.GetFirstSelected()
        if index != -1:
            del self.data_manager.exclude_patterns[index]
            self.pattern_list.DeleteItem(index)

    def _on_restore_default(self, event):
        """恢复默认设置"""
        if wx.MessageBox("确定要恢复默认设置吗？", "确认", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.data_manager.exclude_patterns = ['*_time', '*_status', '*_flag']
            self.pattern_list.DeleteAllItems()
            for pattern in self.data_manager.exclude_patterns:
                self.pattern_list.Append([pattern])


class ImportOptionsDialog(wx.Dialog):
    """导入选项设置对话框"""
    def __init__(self, parent, data_manager):
        super().__init__(parent, title="导入选项")
        self.data_manager = data_manager
        self._create_ui()
        self._load_settings()
        # 用顶层sizer自适应大小，确保内容完整显示
        self.Fit()
        self.Layout()

    def _create_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(panel, label="导入时自动跳过参数名包含以下字样的参数：")
        font = title.GetFont()
        font.MakeBold()
        title.SetFont(font)
        sizer.Add(title, 0, wx.ALL, 10)

        name_grid = wx.GridSizer(0, 3, 8, 8)
        self.cb_fault = wx.CheckBox(panel, label='故障')
        self.cb_reserve = wx.CheckBox(panel, label='保留')
        self.cb_predefined = wx.CheckBox(panel, label='预留')
        self.cb_standby = wx.CheckBox(panel, label='备用')
        self.cb_idle = wx.CheckBox(panel, label='空闲')
        self.cb_delete = wx.CheckBox(panel, label='删除')

        for cb in [self.cb_fault, self.cb_reserve, self.cb_predefined,
                   self.cb_standby, self.cb_idle, self.cb_delete]:
            name_grid.Add(cb, 0, wx.ALL, 4)

        sizer.Add(name_grid, 0, wx.ALL | wx.EXPAND, 10)

        # 使用普通按钮（不用标准按钮），避免默认行为干扰
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.AddStretchSpacer(1)
        ok_btn = wx.Button(panel, wx.ID_ANY, "确定")
        cancel_btn = wx.Button(panel, wx.ID_ANY, "取消")
        btn_sizer.Add(ok_btn, 0, wx.RIGHT, 5)
        btn_sizer.Add(cancel_btn, 0, 0, 0)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 10)

        panel.SetSizer(sizer)

        # 关键：给 dialog 设置顶层 sizer 包含 panel，Fit 才能正确计算尺寸
        top_sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(top_sizer)

        # 绑定按钮事件确保保存设置
        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

    def _load_settings(self):
        self.cb_fault.SetValue(self.data_manager.skip_fault_params)
        self.cb_reserve.SetValue(self.data_manager.skip_reserve_params)
        self.cb_predefined.SetValue(self.data_manager.skip_predefined_params)
        self.cb_standby.SetValue(self.data_manager.skip_standby_params)
        self.cb_idle.SetValue(self.data_manager.skip_idle_params)
        self.cb_delete.SetValue(self.data_manager.skip_delete_params)

    def _save_settings(self):
        self.data_manager.skip_fault_params = self.cb_fault.GetValue()
        self.data_manager.skip_reserve_params = self.cb_reserve.GetValue()
        self.data_manager.skip_predefined_params = self.cb_predefined.GetValue()
        self.data_manager.skip_standby_params = self.cb_standby.GetValue()
        self.data_manager.skip_idle_params = self.cb_idle.GetValue()
        self.data_manager.skip_delete_params = self.cb_delete.GetValue()

    def _on_ok(self, event):
        """确定按钮——保存设置后关闭"""
        self._save_settings()
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.Close()

    def _on_cancel(self, event):
        """取消按钮——不保存直接关闭"""
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Close()


class EffectiveValueDialog(wx.Dialog):
    """有效值获取方式对话框——弹出在按钮附近"""
    def __init__(self, parent, data_manager):
        title = "有效值获取方式"
        super().__init__(parent, title=title,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.data_manager = data_manager
        self._create_ui()
        self.Fit()  # 根据内容自适应大小
        # 定位到鼠标附近（按钮点击位置），若取不到则 CentOnParent
        pos = wx.GetMousePosition()
        if pos:
            self.SetPosition(pos)
        else:
            self.CentreOnParent()

    def _create_ui(self):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(panel, label="请选择有效值计算窗口：")
        sizer.Add(label, 0, wx.ALL, 10)

        # 使用独立 RadioButton，每个按钮按自身文字宽度显示
        choices = list(Config.EFFECTIVE_VALUE_METHODS.keys())
        self._radio_buttons = []
        default_idx = choices.index(self.data_manager.effective_value_method)
        for i, choice in enumerate(choices):
            rb = wx.RadioButton(panel, label=choice, style=wx.RB_GROUP if i == 0 else 0)
            if i == default_idx:
                rb.SetValue(True)
            sizer.Add(rb, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
            self._radio_buttons.append(rb)
        # 末尾补一行间距
        sizer.AddSpacer(8)

        # 阴影显示选项——选中时按有效值窗口宽度在竖直线两侧显示半透明阴影
        self.shadow_check = wx.CheckBox(panel, label="显示有效值阴影（按窗口宽度）")
        self.shadow_check.SetValue(self.data_manager.show_effective_shadow)
        self.shadow_check.SetToolTip("选中后，红蓝竖直线两侧会显示半透明阴影区域，宽度等于有效值计算窗口")
        sizer.Add(self.shadow_check, 0, wx.ALL | wx.ALIGN_LEFT, 10)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(panel, wx.ID_OK, "确定")
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "取消")
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 10)

        panel.SetSizer(sizer)
        top_sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(top_sizer)

    def GetSelectedMethod(self):
        choices = list(Config.EFFECTIVE_VALUE_METHODS.keys())
        selected_idx = 0
        for i, rb in enumerate(self._radio_buttons):
            if rb.GetValue():
                selected_idx = i
                break
        return choices[selected_idx], Config.EFFECTIVE_VALUE_METHODS[choices[selected_idx]], self.shadow_check.GetValue()


class ParameterGridPanel(wx.Panel):
    """参数表格面板"""

    def __init__(self, parent, on_parameter_changed_callback):
        super().__init__(parent)
        self.on_parameter_changed = on_parameter_changed_callback
        self.show_actual_value_channels = set()
        self.top_channels = set()
        self._channel_mapping = {}
        self.last_selected_cell = None
        self._suppress_redraw = False

        # 简化：只记录下一个颜色索引
        self._next_color_index = 0

        self._create_ui()
        self._setup_event_bindings()
        self._setup_grid_appearance()

    def _create_ui(self):
        """创建用户界面"""
        scrolled = wx.ScrolledWindow(self)
        scrolled.SetScrollRate(10, 10)

        self.grid = wx.grid.Grid(scrolled)
        self.grid.CreateGrid(0, 17)

        # 设置列标签
        columns = [
            "参数名称", "采样间隔(ms)", "绘制曲线", "显示实际值", "曲线颜色",
            "曲线线型", "线宽", "图例名称", "最大值", "最小值", "区域均值",
            "区域最大值", "区域最小值", "红轴数值", "蓝轴数值",
            "红轴有效值", "蓝轴有效值"
        ]

        for i, label in enumerate(columns):
            self.grid.SetColLabelValue(i, label)

        # 设置列宽
        col_sizes = [200, 100, 80, 80, 100, 80, 80, 120, 80, 80, 80, 80, 80, 80, 80, 80, 80]
        for i, size in enumerate(col_sizes):
            self.grid.SetColSize(i, size)

        self.grid.EnableGridLines(True)
        self._setup_special_columns()

        # 布局
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.grid, 1, wx.EXPAND)
        scrolled.SetSizer(sizer)

        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        panel_sizer.Add(scrolled, 1, wx.EXPAND)
        self.SetSizer(panel_sizer)

    def _setup_special_columns(self):
        """设置特殊列（颜色、线型等）及编辑权限"""
        # 参数名称列（col 0）——只读
        name_attr = wx.grid.GridCellAttr()
        name_attr.SetReadOnly(True)
        self.grid.SetColAttr(0, name_attr)

        # 复选框列（col 2 绘制曲线、col 3 显示实际值）
        for col in [2, 3]:
            attr = wx.grid.GridCellAttr()
            attr.SetRenderer(CheckboxRenderer())
            self.grid.SetColAttr(col, attr)

        # 颜色列（col 4）——渲染器绘制色块，点击由 _on_cell_left_click 处理弹出选择器
        color_attr = wx.grid.GridCellAttr()
        color_attr.SetRenderer(ColorRenderer())
        color_attr.SetReadOnly(True)
        self.grid.SetColAttr(4, color_attr)

        # 线型列（col 5）——渲染器绘制线型，点击弹出视觉化选择器
        linestyle_attr = wx.grid.GridCellAttr()
        linestyle_attr.SetRenderer(LineStyleRenderer())
        linestyle_attr.SetReadOnly(True)
        self.grid.SetColAttr(5, linestyle_attr)

        # 线宽列（col 6）——下拉选择
        linewidth_attr = wx.grid.GridCellAttr()
        linewidth_editor = wx.grid.GridCellChoiceEditor(Config.LINEWIDTH_CHOICES)
        linewidth_attr.SetEditor(linewidth_editor)
        self.grid.SetColAttr(6, linewidth_attr)

        # 图例名称列（col 7）——文本编辑
        legend_attr = wx.grid.GridCellAttr()
        legend_attr.SetEditor(wx.grid.GridCellTextEditor())
        self.grid.SetColAttr(7, legend_attr)

        # 统计列（col 8~16）——只读
        for col in range(8, 17):
            stat_attr = wx.grid.GridCellAttr()
            stat_attr.SetReadOnly(True)
            self.grid.SetColAttr(col, stat_attr)

    def _setup_event_bindings(self):
        """设置事件绑定"""
        self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self._on_cell_changed)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_LEFT_DCLICK, self._on_cell_double_click)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_LEFT_CLICK, self._on_cell_left_click)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_RIGHT_CLICK, self._on_cell_right_click)
        self.grid.Bind(wx.grid.EVT_GRID_SELECT_CELL, self._on_cell_select)
        self.grid.Bind(wx.EVT_CONTEXT_MENU, self._on_grid_context_menu)

    def _on_grid_context_menu(self, event):
        """网格上下文菜单事件"""
        # 获取点击位置
        pos = event.GetPosition()

        # 将屏幕坐标转换为网格客户区坐标
        grid_pos = self.grid.ScreenToClient(pos)

        # 检查点击位置是否在网格的空白区域
        row, col = self.grid.XYToCell(grid_pos.x, grid_pos.y)

        # 如果点击在有效单元格之外（空白区域）
        if row == -1 and col == -1:
            self._show_blank_area_menu(grid_pos)
        else:
            # 如果是单元格右键，让默认处理继续
            event.Skip()

    def _show_blank_area_menu(self, position):
        """显示空白区域右键菜单"""
        menu = wx.Menu()

        # 添加菜单项
        clear_all_item = menu.Append(wx.ID_ANY, "清除全部参数")
        menu.AppendSeparator()
        refresh_item = menu.Append(wx.ID_ANY, "刷新表格")

        # 绑定事件
        self.Bind(wx.EVT_MENU, self._on_clear_all_parameters, clear_all_item)
        self.Bind(wx.EVT_MENU, self._on_refresh_grid, refresh_item)

        # 显示菜单
        self.grid.PopupMenu(menu, position)
        menu.Destroy()

    def _get_next_color(self, current_color=None):
        """获取下一个颜色"""
        if not Config.COLOR_PALETTE:
            return "#FF0000"  # 默认红色

        color = Config.COLOR_PALETTE[self._next_color_index]
        self._next_color_index = (self._next_color_index + 1) % len(Config.COLOR_PALETTE)
        return color

    def _on_clear_all_parameters(self, event):
        """清除全部参数"""
        if self.grid.GetNumberRows() > 0:
            # 确认对话框
            dlg = wx.MessageDialog(self,
                                   "确定要清除所有参数吗？此操作不可撤销！",
                                   "确认清除",
                                   wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)

            if dlg.ShowModal() == wx.ID_YES:
                # 清除所有数据
                self.clear()

                # 触发参数改变回调
                if self.on_parameter_changed:
                    self.on_parameter_changed()

                # 更新状态栏
                main_frame = self.GetTopLevelParent()
                if hasattr(main_frame, 'status_bar'):
                    main_frame.status_bar.SetStatusText("已清除所有参数")

            dlg.Destroy()
        else:
            # 如果没有参数，显示提示
            wx.MessageBox("参数表格中没有任何参数可清除", "提示", wx.OK | wx.ICON_INFORMATION)

    def _on_refresh_grid(self, event):
        """刷新表格"""
        # 重新设置所有行的颜色
        for row in range(self.grid.GetNumberRows()):
            self._refresh_row_appearance(row)
        self.grid.ForceRefresh()
        # 更新状态栏
        main_frame = self.GetTopLevelParent()
        if hasattr(main_frame, 'status_bar'):
            main_frame.status_bar.SetStatusText("表格已刷新")

    def _setup_grid_appearance(self):
        """设置表格外观"""
        # 设置交替行背景色
        self.grid.SetDefaultCellBackgroundColour(wx.Colour(255, 255, 255))  # 白色
        self.grid.SetDefaultCellTextColour(wx.Colour(0, 0, 0))  # 黑色文字

        # 设置网格线颜色
        self.grid.SetGridLineColour(wx.Colour(200, 200, 200))

    def add_channel(self, display_name: str, full_path: str = None):
        """添加通道到表格"""
        row = self.grid.GetNumberRows()
        self.grid.AppendRows(1)

        # 获取上一个参数的颜色
        next_color = self._get_next_color()

        # 设置默认值
        self.grid.SetCellValue(row, 0, display_name)
        self.grid.SetCellValue(row, 1, "20")
        self.grid.SetCellValue(row, 2, "1")
        self.grid.SetCellValue(row, 3, "0")
        self.grid.SetCellValue(row, 4, next_color)
        self.grid.SetCellValue(row, 5, Config.LINESTYLE_CHOICES[0])
        self.grid.SetCellValue(row, 6, Config.LINEWIDTH_CHOICES[0])
        # 图例名称默认取参数名中的通道名部分（去掉文件序号前缀）
        legend_default = display_name.split('|')[1] if '|' in display_name else display_name
        self.grid.SetCellValue(row, 7, legend_default)

        # 设置交替行背景色
        self._refresh_row_appearance(row)

        # 设置文字颜色
        for col in range(self.grid.GetNumberCols()):
            self.grid.SetCellTextColour(row, col, wx.Colour(50, 50, 50))

        if full_path:
            self._channel_mapping[display_name] = full_path

        self.grid.MakeCellVisible(row, 0)
        self.grid.ForceRefresh()  # 强制刷新显示

        main_frame = self.GetTopLevelParent()
        if hasattr(main_frame, 'status_bar'):
            main_frame.status_bar.SetStatusText(f"已添加参数: {display_name} | 颜色: {next_color}")

        if self.on_parameter_changed:
            self.on_parameter_changed()

    def _refresh_row_appearance(self, row):
        """刷新行外观"""
        # 根据行号设置背景色
        if row % 2 == 0:
            bg_color = wx.Colour(240, 245, 255)  # 浅蓝色
        else:
            bg_color = wx.Colour(248, 248, 248)  # 浅灰色

        for col in range(self.grid.GetNumberCols()):
            self.grid.SetCellBackgroundColour(row, col, bg_color)

    def get_visible_channels(self):
        """获取可见通道"""
        return {
            self.grid.GetCellValue(i, 0)
            for i in range(self.grid.GetNumberRows())
            if self.grid.GetCellValue(i, 0) and self.grid.GetCellValue(i, 2) == "1"
        }

    def get_show_actual_value_channels(self):
        """获取显示实际值的通道"""
        return {
            self.grid.GetCellValue(i, 0)
            for i in range(self.grid.GetNumberRows())
            if self.grid.GetCellValue(i, 0) and self.grid.GetCellValue(i, 3) == "1"
        }

    def _get_full_path(self, display_name: str):
        """获取完整路径"""
        return self._channel_mapping.get(display_name)

    def clear(self):
        """清空表格"""
        if self.grid.GetNumberRows() > 0:
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        self.show_actual_value_channels.clear()
        self.top_channels.clear()
        self._channel_mapping.clear()
        self._next_color_index = 0
        self.grid.ForceRefresh()

    def _on_cell_changed(self, event):
        """单元格内容变化事件"""
        if self._suppress_redraw:
            event.Skip()
            return
        row, col = event.GetRow(), event.GetCol()
        if col == 1:  # 采样间隔列——联动修改同文件所有通道
            new_value = self.grid.GetCellValue(row, 1)
            full_path = self._get_full_path(self.grid.GetCellValue(row, 0))
            if full_path:
                file_name = full_path.split('/')[0]
                for i in range(self.grid.GetNumberRows()):
                    if i == row:
                        continue
                    other_full = self._get_full_path(self.grid.GetCellValue(i, 0))
                    if other_full and other_full.split('/')[0] == file_name:
                        self.grid.SetCellValue(i, 1, new_value)
        if self.on_parameter_changed:
            self.on_parameter_changed()
        event.Skip()

    def _on_cell_left_click(self, event):
        """单元格左键点击事件"""
        row, col = event.GetRow(), event.GetCol()

        if col in [2, 3]:  # 复选框列
            current_value = self.grid.GetCellValue(row, col)
            new_value = "1" if current_value != "1" else "0"
            self.grid.SetCellValue(row, col, new_value)
            self.grid.RefreshAttr(row, col)
            if self.on_parameter_changed:
                self.on_parameter_changed()
            return
        if col == 4:  # 颜色列
            wx.CallAfter(self._show_color_popup, row, col)
            return
        if col == 5:  # 线型列
            wx.CallAfter(self._show_linestyle_popup, row, col)
            return
        event.Skip()

    def _show_color_popup(self, row, col):
        """颜色弹出选择器——点击外部自动消失（非阻塞）"""
        grid = self.grid
        old_value = grid.GetCellValue(row, col)
        selected = [False]

        def on_select(hex_code):
            selected[0] = True
            self._suppress_redraw = True
            grid.SetCellValue(row, col, hex_code)
            self._suppress_redraw = False
            grid.Refresh()
            if self.on_parameter_changed:
                self.on_parameter_changed()

        def on_dismiss():
            if not selected[0]:
                self._suppress_redraw = True
                grid.SetCellValue(row, col, old_value)
                self._suppress_redraw = False
                grid.Refresh()
            popup.Destroy()

        popup = ColorPopup(grid, on_select, on_dismiss)
        cell_rect = grid.CellToRect(row, col)
        screen_pos = grid.ClientToScreen(cell_rect.GetBottomRight())
        popup.SetPosition(screen_pos)
        popup.Show()

    def _show_linestyle_popup(self, row, col):
        """线型弹出选择器——点击外部自动消失（非阻塞）"""
        grid = self.grid
        old_value = grid.GetCellValue(row, col)
        selected = [False]

        def on_select(style_name):
            selected[0] = True
            self._suppress_redraw = True
            grid.SetCellValue(row, col, style_name)
            self._suppress_redraw = False
            grid.Refresh()
            if self.on_parameter_changed:
                self.on_parameter_changed()

        def on_dismiss():
            if not selected[0]:
                self._suppress_redraw = True
                grid.SetCellValue(row, col, old_value)
                self._suppress_redraw = False
                grid.Refresh()
            popup.Destroy()

        popup = LineStylePopup(grid, on_select, on_dismiss)
        cell_rect = grid.CellToRect(row, col)
        screen_pos = grid.ClientToScreen(cell_rect.GetBottomRight())
        popup.SetPosition(screen_pos)
        popup.Show()

    def _on_cell_right_click(self, event):
        """单元格右键点击事件"""
        row = event.GetRow()
        if row < 0:
            return

        channel_name = self.grid.GetCellValue(row, 0)
        if not channel_name:
            return

        menu = wx.Menu()
        is_top_display = channel_name in self.top_channels
        top_text = "✓ 置顶图层" if is_top_display else "置顶图层"

        top_display_item = menu.Append(wx.ID_ANY, top_text)
        menu.AppendSeparator()
        remove_item = menu.Append(wx.ID_ANY, "取消绘制")

        self.Bind(wx.EVT_MENU, lambda e: self._on_toggle_top_display(row), top_display_item)
        self.Bind(wx.EVT_MENU, lambda e: self._on_remove_channel(row), remove_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def _on_toggle_top_display(self, row):
        """切换置顶显示"""
        channel_name = self.grid.GetCellValue(row, 0)

        if channel_name in self.top_channels:
            self.top_channels.remove(channel_name)
        else:
            self.top_channels.add(channel_name)

        if self.on_parameter_changed:
            self.on_parameter_changed()

    def _on_remove_channel(self, row):
        """移除通道"""
        channel_name = self.grid.GetCellValue(row, 0)

        if channel_name in self.show_actual_value_channels:
            self.show_actual_value_channels.remove(channel_name)

        if channel_name in self.top_channels:
            self.top_channels.remove(channel_name)
        self.grid.DeleteRows(row)

        if self.on_parameter_changed:
            self.on_parameter_changed()

    def update_statistics(self, plots_data):
        """更新统计信息"""
        channel_data_map = {plot_data['name']: plot_data for plot_data in plots_data}

        for i in range(self.grid.GetNumberRows()):
            channel_name = self.grid.GetCellValue(i, 0)
            if not channel_name or channel_name not in channel_data_map:
                continue

            y_data = channel_data_map[channel_name]['y_data']
            max_val, min_val = np.max(y_data), np.min(y_data)

            self.grid.SetCellValue(i, 8, f"{max_val:.6f}")
            self.grid.SetCellValue(i, 9, f"{min_val:.6f}")

    def update_vertical_line_values(self, red_line_x, blue_line_x):
        """更新竖直线数值"""
        main_frame = self.GetTopLevelParent()
        if not hasattr(main_frame, 'plot_panel'):
            return

        plot_panel = main_frame.plot_panel

        for i in range(self.grid.GetNumberRows()):
            channel_name = self.grid.GetCellValue(i, 0)
            if not channel_name:
                continue

            # 重置区域统计
            for col in range(10, 13):
                self.grid.SetCellValue(i, col, "")

            # 更新红轴数值
            if red_line_x is not None:
                red_value = self._get_original_value(plot_panel, channel_name, red_line_x)
                self.grid.SetCellValue(i, 13, red_value)
                red_effective = self._calculate_effective_value(plot_panel, channel_name, red_line_x)
                self.grid.SetCellValue(i, 15, red_effective)
            else:
                self.grid.SetCellValue(i, 13, "")
                self.grid.SetCellValue(i, 15, "")

            # 更新蓝轴数值
            if blue_line_x is not None:
                blue_value = self._get_original_value(plot_panel, channel_name, blue_line_x)
                self.grid.SetCellValue(i, 14, blue_value)
                blue_effective = self._calculate_effective_value(plot_panel, channel_name, blue_line_x)
                self.grid.SetCellValue(i, 16, blue_effective)
            else:
                self.grid.SetCellValue(i, 14, "")
                self.grid.SetCellValue(i, 16, "")

            # 计算区域统计
            if red_line_x is not None and blue_line_x is not None:
                region_start, region_end = sorted([red_line_x, blue_line_x])
                region_stats = self._get_region_statistics(plot_panel, channel_name, region_start, region_end)
                if region_stats:
                    self.grid.SetCellValue(i, 10, f"{region_stats['mean']:.6f}")
                    self.grid.SetCellValue(i, 11, f"{region_stats['max']:.6f}")
                    self.grid.SetCellValue(i, 12, f"{region_stats['min']:.6f}")

    def _calculate_effective_value(self, plot_panel, channel_name: str, line_x: float):
        """计算有效值"""
        if not hasattr(plot_panel, 'original_data') or channel_name not in plot_panel.original_data:
            return "N/A"

        main_frame = self.GetTopLevelParent()
        window_size = getattr(main_frame.data_manager, 'effective_value_window', 5.0)

        channel_data = plot_panel.original_data[channel_name]
        x_data, y_data = channel_data['x'], channel_data['y']

        if len(x_data) == 0:
            return "N/A"

        if window_size == 0.0:  # 瞬时值
            idx = np.argmin(np.abs(x_data - line_x))
            if abs(x_data[idx] - line_x) < 0.1:
                return f"{y_data[idx]:.6f}"
            return "N/A"

        # 窗口平均值
        start_time, end_time = line_x - window_size, line_x + window_size
        mask = (x_data >= start_time) & (x_data <= end_time)
        window_data = y_data[mask]

        if len(window_data) == 0:
            return "N/A"

        return f"{np.mean(window_data):.6f}"

    def _get_region_statistics(self, plot_panel, channel_name: str, start_x: float, end_x: float):
        """计算区域统计信息"""
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

        return {
            'mean': np.mean(region_data),
            'max': np.max(region_data),
            'min': np.min(region_data),
            'count': len(region_data)
        }

    def _get_original_value(self, plot_panel, channel_name: str, time_x: float):
        """获取原始数值"""
        if not hasattr(plot_panel, 'original_data') or channel_name not in plot_panel.original_data:
            return "N/A"

        channel_data = plot_panel.original_data[channel_name]
        x_data, y_data = channel_data['x'], channel_data['y']

        if len(x_data) == 0:
            return "N/A"

        idx = np.argmin(np.abs(x_data - time_x))
        time_diff = abs(x_data[idx] - time_x)

        return f"{y_data[idx]:.6f}" if time_diff <= 0.1 else "N/A"

    def _on_cell_double_click(self, event):
        """单元格双击事件——仅对可编辑单元格启用编辑控件"""
        row, col = event.GetRow(), event.GetCol()
        # 可编辑列：采样间隔(1)、图例名称(7)；其余列由专用处理器或只读
        if col in (1, 7):
            self.grid.EnableCellEditControl()
        event.Skip()

    def _on_cell_select(self, event):
        """单元格选择事件"""
        if (self.last_selected_cell and
                self.last_selected_cell[1] in [2, 3] and
                event.GetCol() != self.last_selected_cell[1]):

            if self.on_parameter_changed:
                self.on_parameter_changed()

        self.last_selected_cell = (event.GetRow(), event.GetCol())
        event.Skip()


class SaveImageDialog(wx.Dialog):
    """保存图像字体设置对话框，含预览功能"""
    def __init__(self, parent, plot_panel):
        super().__init__(parent, title="图像保存设置",
                        style=wx.DEFAULT_DIALOG_STYLE)
        self.plot_panel = plot_panel
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # 坐标轴字体大小
        axis_sizer = wx.BoxSizer(wx.HORIZONTAL)
        axis_sizer.Add(wx.StaticText(panel, label="坐标字体大小:"), 0,
                       wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.axis_font_size = wx.SpinCtrl(panel, value="9", min=6, max=24, size=(60, -1))
        self.axis_font_size.SetToolTip("坐标轴标签和刻度文字的大小")
        axis_sizer.Add(self.axis_font_size, 0)
        main_sizer.Add(axis_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # 图例字体大小
        legend_sizer = wx.BoxSizer(wx.HORIZONTAL)
        legend_sizer.Add(wx.StaticText(panel, label="图例文字大小:"), 0,
                         wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        self.legend_font_size = wx.SpinCtrl(panel, value="8", min=6, max=24, size=(60, -1))
        self.legend_font_size.SetToolTip("图例区域会随文字大小自动调整")
        legend_sizer.Add(self.legend_font_size, 0)
        main_sizer.Add(legend_sizer, 0, wx.ALL | wx.EXPAND, 10)

        # 按钮：预览 | 弹性间距 | 确定 | 取消
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        preview_btn = wx.Button(panel, wx.ID_ANY, "预览")
        preview_btn.SetToolTip("将当前字体设置应用到绘图区预览效果")
        preview_btn.Bind(wx.EVT_BUTTON, self._on_preview)
        btn_sizer.Add(preview_btn, 0, wx.RIGHT, 10)
        btn_sizer.AddStretchSpacer(1)
        ok_btn = wx.Button(panel, wx.ID_OK, "确定")
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, "取消")
        btn_sizer.Add(ok_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(cancel_btn, 0)
        main_sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 10)

        panel.SetSizer(main_sizer)
        main_sizer.Fit(self)
        self.CenterOnParent()

    def _on_preview(self, event):
        """预览：将当前字体设置实时应用到绘图区"""
        axis_font = self.axis_font_size.GetValue()
        legend_font = self.legend_font_size.GetValue()
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

        # 隐藏十字光标（预览中也不显示）
        for obj in [p.crosshair_v, p.crosshair_h, p.crosshair_text]:
            if obj is not None:
                obj.set_visible(False)

        p.figure.tight_layout(pad=1.0)
        p.canvas.draw()

    def get_settings(self):
        return {
            'axis_font_size': self.axis_font_size.GetValue(),
            'legend_font_size': self.legend_font_size.GetValue()
        }


class MatplotlibPlotPanel(wx.Panel):
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
        # 有效值阴影区域（axvspan 对象）
        self.red_shadow = None
        self.blue_shadow = None
        self.span_selector = None
        self.dragging = None
        self.right_axes_dict = {}
        self.x_max = Config.DEFAULT_WINDOW_DURATION
        # 十字光标
        self.crosshair_v = None
        self.crosshair_h = None
        self.crosshair_text = None

        self._create_ui()
        self._setup_event_bindings()

    def _create_ui(self):
        """创建用户界面"""
        self.figure = Figure(figsize=(10, 6), dpi=120)
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self, -1, self.figure)

        # 工具栏
        toolbar_panel = self._create_toolbar()

        # 布局
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(toolbar_panel, 0, wx.EXPAND)
        sizer.Add(self.canvas, 1, wx.EXPAND)
        self.SetSizer(sizer)

    def _create_toolbar(self):
        """创建工具栏"""
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        # 工具按钮
        tools = [
            ("导出数据", self.on_export_data),
            ("保存图像", self.on_save_image),
            ("导出有效值", self.on_export_effective_values)
        ]

        for label, handler in tools:
            btn = wx.Button(panel, label=label)
            btn.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, handler)
            sizer.Add(btn, 0, wx.ALL, 5)

        # 窗口时长
        duration_label = wx.StaticText(panel, label="  窗口时长(s):")
        duration_label.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(duration_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.window_duration = wx.TextCtrl(panel, value="10.0", size=(60, -1), style=wx.TE_PROCESS_ENTER)
        self.window_duration.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.window_duration, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        # 竖直线控制
        line_label = wx.StaticText(panel, label="  竖直线:")
        line_label.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(line_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.red_line_check = wx.CheckBox(panel, label="红色")
        self.red_line_check.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.red_line_check.SetValue(False)
        sizer.Add(self.red_line_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.blue_line_check = wx.CheckBox(panel, label="蓝色")
        self.blue_line_check.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.blue_line_check.SetValue(False)
        sizer.Add(self.blue_line_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        panel.SetSizer(sizer)
        return panel

    def _setup_event_bindings(self):
        """设置事件绑定"""
        self.window_duration.Bind(wx.EVT_TEXT_ENTER, self._on_window_duration_changed)
        self.window_duration.Bind(wx.EVT_KILL_FOCUS, self._on_window_duration_changed)

        self.red_line_check.Bind(wx.EVT_CHECKBOX, self._on_red_line_toggle)
        self.blue_line_check.Bind(wx.EVT_CHECKBOX, self._on_blue_line_toggle)

        self.canvas.mpl_connect('button_press_event', self._on_mouse_press)
        self.canvas.mpl_connect('motion_notify_event', self._on_mouse_motion)
        self.canvas.mpl_connect('button_release_event', self._on_mouse_release)
        self.canvas.mpl_connect('button_press_event', self._on_navigation)
        self.canvas.mpl_connect('scroll_event', self._on_scroll)

    def plot(self, plots_data, parameters, show_actual_value_channels=None, top_channels=None):
        """绘制数据"""
        if show_actual_value_channels is None:
            show_actual_value_channels = set()
        if top_channels is None:
            top_channels = set()

        self._clear_plot()

        # 单通道常数参数自动切实际值模式
        if len(plots_data) == 1:
            y_raw = plots_data[0]['y_data']
            if np.min(y_raw) == np.max(y_raw) and plots_data[0]['name'] not in show_actual_value_channels:
                show_actual_value_channels.add(plots_data[0]['name'])

        self._prepare_plot_data(plots_data, parameters, show_actual_value_channels, top_channels)
        self._setup_plot_appearance()
        # 设置X轴从0开始并自动调整Y轴，与双击重置缩放保持一致
        self.axes.set_xlim(0, self.x_max)
        for right_ax in self.right_axes_dict.values():
            right_ax.set_xlim(0, self.x_max)
        self._auto_scale_y()
        self._update_vertical_lines()
        self._finalize_plot()

    def _clear_plot(self):
        """清除绘图"""
        self.axes.clear()
        for ax in self.right_axes_dict.values():
            ax.remove()
        self.right_axes_dict.clear()
        self.current_plots.clear()
        self.original_data.clear()
        # 重置十字光标引用（axes.clear() 已删除原对象）
        self.crosshair_v = None
        self.crosshair_h = None
        self.crosshair_text = None
        # 重置阴影引用（axes.clear() 已删除原对象）
        self.red_shadow = None
        self.blue_shadow = None

    def _prepare_plot_data(self, plots_data, parameters, show_actual_value_channels, top_channels):
        """准备绘图数据"""
        # 计算X轴范围 - 基于实际数据，不依赖窗口时长设置
        max_x = max((np.max(plot_data['x_data']) for plot_data in plots_data if len(plot_data['x_data']) > 0),
                    default=0)

        if max_x > 0:
            # 更新窗口时长显示（仅用于显示，不控制范围）
            self.window_duration.SetValue(f"{max_x:.2f}")
            self.x_max = max_x
        else:
            self.x_max = Config.DEFAULT_WINDOW_DURATION

        # 分离普通通道和置顶通道
        normal_plots, top_plots = [], []

        for plot_data in plots_data:
            plot_info = self._create_plot_info(plot_data, parameters, show_actual_value_channels, top_channels)
            if plot_info['is_top']:
                top_plots.append(plot_info)
            else:
                normal_plots.append(plot_info)

        # 绘制通道
        self._draw_plots(normal_plots + top_plots, parameters, show_actual_value_channels)

    @staticmethod
    def _downsample(x, y, threshold=4000):
        """LTTB降采样：保持波形特征的智能降采样，返回降采样后的 x, y"""
        n = len(x)
        if n <= threshold:
            return x, y

        # 输出数组
        out_x = np.empty(threshold)
        out_y = np.empty(threshold)
        out_x[0] = x[0]
        out_y[0] = y[0]
        out_x[-1] = x[-1]
        out_y[-1] = y[-1]

        # 每个桶大小（首尾点各占一个，中间分 threshold-2 个桶）
        bucket_size = (n - 2) / (threshold - 2)
        a = 0  # 上一个被选中点的索引

        for i in range(threshold - 2):
            # 当前桶范围
            s = int(np.floor(i * bucket_size) + 1)
            e = int(np.floor((i + 1) * bucket_size) + 1)
            e = min(e, n - 1)
            # 下一个桶的平均值（作为三角形的第三个顶点）
            ns = int(np.floor((i + 1) * bucket_size) + 1)
            ne = int(np.floor((i + 2) * bucket_size) + 1)
            ne = min(ne, n)
            avg_x = x[ns:ne].mean()
            avg_y = y[ns:ne].mean()
            # 在当前桶中选择与(上一个点, 下一桶均值)构成最大三角形面积的点
            ax, ay = x[a], y[a]
            area = np.abs((ax - avg_x) * (y[s:e] - ay) - (ax - x[s:e]) * (avg_y - ay))
            a = s + int(np.argmax(area))
            out_x[i + 1] = x[a]
            out_y[i + 1] = y[a]

        return out_x, out_y

    def _create_plot_info(self, plot_data, parameters, show_actual_value_channels, top_channels):
        """创建绘图信息"""
        name = plot_data['name']
        simple_name = self._extract_simple_name(name)

        # 保存原始数据
        self.original_data[name] = {
            'x': plot_data['x_data'],
            'y': plot_data['y_data']
        }

        # 获取参数
        param = parameters.get(name, {})
        color = param.get('color', '#1f77b4')
        linestyle = param.get('linestyle', '-')  # _get_channel_parameters 已映射为 matplotlib 代码
        linewidth = float(param.get('linewidth', Config.DEFAULT_LINEWIDTH))
        legend_name = param.get('legend_name', simple_name)  # 来自参数表格的图例名称

        show_actual = name in show_actual_value_channels
        is_top = name in top_channels

        # 百分比归一化
        y_data = plot_data['y_data']
        y_min, y_max = np.min(y_data), np.max(y_data)
        if self._is_percent_mode() and not show_actual:
            if y_max != y_min:
                y_data = (y_data - y_min) / (y_max - y_min) * 100
            else:
                # 常数通道：归一化到 100% 水平线
                y_data = np.full_like(y_data, 100.0)

        return {
            'x_data': plot_data['x_data'],
            'y_data': y_data,
            'name': name,
            'display_name': simple_name,
            'legend_name': legend_name,
            'color': color,
            'linestyle': linestyle,
            'linewidth': linewidth,
            'show_actual': show_actual,
            'is_top': is_top,
            'original_data': plot_data['y_data'],
            'is_constant': (y_max == y_min)  # 标记常数通道
        }

    def _draw_plots(self, plots, parameters, show_actual_value_channels):
        """绘制所有通道"""
        for plot_info in plots:
            if not plot_info['show_actual'] or self._is_percent_mode():
                line = self._draw_single_plot(plot_info)
                if line:
                    self.current_plots[plot_info['name']] = line

        # 为显示实际值的通道创建右侧Y轴
        self._create_right_axes(parameters, show_actual_value_channels)

    def _create_right_axes(self, parameters, show_actual_value_channels):
        """创建右侧Y轴"""
        actual_value_channels = [
            name for name in parameters.keys()
            if name in show_actual_value_channels and not self._is_percent_mode()
        ]

        for i, channel_name in enumerate(actual_value_channels):
            if channel_name not in self.original_data:
                continue

            # 创建右侧Y轴
            right_ax = self.axes.twinx()
            offset = 60 * (i + 1)
            right_ax.spines['right'].set_position(('outward', offset))

            # 设置样式
            color = parameters[channel_name].get('color', '#1f77b4')
            right_ax.spines['right'].set_color(color)
            right_ax.tick_params(axis='y', colors=color)
            right_ax.yaxis.label.set_color(color)

            # 设置标签
            simple_name = self._extract_simple_name(channel_name)
            legend_name = parameters[channel_name].get('legend_name', simple_name)
            right_ax.set_ylabel(legend_name, fontsize=8)
            right_ax.set_xlim(self.axes.get_xlim())

            self.right_axes_dict[channel_name] = right_ax

            # 绘制实际值数据
            self._draw_actual_value(right_ax, channel_name, parameters)

    def _draw_actual_value(self, right_ax, channel_name, parameters):
        """在右侧Y轴绘制实际值"""
        channel_data = self.original_data[channel_name]
        param = parameters[channel_name]

        color = param.get('color', '#1f77b4')
        linestyle = param.get('linestyle', '-')  # _get_channel_parameters 已映射为 matplotlib 代码
        linewidth = float(param.get('linewidth', Config.DEFAULT_LINEWIDTH))

        is_top = channel_name in getattr(self.GetTopLevelParent().param_panel, 'top_channels', set())
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
        """绘制单个通道"""
        zorder = 10 if plot_info['is_top'] else 1

        # 降采样：保留原始数据引用，仅对渲染数据降采样
        x_data, y_data = self._downsample(plot_info['x_data'], plot_info['y_data'])

        line, = self.axes.plot(
            x_data, y_data,
            label=f"{plot_info['legend_name']}",
            color=plot_info['color'], linestyle=plot_info['linestyle'],
            linewidth=plot_info['linewidth'], zorder=zorder
        )
        return line

    def _setup_plot_appearance(self):
        """设置绘图外观"""
        self.axes.set_xlabel('时间 (s)', fontsize=9)
        self.axes.set_ylabel('百分比 (%)' if self._is_percent_mode() else '数值', fontsize=9)
        self.axes.grid(True, alpha=0.3)

        # 添加图例
        if self.current_plots:
            lines = list(self.current_plots.values())
            labels = [line.get_label() for line in lines]
            legend = self.axes.legend(lines, labels, loc='upper right', fontsize=8)
            # 加粗图例中的线，便于辨认颜色
            for leg_line in legend.get_lines():
                leg_line.set_linewidth(1.0)

        # 添加范围选择器
        if self.span_selector:
            self.span_selector.disconnect_events()
        self.span_selector = SpanSelector(self.axes, self._on_span_select, 'horizontal',
                                          useblit=True, props=dict(alpha=0.2, facecolor='red'))

    def _finalize_plot(self):
        """完成绘图设置"""
        self.figure.tight_layout(pad=1.0)
        self.canvas.draw()

    def _is_percent_mode(self):
        """检查是否为百分比模式"""
        main_frame = self.GetTopLevelParent()
        return not bool(getattr(main_frame.param_panel, 'show_actual_value_channels', set()))

    def _extract_simple_name(self, display_name):
        """提取简单名称"""
        return display_name.split('|')[1] if '|' in display_name else display_name

    def _on_window_duration_changed(self, event):
        """窗口时长改变事件"""
        try:
            duration = float(self.window_duration.GetValue())
            if duration > 0:
                self.x_max = duration
                self.axes.set_xlim(0, self.x_max)
                for right_ax in self.right_axes_dict.values():
                    right_ax.set_xlim(0, self.x_max)
                self.canvas.draw()
                self._update_zoom_status(0, self.x_max, is_duration_change=True)
        except (ValueError, TypeError):
            # 如果输入无效，恢复为当前范围
            current_range = self.axes.get_xlim()
            self.window_duration.SetValue(f"{current_range[1]:.2f}")
        event.Skip()

    def _on_span_select(self, xmin, xmax):
        """范围选择事件"""
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
        """鼠标按下事件"""
        if event.inaxes != self.axes:
            return

        if hasattr(event, 'dblclick') and event.dblclick:
            return

        # 检查竖直线拖拽
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
        """鼠标移动事件——拖拽竖直线 或 显示十字光标"""
        if event.inaxes != self.axes or event.xdata is None or event.ydata is None:
            self._hide_crosshair()
            return

        # 拖拽竖直线模式
        if self.dragging:
            if self.dragging == 'red':
                self.red_line_x = event.xdata
            elif self.dragging == 'blue':
                self.blue_line_x = event.xdata
            self._update_vertical_lines()
            self._hide_crosshair()
            return

        # 十字光标模式
        self._update_crosshair(event.xdata, event.ydata)

    def _update_crosshair(self, x, y):
        """绘制十字光标 + 坐标标签"""
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

        # 坐标文本
        label = f"X={x:.4f}s  Y={y:.4f}"
        if self.crosshair_text is None:
            self.crosshair_text = self.axes.text(
                0.02, 0.98, label, transform=self.axes.transAxes,
                fontsize=8, ha='left', va='top',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='lightyellow', alpha=0.85),
                zorder=25
            )
        else:
            self.crosshair_text.set_text(label)
            self.crosshair_text.set_visible(True)

        self.canvas.draw_idle()

    def _hide_crosshair(self):
        """隐藏十字光标"""
        for obj in [self.crosshair_v, self.crosshair_h, self.crosshair_text]:
            if obj:
                obj.set_visible(False)
        if any([self.crosshair_v, self.crosshair_h, self.crosshair_text]):
            self.canvas.draw_idle()

    def _on_mouse_release(self, event):
        """鼠标释放事件"""
        if self.dragging:
            if self.span_selector:
                self.span_selector.set_active(True)
            self.dragging = None

    def _on_navigation(self, event):
        """导航事件（双击复原）"""
        if hasattr(event, 'dblclick') and event.dblclick and event.inaxes == self.axes:
            self._reset_zoom()

    def _on_scroll(self, event):
        """滚轮事件——垂直方向(Y轴)拉伸缩放"""
        if event.inaxes is None:
            return

        target_ax = event.inaxes

        # 获取当前Y轴范围
        y_min, y_max = target_ax.get_ylim()
        y_range = y_max - y_min
        if abs(y_range) < 1e-15:
            return

        # 缩放因子：滚轮上滚放大(范围缩小)，下滚缩小(范围放大)
        scale_factor = 0.8 if event.button == 'up' else 1.25

        # 以鼠标当前Y位置为缩放中心
        y_center = event.ydata if event.ydata is not None else (y_min + y_max) / 2
        ratio = (y_center - y_min) / y_range

        new_range = y_range * scale_factor
        new_y_min = y_center - new_range * ratio
        new_y_max = y_center + new_range * (1 - ratio)

        target_ax.set_ylim(new_y_min, new_y_max)
        self.canvas.draw_idle()

        # 状态栏显示Y轴缩放信息
        main_frame = self.GetTopLevelParent()
        if hasattr(main_frame, 'status_bar'):
            zoom_action = "放大" if event.button == 'up' else "缩小"
            # 判断是主Y轴还是右侧Y轴
            if target_ax is self.axes:
                axis_name = "主Y轴"
            else:
                axis_name = "右侧Y轴"
            status_text = f"Y轴{zoom_action} | {axis_name}范围: {new_y_min:.4f} ~ {new_y_max:.4f}"
            main_frame.status_bar.SetStatusText(status_text, 0)

    def _on_red_line_toggle(self, event):
        """红色竖直线切换"""
        if self.red_line_check.GetValue() and self.red_line_x is None:
            x_range = self.axes.get_xlim()
            self.red_line_x = x_range[0] + (x_range[1] - x_range[0]) * 0.3
        self._update_vertical_lines()

    def _on_blue_line_toggle(self, event):
        """蓝色竖直线切换"""
        if self.blue_line_check.GetValue() and self.blue_line_x is None:
            x_range = self.axes.get_xlim()
            self.blue_line_x = x_range[0] + (x_range[1] - x_range[0]) * 0.7
        self._update_vertical_lines()

    def _update_vertical_lines(self):
        """更新竖直线 + 时间标注 + 有效值阴影"""
        # 清理旧对象（竖直线、时间标注、阴影）
        for obj in [self.red_line, self.blue_line,
                    getattr(self, 'red_time_text', None),
                    getattr(self, 'blue_time_text', None),
                    self.red_shadow, self.blue_shadow]:
            if obj and hasattr(obj, 'remove'):
                obj.remove()
        self.red_line = self.blue_line = None
        self.red_time_text = self.blue_time_text = None
        self.red_shadow = self.blue_shadow = None

        ylim = self.axes.get_ylim()
        xlim = self.axes.get_xlim()
        y_top = ylim[1] - (ylim[1] - ylim[0]) * 0.05

        # 获取有效值阴影设置
        main_frame = self.GetTopLevelParent()
        show_shadow = getattr(main_frame.data_manager, 'show_effective_shadow', False)
        window_size = getattr(main_frame.data_manager, 'effective_value_window', 0.0)

        if self.red_line_check.GetValue() and self.red_line_x is not None:
            # 阴影在竖直线之前绘制，zorder 低于竖直线
            if show_shadow and window_size > 0:
                self.red_shadow = self.axes.axvspan(
                    self.red_line_x - window_size, self.red_line_x + window_size,
                    alpha=0.12, color='red', zorder=5
                )
            self.red_line = self.axes.axvline(x=self.red_line_x, color='red',
                                              linewidth=2, linestyle='-', zorder=10, alpha=0.8)
            self.red_time_text = self.axes.text(
                self.red_line_x + (xlim[1]-xlim[0])*0.005, y_top,
                f"{self.red_line_x:.3f}s",
                color='red', fontsize=8, ha='left', va='bottom',
                fontweight='bold', zorder=11
            )

        if self.blue_line_check.GetValue() and self.blue_line_x is not None:
            # 阴影
            if show_shadow and window_size > 0:
                self.blue_shadow = self.axes.axvspan(
                    self.blue_line_x - window_size, self.blue_line_x + window_size,
                    alpha=0.12, color='blue', zorder=5
                )
            self.blue_line = self.axes.axvline(x=self.blue_line_x, color='blue',
                                               linewidth=2, linestyle='-', zorder=10, alpha=0.8)
            self.blue_time_text = self.axes.text(
                self.blue_line_x + (xlim[1]-xlim[0])*0.005, y_top,
                f"{self.blue_line_x:.3f}s",
                color='blue', fontsize=8, ha='left', va='bottom',
                fontweight='bold', zorder=11
            )

        self.on_vertical_lines_changed(self.red_line_x, self.blue_line_x)
        self.canvas.draw()

    def _is_near_line(self, x, line_x, threshold=0.01):
        """检查是否靠近竖直线"""
        if line_x is None:
            return False
        x_range = self.axes.get_xlim()
        return abs(x - line_x) < (x_range[1] - x_range[0]) * threshold

    def _reset_zoom(self):
        """重置缩放"""
        if not self.original_data:
            # 如果没有数据，使用默认范围
            x_min, x_max = 0, Config.DEFAULT_WINDOW_DURATION
            self.axes.set_xlim(x_min, x_max)
            for right_ax in self.right_axes_dict.values():
                right_ax.set_xlim(x_min, x_max)
            self.canvas.draw()
            return

        try:
            # 计算所有通道数据的最大时间范围
            max_time = 0
            for channel_data in self.original_data.values():
                if len(channel_data['x']) > 0:
                    channel_max = np.max(channel_data['x'])
                    max_time = max(max_time, channel_max)

            self.x_max = max_time

            # 更新窗口时长显示（仅显示，不用于控制范围）
            self.window_duration.SetValue(f"{self.x_max:.2f}")

            # 设置X轴范围
            self.axes.set_xlim(0, self.x_max)
            for right_ax in self.right_axes_dict.values():
                right_ax.set_xlim(0, self.x_max)

            # 自动调整Y轴范围
            self._auto_scale_y()

            self.canvas.draw()
            self._update_zoom_status(0, self.x_max, is_reset=True)

        except Exception:
            # 如果计算失败，使用默认范围
            self.x_max = Config.DEFAULT_WINDOW_DURATION
            self.axes.set_xlim(0, self.x_max)
            for right_ax in self.right_axes_dict.values():
                right_ax.set_xlim(0, self.x_max)
            self.canvas.draw()

    def _auto_scale_y(self):
        """自动调整Y轴范围"""
        if not self.current_plots:
            return

        # 逐线取 min/max 后聚合计算 Y 轴范围
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

        # 调整右侧Y轴
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
        """更新缩放状态"""
        try:
            main_frame = self.GetTopLevelParent()
            if not hasattr(main_frame, 'status_bar'):
                return

            duration = xmax - xmin

            if is_reset:
                status_text = f"缩放已复原 | 数据范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s"
            elif is_duration_change:
                status_text = f"窗口时长已设置 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s"
            else:
                # 计算显示的缩放比例
                data_duration = self.x_max  # 使用实际数据范围
                zoom_ratio = data_duration / duration if duration > 0 else 1.0

                # 估算显示的数据点数量
                visible_points = 0
                if hasattr(self, 'original_data') and self.original_data:
                    for channel_data in self.original_data.values():
                        x_data = channel_data['x']
                        visible_points = max(visible_points, np.sum((x_data >= xmin) & (x_data <= xmax)))

                if visible_points > 0:
                    status_text = f"已缩放 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s | 缩放: {zoom_ratio:.1f}x | 数据点: {visible_points}"
                else:
                    status_text = f"已缩放 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s | 缩放: {zoom_ratio:.1f}x"

            main_frame.status_bar.SetStatusText(status_text, 0)
        except Exception:
            pass

    def on_export_data(self, event):
        """导出数据"""
        if not self.original_data:
            wx.MessageBox("没有数据可导出", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        wildcard = "CSV files (*.csv)|*.csv|All files (*.*)|*.*"
        with wx.FileDialog(self, "导出数据", wildcard=wildcard,
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self._export_data_advanced(dialog.GetPath())
                    wx.MessageBox(f"数据已导出到: {dialog.GetPath()}", "成功", wx.OK | wx.ICON_INFORMATION)
                except Exception as e:
                    wx.MessageBox(f"导出数据失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

    def on_export_effective_values(self, event):
        """导出有效值"""
        if not self.current_plots:
            wx.MessageBox("没有数据可导出", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        has_red_line = self.red_line_x is not None
        has_blue_line = self.blue_line_x is not None

        if not has_red_line and not has_blue_line:
            wx.MessageBox("请先添加红色或蓝色竖直线", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        wildcard = "CSV files (*.csv)|*.csv|All files (*.*)|*.*"
        with wx.FileDialog(self, "导出有效值", wildcard=wildcard,
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self._export_effective_values_csv(dialog.GetPath(), has_red_line, has_blue_line)
                    wx.MessageBox(f"有效值已导出到: {dialog.GetPath()}", "成功", wx.OK | wx.ICON_INFORMATION)
                except Exception as e:
                    wx.MessageBox(f"导出有效值失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)


    def on_save_image(self, event):
        """保存图像——字体设置（含预览）→ 保存 → 还原"""
        if not self.current_plots:
            wx.MessageBox("没有图像可保存", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        # ---- 保存原始状态（支持取消时还原） ----
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

        # ---- 弹出字体设置对话框（含预览功能） ----
        dlg = SaveImageDialog(self, self)
        result = dlg.ShowModal()
        settings = dlg.get_settings() if result == wx.ID_OK else None
        dlg.Destroy()

        if result != wx.ID_OK:
            # 用户取消：还原原始状态
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

        # 确保字体设置已应用
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

        # ---- 文件保存对话框 ----
        wildcard = "PNG files (*.png)|*.png|JPEG files (*.jpg)|*.jpg|PDF files (*.pdf)|*.pdf|All files (*.*)|*.*"
        with wx.FileDialog(self, "保存图像", wildcard=wildcard,
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self.figure.savefig(dialog.GetPath(), dpi=300, bbox_inches='tight')
                    wx.MessageBox(f"图像已保存到: {dialog.GetPath()}", "成功", wx.OK | wx.ICON_INFORMATION)
                except Exception as e:
                    wx.MessageBox(f"保存图像失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

        # ---- 还原原始状态 ----
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

        wx.CallAfter(self.GetTopLevelParent().Refresh)

    def _export_data_advanced(self, file_path):
        """高级数据导出"""
        if not self.original_data:
            return

        # 按采样间隔分组
        # 预构建 通道名→采样间隔 查找表
        param_panel = self.GetTopLevelParent().param_panel
        sample_time_map = {}
        for i in range(param_panel.grid.GetNumberRows()):
            name = param_panel.grid.GetCellValue(i, 0)
            if name:
                try:
                    sample_time_map[name] = float(param_panel.grid.GetCellValue(i, 1))
                except ValueError:
                    sample_time_map[name] = Config.DEFAULT_SAMPLE_TIME

        groups = {}
        for channel_name, channel_data in self.original_data.items():
            sample_time = sample_time_map.get(channel_name, Config.DEFAULT_SAMPLE_TIME)
            display_name = self._extract_simple_name(channel_name)

            if sample_time not in groups:
                groups[sample_time] = []

            groups[sample_time].append({
                'name': display_name,
                'data': channel_data['y'],
                'length': len(channel_data['y'])
            })

        with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile)

            # 表头
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
                    'sample_time': sample_time,
                    'channels': channels,
                    'max_length': max(ch['length'] for ch in channels)
                })

            writer.writerow(headers)

            # 数据行
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
        """导出有效值到CSV"""
        param_panel = self.GetTopLevelParent().param_panel

        with open(file_path, 'w', newline='', encoding='utf-8-sig') as csvfile:
            writer = csv.writer(csvfile)

            # 收集参数名称和数值
            parameter_names = []
            red_values, red_effective_values = [], []
            blue_values, blue_effective_values = [], []

            for i in range(param_panel.grid.GetNumberRows()):
                display_name = param_panel.grid.GetCellValue(i, 0)
                if not display_name:
                    continue

                # 优先使用图例名称，为空时回退到通道名
                legend_name = param_panel.grid.GetCellValue(i, 7).strip()
                if not legend_name:
                    legend_name = self._extract_simple_name(display_name)
                parameter_names.append(legend_name)

                if has_red_line:
                    red_values.append(param_panel.grid.GetCellValue(i, 13))
                    red_effective_values.append(param_panel.grid.GetCellValue(i, 15))

                if has_blue_line:
                    blue_values.append(param_panel.grid.GetCellValue(i, 14))
                    blue_effective_values.append(param_panel.grid.GetCellValue(i, 16))

            # 写入数据
            headers = ["参数名称"] + parameter_names
            writer.writerow(headers)

            if has_red_line:
                writer.writerow([f"红轴数值({self.red_line_x:.3f}s)"] + red_values)
                writer.writerow([f"红轴有效值({self.red_line_x:.3f}s)"] + red_effective_values)

            if has_blue_line:
                writer.writerow([f"蓝轴数值({self.blue_line_x:.3f}s)"] + blue_values)
                writer.writerow([f"蓝轴有效值({self.blue_line_x:.3f}s)"] + blue_effective_values)

    def _get_channel_sample_time(self, channel_name):
        """获取通道采样间隔"""
        try:
            main_frame = self.GetTopLevelParent()
            param_panel = main_frame.param_panel

            for i in range(param_panel.grid.GetNumberRows()):
                if param_panel.grid.GetCellValue(i, 0) == channel_name:
                    sample_time_str = param_panel.grid.GetCellValue(i, 1)
                    return float(sample_time_str)
            return Config.DEFAULT_SAMPLE_TIME
        except Exception:
            return Config.DEFAULT_SAMPLE_TIME

    def clear_plot(self):
        """清除绘图"""
        self._clear_plot()
        self.axes.set_xlabel('时间 (s)', fontsize=9)
        self.axes.set_ylabel('数值', fontsize=9)
        self.axes.grid(True, alpha=0.3)
        self.axes.set_xlim(0, self.x_max)
        self.figure.tight_layout()
        self.canvas.draw()

        self.red_line_x = self.blue_line_x = None
        self.red_line_check.SetValue(False)
        self.blue_line_check.SetValue(False)
        self._update_vertical_lines()


class UserGuideDialog(wx.Dialog):
    """使用教程对话框——左侧目录树 + 右侧内容区 + 上下页导航"""

    # 教程内容：标题 → 正文（支持简单标记：**粗体**、空行分段）
    GUIDE_SECTIONS = [
        ("快速入门", [
            "欢迎使用 SignalScape —— TDMS 数据可视化分析工具。",
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
            "    软件采用惰性加载策略——导入时只读取文件元数据（组/通道名称），不读取具体数据。数据在首次绘制时才按需读取并缓存，从而加快大文件导入速度。",
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
            "修改方式后，若已设置竖直线，表格会立即刷新计算结果。",
            "",
            "显示有效值阴影：",
            "    勾选后，红蓝竖直线两侧会显示半透明阴影区域，宽度等于有效值计算窗口。",
            "    例如选择「前后10秒平均值」，阴影范围为竖直线前后各 10 秒。",
            "    不勾选时，仅显示竖直线，无阴影。",
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
            "    搜索结果会在状态栏显示匹配数量。",
        ]),
        ("参数表格", [
            "下方参数表格——管理待绘制的通道及其样式",
            "",
            "可编辑列（采样间隔/绘制曲线/显示实际值/曲线颜色/曲线线型/线宽/图例名称）：",
            "    直接点击对应单元格即可编辑，修改后自动重绘。",
            "",
            "各列说明：",
            "    · 参数名称：显示通道名（多文件时带文件序号前缀，如「文件1|通道名」）",
            "    · 采样间隔(ms)：决定 X 轴时间轴的计算，修改某通道会联动同文件所有通道",
            "    · 绘制曲线：勾选则在绘图区显示该通道曲线",
            "    · 显示实际值：勾选则为该通道创建独立右侧 Y 轴，显示真实数值（非百分比）",
            "    · 曲线颜色：点击弹出调色板选择",
            "    · 曲线线型：点击弹出线型预览选择（实线/虚线/点线/点划线）",
            "    · 线宽：下拉选择 0.5 ~ 3.0",
            "    · 图例名称：可编辑文本，作为绘图区图例显示名称（默认取通道名）",
            "    · 最大值/最小值：自动统计的全局极值（只读）",
            "    · 区域均值/最大/最小：红蓝竖直线之间的区域统计",
            "    · 红轴数值/蓝轴数值：竖直线处的瞬时值",
            "    · 红轴有效值/蓝轴有效值：竖直线处的有效值（按设定窗口计算）",
            "",
            "右键菜单：",
            "    · 置顶图层：将该通道曲线绘制在最上层",
            "    · 取消绘制：从表格中移除该通道",
            "",
            "空白处右键：清除全部参数 / 刷新表格",
        ]),
        ("绘图与交互", [
            "绘图区——Matplotlib 交互式图表",
            "",
            "显示模式：",
            "    · 百分比模式（默认）：所有通道归一化到 0~100%，便于对比波形",
            "    · 实际值模式：当有通道勾选「显示实际值」时自动切换，该通道用右侧 Y 轴显示真实数值",
            "",
            "鼠标交互：",
            "    · 移动鼠标：显示十字光标及坐标标签",
            "    · 拖拽选区：水平框选放大该区域",
            "    · 双击：复原缩放到完整数据范围",
            "    · 滚轮：以鼠标位置为中心缩放 Y 轴",
            "",
            "竖直线工具：",
            "    勾选「红色」「蓝色」复选框显示竖直线，可直接拖拽移动。",
            "    竖直线用于定位分析时刻，其数值和有效值会实时更新到参数表格。",
        ]),
        ("数据导出", [
            "绘图区工具栏提供三个导出按钮：",
            "",
            "「导出数据」",
            "    将当前绘制通道的原始数据导出为 CSV。按采样间隔分组，每组含时间列和各通道数值列。",
            "",
            "「导出有效值」",
            "    将参数表格中所有通道的红/蓝轴数值及有效值导出为 CSV（需先设置竖直线）。",
            "    导出格式：参数名称行 + 红轴数值/有效值行 + 蓝轴数值/有效值行。",
            "",
            "「保存图像」",
            "    将当前绘图保存为 PNG/JPG/PDF。保存前可设置坐标轴和图例字体大小，支持实时预览。",
            "    导出分辨率为 300 DPI。",
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
            "3. 多文件对比：批量打开多个文件后，参数名会带文件序号前缀（文件1|、文件2|），可同时绘制对比。",
            "",
            "4. 加快导入：在「导入选项」中勾选更多关键词过滤项，可减少无用参数显示。",
            "",
            "5. 卸载文件：在通道树中右键文件节点选择「卸载文件」，可释放内存而不影响其他文件。",
            "",
            "6. 采样间隔联动：修改某通道的采样间隔，同文件的所有通道会同步更新，保证时间轴一致。",
        ]),
    ]

    def __init__(self, parent):
        super().__init__(parent, title="SignalScape 使用教程",
                         size=(900, 640),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._current_index = 0
        self._closing = False
        self._create_ui()
        self._select_section(0)
        self.CenterOnParent()
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _on_close(self, event):
        """关闭时置标记，防止树控件事件访问已销毁的 C++ 对象"""
        self._closing = True
        self.tree.Unbind(wx.EVT_TREE_SEL_CHANGED)
        event.Skip()

    def _create_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # 左侧目录树
        left_panel = wx.Panel(panel)
        left_panel.SetBackgroundColour(wx.Colour(245, 247, 250))
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(left_panel, label="  目  录")
        title_font = wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title.SetFont(title_font)
        title.SetForegroundColour(wx.Colour(60, 90, 140))
        left_sizer.Add(title, 0, wx.ALL, 12)

        self.tree = wx.TreeCtrl(left_panel,
                                style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT |
                                      wx.TR_FULL_ROW_HIGHLIGHT | wx.TR_SINGLE | wx.TR_NO_LINES)
        root = self.tree.AddRoot("目录")
        for section_title, _ in self.GUIDE_SECTIONS:
            self.tree.AppendItem(root, section_title)
        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_tree_select)
        left_sizer.Add(self.tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        left_panel.SetSizer(left_sizer)

        # 右侧内容区
        right_panel = wx.Panel(panel)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        # 标题
        self.title_label = wx.StaticText(right_panel, label="")
        title_font2 = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        self.title_label.SetFont(title_font2)
        self.title_label.SetForegroundColour(wx.Colour(40, 70, 120))
        right_sizer.Add(self.title_label, 0, wx.ALL, 12)

        # 分隔线
        line = wx.StaticLine(right_panel)
        right_sizer.Add(line, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)

        # 内容文本
        self.content_ctrl = wx.TextCtrl(right_panel, style=wx.TE_MULTILINE | wx.TE_READONLY |
                                                          wx.TE_RICH | wx.TE_WORDWRAP | wx.NO_BORDER)
        self.content_ctrl.SetBackgroundColour(wx.Colour(255, 255, 255))
        content_font = wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self.content_ctrl.SetFont(content_font)
        self.content_ctrl.SetCanFocus(False)
        right_sizer.Add(self.content_ctrl, 1, wx.EXPAND | wx.ALL, 12)

        # 底部导航按钮
        nav_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.prev_btn = wx.Button(right_panel, label="◀ 上一页")
        self.next_btn = wx.Button(right_panel, label="下一页 ▶")
        close_btn = wx.Button(right_panel, label="关闭")
        nav_sizer.Add(self.prev_btn, 0, wx.RIGHT, 6)
        nav_sizer.Add(self.next_btn, 0, wx.RIGHT, 6)
        nav_sizer.AddStretchSpacer(1)
        nav_sizer.Add(close_btn, 0)

        self.prev_btn.Bind(wx.EVT_BUTTON, lambda e: self._navigate(-1))
        self.next_btn.Bind(wx.EVT_BUTTON, lambda e: self._navigate(1))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))

        right_sizer.Add(nav_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        right_panel.SetSizer(right_sizer)

        # 布局：左 1/4，右 3/4
        main_sizer.Add(left_panel, 1, wx.EXPAND)
        main_sizer.Add(right_panel, 3, wx.EXPAND | wx.LEFT, 1)
        panel.SetSizer(main_sizer)

        top_sizer = wx.BoxSizer(wx.VERTICAL)
        top_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(top_sizer)

    def _on_tree_select(self, event):
        if self._closing:
            return
        item = event.GetItem()
        if not item.IsOk():
            return
        try:
            # 根据树项找到索引
            idx = 0
            child, cookie = self.tree.GetFirstChild(self.tree.GetRootItem())
            while child.IsOk():
                if child == item:
                    self._select_section(idx)
                    return
                child, cookie = self.tree.GetNextChild(self.tree.GetRootItem(), cookie)
                idx += 1
        except RuntimeError:
            # 树控件 C++ 对象可能已被销毁
            return

    def _navigate(self, delta):
        new_idx = self._current_index + delta
        if 0 <= new_idx < len(self.GUIDE_SECTIONS):
            self._select_section(new_idx)

    def _select_section(self, index):
        self._current_index = index
        title, lines = self.GUIDE_SECTIONS[index]
        self.title_label.SetLabel(title)

        # 渲染内容，支持 **粗体** 标记
        self.content_ctrl.Clear()
        attr_normal = wx.TextAttr()
        attr_normal.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        attr_bold = wx.TextAttr()
        attr_bold.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))

        for line in lines:
            if line.startswith("**") and line.endswith("**"):
                self.content_ctrl.SetDefaultStyle(attr_bold)
                self.content_ctrl.AppendText(line[2:-2] + "\n")
            elif line == "":
                self.content_ctrl.AppendText("\n")
            else:
                # 行内粗体片段
                self._append_rich_line(line, attr_normal, attr_bold)
        # 移除末尾多余空行
        self.content_ctrl.SetInsertionPoint(0)

        # 同步树选中
        if not self._closing:
            try:
                child, cookie = self.tree.GetFirstChild(self.tree.GetRootItem())
                i = 0
                while child.IsOk():
                    if i == index:
                        self.tree.SelectItem(child)
                        break
                    child, cookie = self.tree.GetNextChild(self.tree.GetRootItem(), cookie)
                    i += 1
            except RuntimeError:
                pass

        # 更新导航按钮状态
        self.prev_btn.Enable(index > 0)
        self.next_btn.Enable(index < len(self.GUIDE_SECTIONS) - 1)

    def _append_rich_line(self, line, attr_normal, attr_bold):
        """渲染单行，支持 **粗体** 片段标记"""
        parts = re.split(r'(\*\*[^*]+\*\*)', line)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                self.content_ctrl.SetDefaultStyle(attr_bold)
                self.content_ctrl.AppendText(part[2:-2])
            elif part:
                self.content_ctrl.SetDefaultStyle(attr_normal)
                self.content_ctrl.AppendText(part)
        self.content_ctrl.AppendText("\n")


class HoverButton(wx.Button):
    """无边框按钮——默认透明，鼠标悬停时显示底色"""
    def __init__(self, parent, label, font=None):
        super().__init__(parent, label=label, style=wx.BORDER_NONE)
        self._bg_normal = parent.GetBackgroundColour()
        self._bg_hover = wx.Colour(220, 220, 220)
        self.SetBackgroundColour(self._bg_normal)
        if font:
            self.SetFont(font)
        self.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)

    def _on_enter(self, event):
        self.SetBackgroundColour(self._bg_hover)
        self.Refresh()
        event.Skip()

    def _on_leave(self, event):
        self.SetBackgroundColour(self._bg_normal)
        self.Refresh()
        event.Skip()


class SignalScapeFrame(wx.Frame):
    """主框架类"""

    def __init__(self):
        # 获取显示位置
        display_index = self._get_display_index()
        display_rect = wx.Display(display_index).GetGeometry()

        super().__init__(None, title="SignalScape - TDMS数据可视化工具",
                         pos=display_rect.GetPosition(), size=display_rect.GetSize())

        self.Maximize(True)
        self.data_manager = DataManager()

        # 防抖定时器：参数频繁变化时延迟重绘
        self._redraw_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_redraw_timer, self._redraw_timer)

        self._create_ui()
        self._create_button_bar()
        self._create_status_bar()

    def _get_display_index(self):
        """获取显示索引"""
        mouse_pos = wx.GetMousePosition()
        for i in range(wx.Display.GetCount()):
            if wx.Display(i).GetGeometry().Contains(mouse_pos):
                return i
        return 0

    def _create_button_bar(self):
        """创建按钮栏——单击即触发，无按钮底色和边框，支持快捷键"""
        bar = wx.Panel(self)
        bar.SetBackgroundColour(wx.Colour(240, 240, 240))

        # 增大字体便于点击
        btn_font = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)

        sizer = wx.BoxSizer(wx.HORIZONTAL)

        # (显示名称, 处理函数, 加速键标志, 加速键码, 快捷键提示文本)
        buttons = [
            ("打开TDMS文件", self._on_open, wx.ACCEL_CTRL, ord('O'), "Ctrl+O"),
            ("批量打开", self._on_batch_open, wx.ACCEL_CTRL, ord('B'), "Ctrl+B"),
            ("导入选项", self._on_import_options, wx.ACCEL_CTRL, ord('I'), "Ctrl+I"),
            ("有效值计算方式", self._on_effective_value_settings, wx.ACCEL_CTRL, ord('E'), "Ctrl+E"),
            ("数据筛选设置", self._on_filter_settings, wx.ACCEL_CTRL, ord('F'), "Ctrl+F"),
            ("使用教程", self._on_show_guide, 0, wx.WXK_F1, "F1"),
        ]

        accel_entries = []
        for name, handler, accel_flags, accel_key, key_text in buttons:
            # label 中显示快捷键提示
            display_label = f"{name} ({key_text})"
            btn = HoverButton(bar, display_label, font=btn_font)
            btn.SetToolTip(f"{name}    快捷键: {key_text}")
            btn.Bind(wx.EVT_BUTTON, handler)
            sizer.Add(btn, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 4)

            # 注册加速键：分配唯一 ID 并绑定 EVT_MENU
            cmd_id = wx.NewIdRef()
            accel_entries.append((accel_flags, accel_key, cmd_id))
            self.Bind(wx.EVT_MENU, handler, id=cmd_id)

        bar.SetSizer(sizer)

        # 设置加速键表，使快捷键全局生效
        if accel_entries:
            self.SetAcceleratorTable(wx.AcceleratorTable(accel_entries))

        # 将按钮栏插入主布局最上方
        main_sizer = self.GetSizer()
        if main_sizer:
            main_sizer.Insert(0, bar, 0, wx.EXPAND)
            self.Layout()

    def _create_status_bar(self):
        """创建状态栏"""
        self.status_bar = self.CreateStatusBar(1)
        self.status_bar.SetStatusText("就绪", 0)

    def _on_filter_settings(self, event):
        """打开筛选设置对话框"""
        dlg = FilterConfigDialog(self, self.data_manager)
        if dlg.ShowModal() == wx.ID_OK:
            pass  # 筛选状态不再在状态栏显示
        dlg.Destroy()

    def _on_show_guide(self, event):
        """打开使用教程对话框"""
        dlg = UserGuideDialog(self)
        dlg.ShowModal()
        dlg.Destroy()


    def _create_ui(self):
        """创建用户界面"""
        main_splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)

        # 左侧面板
        left_panel = self._create_left_panel(main_splitter)
        # 右侧面板
        right_panel = self._create_right_panel(main_splitter)

        # 设置分割器
        main_splitter.SplitVertically(left_panel, right_panel)
        main_splitter.SetSashPosition(400)
        main_splitter.SetMinimumPaneSize(300)

        # 主布局
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(main_splitter, 1, wx.EXPAND)
        self.SetSizer(main_sizer)

    def _create_left_panel(self, parent):
        """创建左侧面板"""
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 搜索框
        search_panel = wx.Panel(panel)
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)

        search_text = wx.StaticText(search_panel, label="搜索:")
        search_text.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.search_ctrl = wx.TextCtrl(search_panel, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        search_sizer.Add(search_text, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        search_sizer.Add(self.search_ctrl, 1, wx.EXPAND)
        search_panel.SetSizer(search_sizer)

        # 通道树
        self.channel_tree = wx.TreeCtrl(panel,
                                        style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT |
                                              wx.TR_FULL_ROW_HIGHLIGHT | wx.TR_SINGLE | wx.TR_NO_LINES)

        sizer.Add(search_panel, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.channel_tree, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(sizer)

        # 事件绑定
        self.search_ctrl.Bind(wx.EVT_TEXT, self._on_search_text_change)

        self.channel_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_channel_activated)
        self.channel_tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self._on_tree_right_click)

        return panel

    def _on_search_text_change(self, event):
        """搜索框文本变化/回车事件处理入口"""

        wx.CallAfter(self._perform_search)
        event.Skip()

    def _perform_search(self):
        """执行搜索并重建树的核心逻辑"""

        if not hasattr(self, 'search_ctrl') or not self.search_ctrl:
            return

        search_term = self.search_ctrl.GetValue().strip()

        if not search_term:
            self._rebuild_full_tree()
            self.status_bar.SetStatusText("就绪")
            return

        self.channel_tree.DeleteAllItems()
        root = self.channel_tree.AddRoot("TDMS文件")

        matched_count = 0
        search_term_lower = search_term.lower()

        for file_name, groups in self.data_manager.files_data.items():
            file_item = None
            file_matched = search_term_lower in file_name.lower()
            if file_matched:
                file_item = self.channel_tree.AppendItem(root, file_name)
                matched_count += 1

            for group_name, channels in groups.items():
                group_item = None
                group_matched = search_term_lower in group_name.lower()

                if group_matched:
                    if not file_item:
                        file_item = self.channel_tree.AppendItem(root, file_name)
                    group_item = self.channel_tree.AppendItem(file_item, group_name)
                    matched_count += 1

                for channel_name in channels.keys():
                    if search_term_lower in channel_name.lower():
                        if not file_item:
                            file_item = self.channel_tree.AppendItem(root, file_name)
                        if not group_item:
                            group_item = self.channel_tree.AppendItem(file_item, group_name)

                        self.channel_tree.AppendItem(group_item, channel_name)
                        matched_count += 1

            if file_item and self.channel_tree.ItemHasChildren(file_item):
                self.channel_tree.Expand(file_item)
                # 展开所有匹配的组，让通道可见
                child, cookie = self.channel_tree.GetFirstChild(file_item)
                while child.IsOk():
                    self.channel_tree.Expand(child)
                    child, cookie = self.channel_tree.GetNextChild(file_item, cookie)

        if matched_count > 0:
            self.status_bar.SetStatusText(f"搜索: '{search_term}' | 找到 {matched_count} 个结果")
        else:
            self.status_bar.SetStatusText(f"搜索: '{search_term}' | 未找到匹配项")
            no_results_item = self.channel_tree.AppendItem(root, "无匹配项")
            self.channel_tree.SetItemTextColour(no_results_item, wx.Colour(150, 150, 150))

    def _create_right_panel(self, parent):
        """创建右侧面板"""
        panel = wx.Panel(parent)
        right_splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE | wx.SP_3D)

        # 绘图面板和参数面板
        self.plot_panel = MatplotlibPlotPanel(right_splitter, self._on_vertical_lines_changed)
        self.param_panel = ParameterGridPanel(right_splitter, self._on_parameter_changed)

        right_splitter.SplitHorizontally(self.plot_panel, self.param_panel)
        # 延迟设置分割线位置，确保获取到真实的窗口高度
        wx.CallAfter(self._set_right_splitter_sash, right_splitter)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(right_splitter, 1, wx.EXPAND)
        panel.SetSizer(sizer)

        return panel

    def _set_right_splitter_sash(self, splitter):
        """辅助方法：在界面布局完成后设置分割线的位置"""
        if splitter and splitter.IsShown():
            height = splitter.GetClientSize().GetHeight()
            if height > 0:
                # 将 2/3 的高度分配给绘图面板，1/3 分配给参数表格
                splitter.SetSashPosition(int(height * 2 // 3))

    def _on_open(self, event):
        """打开文件"""
        wildcard = "TDMS files (*.tdms)|*.tdms|All files (*.*)|*.*"
        with wx.FileDialog(self, "打开TDMS文件", wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self._handle_file_open(dialog.GetPath())

    def _on_batch_open(self, event):
        """批量打开文件"""
        wildcard = "TDMS files (*.tdms)|*.tdms|All files (*.*)|*.*"
        with wx.FileDialog(self, "批量打开TDMS文件", wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                file_paths = dialog.GetPaths()
                success_count = 0

                # 批量处理进度条
                progress_dialog = ProgressDialog(self, "批量加载", f"正在批量加载 {len(file_paths)} 个文件")
                progress_dialog.Show()

                # 首次加载前，按需导入 numpy / nptdms（已加载则立即返回）
                progress_dialog.update(0, "正在加载所需模块（numpy / nptdms）...")
                wx.Yield()  # 让界面刷新一次，显示提示文字
                ensure_data_modules()
                progress_dialog.update(0, f"正在批量加载 {len(file_paths)} 个文件")

                try:
                    for i, file_path in enumerate(file_paths):
                        file_name = osp.basename(file_path)

                        # 更新进度
                        progress = int((i / len(file_paths)) * 100)
                        progress_dialog.update(progress, f"正在加载: {file_name}")

                        # 检查是否已存在
                        if file_name in self.data_manager.files_data:
                            continue

                        if self.data_manager.load_tdms_file(file_path):
                            self._update_channel_tree(file_name)
                            success_count += 1

                        # 允许界面响应
                        wx.Yield()

                    progress_dialog.update(100, "批量加载完成")
                    wx.MessageBox(f"已成功加载 {success_count}/{len(file_paths)} 个文件",
                                  "批量加载完成", wx.OK | wx.ICON_INFORMATION)

                finally:
                    progress_dialog.close()

    def _handle_file_open(self, file_path):
        """处理文件打开 - 异步版（使用正确的公共接口）"""
        file_name = osp.basename(file_path)

        if file_name in self.data_manager.files_data:
            wx.MessageBox(f"文件 '{file_name}' 已经打开！", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        if self.data_manager.files_data:
            result = self._show_file_open_dialog()
            if result == wx.ID_YES:
                self.data_manager.clear()
                self.channel_tree.DeleteAllItems()
                self.param_panel.clear()
                self.plot_panel.clear_plot()
            elif result == wx.ID_CANCEL:
                return

        # 定义加载完成后的回调函数
        def on_load_finished(loaded_file_path, success):
            if success:
                # 执行可能耗时的UI更新
                self._update_channel_tree(osp.basename(loaded_file_path))
                self._update_status_after_load(osp.basename(loaded_file_path))
                self.SetStatusText(f"已加载: {osp.basename(loaded_file_path)}")
            else:
                wx.MessageBox(
                    f"加载文件失败: {osp.basename(loaded_file_path)}",
                    "错误",
                    wx.OK | wx.ICON_ERROR
                )
                self.SetStatusText("文件加载失败")

        # 异步加载文件，完成后回调 on_load_finished
        self.data_manager.load_tdms_file_with_progress(
            file_path,
            parent_window=self,
            on_finish_callback=on_load_finished
        )

    def _show_file_open_dialog(self):
        """显示文件打开选项对话框"""
        file_count = len(self.data_manager.files_data)
        current_files = ", ".join(list(self.data_manager.files_data.keys())[:3])
        if file_count > 3:
            current_files += f" 等 {file_count} 个文件"

        dlg = wx.MessageDialog(
            self,
            f"当前已打开 {file_count} 个文件:\n{current_files}\n\n请选择打开方式:",
            "打开文件选项",
            wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION
        )
        dlg.SetYesNoLabels("仅打开新文件", "添加新文件")
        result = dlg.ShowModal()
        dlg.Destroy()
        return result

    def _update_status_after_load(self, file_name):
        """加载文件后更新状态"""
        stats = self.data_manager.get_file_stats(file_name)
        status_text = f"已加载: {file_name} | 组数: {stats['groups']} | 通道数: {stats['channels']} | 就绪"
        self.status_bar.SetStatusText(status_text)

    def _on_effective_value_settings(self, event):
        """有效值设置——使用 RadioBox 持久化选择"""
        dlg = EffectiveValueDialog(self, self.data_manager)
        if dlg.ShowModal() == wx.ID_OK:
            method_name, window, show_shadow = dlg.GetSelectedMethod()
            self.data_manager.effective_value_method = method_name
            self.data_manager.effective_value_window = window
            self.data_manager.show_effective_shadow = show_shadow
            self.status_bar.SetStatusText(f"有效值计算方法: {method_name}")
            self._update_effective_values()
            # 阴影开关变化时刷新竖直线显示
            self.plot_panel._update_vertical_lines()
        dlg.Destroy()

    def _on_import_options(self, event):
        """导入选项设置——仅当过滤选项有变化且有已加载文件时提示重新加载"""
        dlg = ImportOptionsDialog(self, self.data_manager)
        result = dlg.ShowModal()

        changed = False
        if result == wx.ID_OK:
            # 记录保存前的值，用于判断是否有变化
            dm = self.data_manager
            old_values = (
                dm.skip_fault_params, dm.skip_reserve_params, dm.skip_predefined_params,
                dm.skip_standby_params, dm.skip_idle_params, dm.skip_delete_params,
            )
            dlg._save_settings()
            new_values = (
                dm.skip_fault_params, dm.skip_reserve_params, dm.skip_predefined_params,
                dm.skip_standby_params, dm.skip_idle_params, dm.skip_delete_params,
            )
            changed = (old_values != new_values)

        dlg.Destroy()

        # 仅当过滤选项有变化且存在已加载文件时，才提示重新加载
        if changed and self.data_manager.files_data:
            ret = wx.MessageBox(
                "导入选项已更新。\n\n要重新加载当前文件以应用新的过滤规则吗？",
                "应用导入选项",
                wx.YES_NO | wx.ICON_QUESTION
            )
            if ret == wx.YES:
                self._reload_all_files()

    def _reload_all_files(self):
        """重新加载所有已打开的文件，应用新的过滤规则"""
        # 保存文件路径列表
        file_paths = list(self.data_manager.file_paths.values())
        if not file_paths:
            return

        # 清空当前数据
        self.data_manager.clear()
        self.channel_tree.DeleteAllItems()
        self.param_panel.clear()
        self.plot_panel.clear_plot()

        # 逐个重新加载
        for file_path in file_paths:
            if self.data_manager.load_tdms_file(file_path):
                self._update_channel_tree(osp.basename(file_path))

        self.SetStatusText(f"已重新加载 {len(file_paths)} 个文件")

    def _update_effective_values(self):
        """更新有效值"""
        if hasattr(self.plot_panel, 'red_line_x') or hasattr(self.plot_panel, 'blue_line_x'):
            self.plot_panel.on_vertical_lines_changed(
                getattr(self.plot_panel, 'red_line_x', None),
                getattr(self.plot_panel, 'blue_line_x', None)
            )

    def _on_channel_activated(self, event):
        """通道激活事件"""
        item = event.GetItem()
        if not item:
            return

        # 文件节点：展开/折叠
        if (self.channel_tree.ItemHasChildren(item) and
                self.channel_tree.GetItemParent(item) != self.channel_tree.GetRootItem()):
            if self.channel_tree.IsExpanded(item):
                self.channel_tree.Collapse(item)
            else:
                self.channel_tree.Expand(item)

        # 通道节点：添加到参数表格
        elif not self.channel_tree.ItemHasChildren(item):
            self._add_channel_to_grid(item)

    def _add_channel_to_grid(self, item):
        """添加通道到参数表格"""
        channel_name = self.channel_tree.GetItemText(item)
        parent = self.channel_tree.GetItemParent(item)
        root = self.channel_tree.GetRootItem()

        # 跳过隐藏根节点
        if not parent.IsOk() or parent == root:
            return

        group_name = self.channel_tree.GetItemText(parent)
        file_item = self.channel_tree.GetItemParent(parent)

        # 跳过隐藏根节点
        if not file_item.IsOk() or file_item == root:
            return

        file_name = self.channel_tree.GetItemText(file_item)
        full_path = f"{file_name}/{group_name}/{channel_name}"

        display_name = self._generate_display_name(channel_name, file_name)

        # 检查是否已存在
        exists = any(
            self.param_panel.grid.GetCellValue(i, 0) == display_name
            for i in range(self.param_panel.grid.GetNumberRows())
        )

        if not exists:
            self.param_panel.add_channel(display_name, full_path)
            self.status_bar.SetStatusText(f"已选择: {display_name}")
            self._redraw_timer.Stop()  # 取消防抖，立即重绘
            self._plot_selected_channels()

    def _generate_display_name(self, channel_name, file_name):
        """生成显示名称"""
        if len(self.data_manager.files_data) > 1:
            file_list = list(self.data_manager.files_data.keys())
            file_index = file_list.index(file_name) + 1
            return f"文件{file_index}|{channel_name}"
        return channel_name

    def _on_tree_right_click(self, event):
        """树形控件右键点击"""
        item = event.GetItem()
        if not item:
            return

        # 文件节点右键菜单
        if (self.channel_tree.ItemHasChildren(item) and
                self.channel_tree.GetItemParent(item) == self.channel_tree.GetRootItem()):
            menu = wx.Menu()
            unload_item = menu.Append(wx.ID_ANY, "卸载文件")
            self.Bind(wx.EVT_MENU, lambda e: self._on_unload_file(item), unload_item)
            self.PopupMenu(menu)
            menu.Destroy()

    def _on_unload_file(self, file_item):
        """卸载文件"""
        file_name = self.channel_tree.GetItemText(file_item)
        # 确认对话框
        dlg = wx.MessageDialog(self,
                               f"确定要卸载文件 '{file_name}' 吗？相关的参数将被清除。",
                               "确认卸载",
                               wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            # 先移除参数表格中的相关通道
            removed_count = self._remove_channels_from_grid(file_name)

            # 然后从数据管理器中移除
            self.data_manager.unload_file(file_name)
            self.channel_tree.Delete(file_item)

            # 重新绘图
            self._redraw_timer.Stop()  # 取消防抖，立即重绘
            self._plot_selected_channels()

            # 更新状态栏
            status_text = f"已卸载文件: {file_name}"
            if removed_count > 0:
                status_text += f" | 已移除 {removed_count} 个相关参数"
            remaining_files = len(self.data_manager.files_data)
            status_text += f" | 剩余文件: {remaining_files}"
            self.status_bar.SetStatusText(status_text)

        dlg.Destroy()

    def _remove_channels_from_grid(self, file_name):
        """从参数表格中移除文件相关通道"""
        rows_to_remove = []
        removed_count = 0

        # 查找所有相关的行 - 使用最优方法：通过channel_mapping检查完整路径
        for i in range(self.param_panel.grid.GetNumberRows()):
            channel_name = self.param_panel.grid.GetCellValue(i, 0)
            if not channel_name:
                continue

            # 最优方法：检查通道映射中的完整路径
            if self._is_channel_from_file(channel_name, file_name):
                rows_to_remove.append(i)

        # 逆序删除
        for i in sorted(rows_to_remove, reverse=True):
            channel_name = self.param_panel.grid.GetCellValue(i, 0)

            # 从各种集合中移除
            if channel_name in self.param_panel.show_actual_value_channels:
                self.param_panel.show_actual_value_channels.remove(channel_name)
            if channel_name in self.param_panel.top_channels:
                self.param_panel.top_channels.remove(channel_name)
            if channel_name in self.param_panel._channel_mapping:
                del self.param_panel._channel_mapping[channel_name]

            self.param_panel.grid.DeleteRows(i)
            removed_count += 1

        # 刷新表格外观
        if removed_count > 0:
            # 重新设置剩余行的颜色
            for row in range(self.param_panel.grid.GetNumberRows()):
                self.param_panel._refresh_row_appearance(row)
            self.param_panel.grid.ForceRefresh()

        return removed_count

    def _is_channel_from_file(self, channel_name, file_name):
        """检查通道是否属于指定文件"""
        if channel_name in self.param_panel._channel_mapping:
            full_path = self.param_panel._channel_mapping[channel_name]
            # 完整路径格式为 "文件名/组名/通道名"
            return full_path.startswith(file_name + "/")

        return False

    def _regenerate_display_names(self):
        """重新生成所有通道的显示名称（用于多文件状态下的文件索引更新）"""
        if len(self.data_manager.files_data) <= 1:
            # 单文件或没有文件，不需要更新显示名称
            return

        # 获取当前文件列表
        file_list = list(self.data_manager.files_data.keys())

        # 遍历所有参数行，更新显示名称
        for i in range(self.param_panel.grid.GetNumberRows()):
            old_display_name = self.param_panel.grid.GetCellValue(i, 0)
            if not old_display_name:
                continue

            # 获取完整路径
            full_path = self.param_panel._channel_mapping.get(old_display_name)
            if not full_path:
                continue

            # 解析完整路径
            parts = full_path.split("/")
            if len(parts) == 3:
                original_file_name, group_name, channel_name = parts

                # 查找文件在列表中的新位置
                if original_file_name in file_list:
                    file_index = file_list.index(original_file_name) + 1
                    new_display_name = f"文件{file_index}|{channel_name}"

                    # 更新显示名称
                    if new_display_name != old_display_name:
                        self.param_panel.grid.SetCellValue(i, 0, new_display_name)

                        # 更新映射关系
                        self.param_panel._channel_mapping[new_display_name] = full_path
                        if old_display_name in self.param_panel._channel_mapping:
                            del self.param_panel._channel_mapping[old_display_name]

                        # 更新集合中的名称
                        if old_display_name in self.param_panel.show_actual_value_channels:
                            self.param_panel.show_actual_value_channels.remove(old_display_name)
                            self.param_panel.show_actual_value_channels.add(new_display_name)

                        if old_display_name in self.param_panel.top_channels:
                            self.param_panel.top_channels.remove(old_display_name)
                            self.param_panel.top_channels.add(new_display_name)

        # 刷新表格
        self.param_panel.grid.ForceRefresh()

    def _on_parameter_changed(self):
        """参数改变事件（防抖：150ms内多次变化只重绘一次）"""
        self._redraw_timer.StartOnce(150)

    def _on_redraw_timer(self, event):
        """防抖定时器触发——执行实际重绘"""
        self._plot_selected_channels()

    def _on_vertical_lines_changed(self, red_line_x=None, blue_line_x=None):
        """竖直线改变事件"""
        self.param_panel.update_vertical_line_values(red_line_x, blue_line_x)

    def _plot_selected_channels(self):
        """绘制选中的通道"""
        if not self.param_panel.grid.GetNumberRows():
            self.plot_panel.clear_plot()
            return

        plots_data = []
        parameters = {}
        visible_channels = self.param_panel.get_visible_channels()

        # 收集参数和可见通道
        for i in range(self.param_panel.grid.GetNumberRows()):
            display_name = self.param_panel.grid.GetCellValue(i, 0)
            if not display_name or display_name not in visible_channels:
                continue

            full_path = self.param_panel._get_full_path(display_name)
            if not full_path:
                continue

            # 获取参数
            param_info = self._get_channel_parameters(i, display_name, full_path)
            if param_info:
                parameters[display_name] = param_info

        # 收集数据
        for display_name, param_info in parameters.items():
            channel_data = self._get_channel_data(param_info['full_path'])
            if channel_data is not None:
                time_axis = np.arange(len(channel_data)) * param_info['sample_time'] / 1000.0
                plots_data.append({
                    'x_data': time_axis,
                    'y_data': channel_data,
                    'name': display_name
                })

        if plots_data:
            show_actual_channels = self.param_panel.get_show_actual_value_channels()
            self.plot_panel.plot(plots_data, parameters, show_actual_channels, self.param_panel.top_channels)
            self.param_panel.update_statistics(plots_data)

            visible_count = len(visible_channels)
            plotted_count = len(plots_data)
            self.status_bar.SetStatusText(f"可见通道: {visible_count} | 已绘制: {plotted_count} | 就绪")
        else:
            self.plot_panel.clear_plot()

    def _get_channel_parameters(self, row, display_name, full_path):
        """获取通道参数"""
        try:
            sample_time = float(self.param_panel.grid.GetCellValue(row, 1))
        except ValueError:
            sample_time = Config.DEFAULT_SAMPLE_TIME

        try:
            linewidth = float(self.param_panel.grid.GetCellValue(row, 6))
        except ValueError:
            linewidth = Config.DEFAULT_LINEWIDTH

        linestyle = self.param_panel.grid.GetCellValue(row, 5)
        linestyle_val = Config.LINESTYLE_MAP.get(linestyle, '-')

        # 图例名称（col 7），为空时回退到通道名
        legend_name = self.param_panel.grid.GetCellValue(row, 7).strip()
        if not legend_name:
            legend_name = self._extract_simple_name(display_name)

        return {
            'sample_time': sample_time,
            'color': self.param_panel.grid.GetCellValue(row, 4),
            'linestyle': linestyle_val,
            'linewidth': linewidth,
            'legend_name': legend_name,
            'full_path': full_path
        }

    def _get_channel_data(self, full_path):
        """获取通道数据"""
        parts = full_path.split('/')
        if len(parts) == 3:
            file_name, group_name, channel_name = parts
            return self.data_manager.get_channel_data(file_name, group_name, channel_name)
        return None

    def _update_channel_tree(self, file_name):
        """为单个文件在树下添加节点（用于重建）"""
        root = self.channel_tree.GetRootItem()
        if not root.IsOk():
            root = self.channel_tree.AddRoot("TDMS文件")
        if file_name not in self.data_manager.files_data:
            return
        file_item = self.channel_tree.AppendItem(root, file_name)
        for group_name, channels in self.data_manager.files_data[file_name].items():
            group_item = self.channel_tree.AppendItem(file_item, group_name)
            for channel_name in channels.keys():
                self.channel_tree.AppendItem(group_item, channel_name)
            # 不自动展开组——通道参数太多，默认折叠，用户手动展开
        self.channel_tree.Expand(file_item)           # 展开文件，显示组名

    def _rebuild_full_tree(self):
        """根据 data_manager 的数据重建完整的树形结构"""
        self.channel_tree.DeleteAllItems()
        root = self.channel_tree.AddRoot("TDMS文件")
        if not self.data_manager.files_data:
            return
        for file_name in self.data_manager.files_data.keys():
            self._update_channel_tree(file_name)


if __name__ == "__main__":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PerMonitorV2 高清适配
    except Exception:
        pass
    app = wx.App(False)
    frame = SignalScapeFrame()
    frame.Show()
    app.MainLoop()