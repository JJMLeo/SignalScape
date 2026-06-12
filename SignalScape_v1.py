import wx
import wx.grid
import threading
import gc
import numpy as np
from nptdms import TdmsFile
import os.path as osp
import csv
import matplotlib as mpl
from collections import OrderedDict
import weakref

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
import matplotlib.pyplot as plt
from matplotlib.widgets import SpanSelector


class Config:
    """配置常量类"""
    DEFAULT_SAMPLE_TIME = 20.0
    DEFAULT_WINDOW_DURATION = 10.0
    DEFAULT_LINEWIDTH = 0.5
    EFFECTIVE_VALUE_METHODS = {
        "前后5秒平均值": 5.0,
        "前后3秒平均值": 3.0,
        "前后10秒平均值": 10.0,
        "前后1秒平均值": 1.0,
        "瞬时值": 0.0
    }
    COLOR_PALETTE = [
        "#FF0000",  # 红色
        "#0000FF",  # 蓝色
        "#00FF00",  # 绿色
        "#FF00FF",  # 洋红色
        "#00FFFF",  # 青色
        "#FFFF00",  # 黄色
        "#FFA500",  # 橙色
        "#800080",  # 紫色
        "#008000",  # 深绿色
        "#000080",  # 深蓝色
        "#800000",  # 深红色
        "#808000",  # 橄榄色
        "#008080",  # 蓝绿色
        "#FF4500",  # 橙红色
        "#2E8B57",  # 海绿色
        "#6A5ACD",  # 板岩蓝
        "#D2691E",  # 巧克力色
        "#DC143C",  # 深红色
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
    """数据管理类 - 异步诊断与容错加载版"""
    def __init__(self):
        self.files_data = OrderedDict()
        self.sample_time = Config.DEFAULT_SAMPLE_TIME
        self.effective_value_method = "前后5秒平均值"
        self.effective_value_window = 5.0
        self._loading_lock = threading.Lock()


    def load_tdms_file(self, file_path: str, progress_callback=None) -> bool:
        """
        真正的文件加载逻辑，包含诊断和备用加载方案。
        """
        file_name = osp.basename(file_path)
        # 提前在主线程中注册文件名，防止后台线程重复加载
        if file_name in self.files_data:
            return False
        self.files_data[file_name] = {}

        # --- 尝试主要加载方法 ---
        try:
            # 主要加载方式，使用nptdms的默认优化（通常是内存映射）
            with TdmsFile.open(file_path) as tdms_file:
                return self._process_tdms_data(tdms_file, file_name, progress_callback)

        except (Exception, KeyError, Exception) as e:
            print(f"--- 主要加载方式失败: {file_name} ---")
            print(f"错误类型: {type(e).__name__}")
            print(f"错误信息: {str(e)}")
            print("-----------------------------------------\n")
            print("尝试备用加载方式（禁用内存映射）...")

            # --- 尝试备用加载方法 ---
            try:
                # 备用加载方式：禁用内存映射 (mmap=False)
                # 这对于某些网络驱动器、特殊文件系统或文件损坏的情况更健壮
                with TdmsFile.open(file_path, mmap=False) as tdms_file:
                    print("备用加载方式成功！")
                    return self._process_tdms_data(tdms_file, file_name, progress_callback)

            except (Exception, KeyError, Exception) as e_backup:
                # --- 两种方式都失败，进行详细诊断并清理 ---
                print(f"--- 备用加载方式也失败: {file_name} ---")
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

                # 在UI上显示一个详细的错误报告
                final_error_msg = (
                    f"加载文件失败: {file_name}\n\n"
                    f"主要加载错误:\n{type(e).__name__}: {str(e)}\n\n"
                    f"备用加载错误:\n{type(e_backup).__name__}: {str(e_backup)}\n\n"
                    f"请检查文件是否损坏，或尝试重命名文件（避免使用方括号[]等特殊字符）。"
                )
                wx.CallAfter(wx.MessageBox, final_error_msg, "文件加载错误", wx.OK | wx.ICON_ERROR)
                return False


    def _process_tdms_data(self, tdms_file, file_name, progress_callback):
        """处理已打开的TdmsFile对象，提取数据"""
        try:
            total_channels = sum(len(group.channels()) for group in tdms_file.groups())
        except Exception:
            total_channels = 0

        loaded_channels = 0
        for group in tdms_file.groups():
            group_name = group.name
            self.files_data[file_name][group_name] = {}
            for channel in group.channels():
                channel_name = channel.name

                if total_channels > 0 and progress_callback:
                    loaded_channels += 1
                    progress = int((loaded_channels / total_channels) * 100)

                    display_message = (
                        f"正在加载文件:\n{file_name}\n"
                        f"当前通道: {group_name} / {channel_name}"
                    )
                    wx.CallAfter(progress_callback, progress, display_message)

                data = np.asarray(channel[:])
                self.files_data[file_name][group_name][channel_name] = data

        return True


    def _load_file_in_thread(self, file_path: str, parent_window, on_finish_callback):
        """在后台线程中执行加载任务的内部方法。"""
        original_file_name = osp.basename(file_path)
        progress_dialog = ProgressDialog(parent_window, "加载文件", f"准备加载文件:\n{original_file_name}")

        def progress_callback(value, message):
            wx.CallAfter(progress_dialog.update, value, message)

        def target():
            with self._loading_lock:
                if original_file_name in self.files_data and len(self.files_data[original_file_name]) > 0:
                    wx.CallAfter(progress_dialog.close)
                    wx.CallAfter(wx.MessageBox, f"文件 '{original_file_name}' 已经打开！", "提示",
                                 wx.OK | wx.ICON_INFORMATION)
                    return

                success = self.load_tdms_file(file_path, progress_callback)

                wx.CallAfter(progress_dialog.close)
                if on_finish_callback:
                    wx.CallAfter(on_finish_callback, file_path, success)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        progress_dialog.ShowModal()
        progress_dialog.Destroy()


    def load_tdms_file_with_progress(self, file_path: str, parent_window, on_finish_callback=None) -> None:
        """启动带进度条的异步文件加载。"""
        thread = threading.Thread(
            target=self._load_file_in_thread,
            args=(file_path, parent_window, on_finish_callback),
            daemon=True
        )
        thread.start()


    # --- unload_file 等其他方法保持不变 ---
    def unload_file(self, file_name: str):
        """卸载文件"""
        if file_name in self.files_data:
            del self.files_data[file_name]
            gc.collect()


    def get_channel_data(self, file_name: str, group_name: str, channel_name: str):
        """获取通道数据"""
        try:
            return self.files_data[file_name][group_name][channel_name]
        except KeyError:
            return None


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
        gc.collect()

class ColorRenderer(wx.grid.GridCellRenderer):
    """颜色渲染器"""

    def __init__(self):
        super().__init__()

    def Draw(self, grid, attr, dc, rect, row, col, isSelected):
        dc.SetBackgroundMode(wx.SOLID)
        color_value = grid.GetCellValue(row, col)

        if color_value:
            try:
                color = wx.Colour(color_value)
                dc.SetBrush(wx.Brush(color))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawRectangle(rect)
            except:
                dc.SetBrush(wx.Brush(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)))
                dc.SetPen(wx.TRANSPARENT_PEN)
                dc.DrawRectangle(rect)

        dc.SetTextForeground(wx.BLACK)
        dc.DrawText(color_value, rect.x + 2, rect.y + 2)

    def GetBestSize(self, grid, attr, dc, row, col):
        text = grid.GetCellValue(row, col)
        w, h = dc.GetTextExtent(text)
        return wx.Size(w + 4, h + 4)

    def Clone(self):
        return ColorRenderer()


class LineStyleRenderer(wx.grid.GridCellRenderer):
    """线型渲染器"""

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

        dc.SetTextForeground(wx.BLACK)
        dc.DrawText(linestyle, rect.x + 2, rect.y + 2)

    def GetBestSize(self, grid, attr, dc, row, col):
        text = grid.GetCellValue(row, col)
        w, h = dc.GetTextExtent(text)
        return wx.Size(w + 4, h + 4)

    def Clone(self):
        return LineStyleRenderer()


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

        # --- 核心修复点：设置一个足够大的、固定的初始尺寸 ---
        # 这个高度 (250) 应该能舒适地容纳所有内容，无需滚动。
        super().__init__(parent, title=title, size=(best_width, 200))

        self.parent = parent

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

        # --- 修改点: 恢复 proportion=1 ---
        # 让消息区域占据所有剩余的垂直空间
        main_sizer.Add(self.message_ctrl, 1, wx.ALL | wx.EXPAND, 10)

        # --- 进度条容器面板 ---
        self.progress_panel = wx.Panel(panel)
        main_sizer.Add(self.progress_panel, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)

        # 进度条
        self.gauge = wx.Gauge(self.progress_panel, range=100, style=wx.GA_HORIZONTAL)

        # 百分比文本 (已隐藏)
        self.progress_label = wx.StaticText(self.progress_panel, label="0%", style=wx.ALIGN_CENTER)
        self.progress_label.Hide()

        panel.SetSizer(main_sizer)

        self.progress_panel.Bind(wx.EVT_SIZE, self.on_progress_panel_resize)

        self.Centre()

        # 窗口大小确定后，再初始化进度条
        wx.CallAfter(self.on_progress_panel_resize)

    def on_progress_panel_resize(self, event=None):
        """当容器面板尺寸变化时，更新进度条尺寸"""
        panel_size = self.progress_panel.GetSize()
        self.gauge.SetSize(panel_size)
        if event:
            event.Skip()

    def update(self, value, message=None):
        """更新进度"""
        if message:
            self.message_ctrl.SetValue(message)

        self.gauge.SetValue(value)

        # --- 核心修复点：移除所有动态调整尺寸的代码 ---
        # 窗口大小现在是固定的，不需要再调整。
        # 只需刷新进度条面板即可。
        self.progress_panel.Refresh()

    def close(self):
        """关闭对话框"""
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


class ParameterGridPanel(wx.Panel):
    """参数表格面板"""

    def __init__(self, parent, on_parameter_changed_callback):
        super().__init__(parent)
        self.on_parameter_changed = on_parameter_changed_callback
        self.show_actual_value_channels = set()
        self.top_channels = set()
        self._channel_mapping = {}
        self.last_selected_cell = None

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
        self.grid.CreateGrid(0, 16)

        # 设置列标签
        columns = [
            "参数名称", "采样间隔(ms)", "绘制曲线", "显示实际值", "曲线颜色",
            "曲线线型", "线宽", "最大值", "最小值", "区域均值",
            "区域最大值", "区域最小值", "红轴数值", "蓝轴数值",
            "红轴有效值", "蓝轴有效值"
        ]

        for i, label in enumerate(columns):
            self.grid.SetColLabelValue(i, label)

        # 设置列宽
        col_sizes = [200, 100, 80, 80, 100, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80, 80]
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
        """设置特殊列（颜色、线型等）"""
        # 复选框列
        for col in [2, 3]:
            attr = wx.grid.GridCellAttr()
            attr.SetRenderer(CheckboxRenderer())
            self.grid.SetColAttr(col, attr)

        # 颜色列
        color_attr = wx.grid.GridCellAttr()
        color_editor = wx.grid.GridCellChoiceEditor(Config.COLOR_PALETTE)
        color_attr.SetEditor(color_editor)
        color_attr.SetRenderer(ColorRenderer())
        self.grid.SetColAttr(4, color_attr)

        # 线型列
        linestyle_attr = wx.grid.GridCellAttr()
        linestyle_editor = wx.grid.GridCellChoiceEditor(Config.LINESTYLE_CHOICES)
        linestyle_attr.SetEditor(linestyle_editor)
        linestyle_attr.SetRenderer(LineStyleRenderer())
        self.grid.SetColAttr(5, linestyle_attr)

        # 线宽列
        linewidth_attr = wx.grid.GridCellAttr()
        linewidth_editor = wx.grid.GridCellChoiceEditor(Config.LINEWIDTH_CHOICES)
        linewidth_attr.SetEditor(linewidth_editor)
        self.grid.SetColAttr(6, linewidth_attr)

    def _setup_event_bindings(self):
        """设置事件绑定"""
        self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self._on_cell_changed)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_LEFT_DCLICK, self._on_cell_double_click)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_LEFT_CLICK, self._on_cell_left_click)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_RIGHT_CLICK, self._on_cell_right_click)
        self.grid.Bind(wx.grid.EVT_GRID_SELECT_CELL, self._on_cell_select)
        self.grid.Bind(wx.EVT_CONTEXT_MENU, self._on_grid_context_menu)

    def _on_grid_context_menu(self, event):
        """网格上下文菜单事件 - 修复空白区域右键"""
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
        """显示空白区域右键菜单 - 修复版本"""
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
        """清除全部参数 - 修复版本"""
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

        event.Skip()

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

    def _redistribute_colors_if_needed(self):
        """在删除行后重新分配颜色以保持连续性"""
        row_count = self.grid.GetNumberRows()
        if row_count <= 1:
            return

        # 检查颜色是否连续
        colors = []
        for i in range(row_count):
            color = self.grid.GetCellValue(i, 4)
            colors.append(color)

        # 如果颜色不连续，重新分配
        if not self._is_color_sequence_continuous(colors):
            self._redistribute_colors()

    def _is_color_sequence_continuous(self, colors):
        """检查颜色序列是否连续"""
        if not colors:
            return True

        # 查找第一个颜色在调色板中的位置
        try:
            first_color_index = Config.COLOR_PALETTE.index(colors[0])
        except ValueError:
            return False

        # 检查后续颜色是否按顺序
        for i, color in enumerate(colors):
            expected_index = (first_color_index + i) % len(Config.COLOR_PALETTE)
            if color != Config.COLOR_PALETTE[expected_index]:
                return False

        return True

    def _redistribute_colors(self):
        """重新分配所有行的颜色"""
        row_count = self.grid.GetNumberRows()
        for i in range(row_count):
            color = Config.COLOR_PALETTE[i % len(Config.COLOR_PALETTE)]
            self.grid.SetCellValue(i, 4, color)

        self.grid.ForceRefresh()


    def update_statistics(self, plots_data):
        """更新统计信息"""
        channel_data_map = {plot_data['name']: plot_data for plot_data in plots_data}

        for i in range(self.grid.GetNumberRows()):
            channel_name = self.grid.GetCellValue(i, 0)
            if not channel_name or channel_name not in channel_data_map:
                continue

            y_data = channel_data_map[channel_name]['y_data']
            max_val, min_val = np.max(y_data), np.min(y_data)

            self.grid.SetCellValue(i, 7, f"{max_val:.6f}")
            self.grid.SetCellValue(i, 8, f"{min_val:.6f}")

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
            for col in range(9, 12):
                self.grid.SetCellValue(i, col, "")

            # 更新红轴数值
            if red_line_x is not None:
                red_value = self._get_original_value(plot_panel, channel_name, red_line_x)
                self.grid.SetCellValue(i, 12, red_value)
                red_effective = self._calculate_effective_value(plot_panel, channel_name, red_line_x)
                self.grid.SetCellValue(i, 14, red_effective)
            else:
                self.grid.SetCellValue(i, 12, "")
                self.grid.SetCellValue(i, 14, "")

            # 更新蓝轴数值
            if blue_line_x is not None:
                blue_value = self._get_original_value(plot_panel, channel_name, blue_line_x)
                self.grid.SetCellValue(i, 13, blue_value)
                blue_effective = self._calculate_effective_value(plot_panel, channel_name, blue_line_x)
                self.grid.SetCellValue(i, 15, blue_effective)
            else:
                self.grid.SetCellValue(i, 13, "")
                self.grid.SetCellValue(i, 15, "")

            # 计算区域统计
            if red_line_x is not None and blue_line_x is not None:
                region_start, region_end = sorted([red_line_x, blue_line_x])
                region_stats = self._get_region_statistics(plot_panel, channel_name, region_start, region_end)
                if region_stats:
                    self.grid.SetCellValue(i, 9, f"{region_stats['mean']:.6f}")
                    self.grid.SetCellValue(i, 10, f"{region_stats['max']:.6f}")
                    self.grid.SetCellValue(i, 11, f"{region_stats['min']:.6f}")

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
        """单元格双击事件"""
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
        self.span_selector = None
        self.dragging = None
        self.right_axes_dict = {}
        self.x_max = Config.DEFAULT_WINDOW_DURATION

        self._create_ui()
        self._setup_event_bindings()

    def _create_ui(self):
        """创建用户界面"""
        self.figure = Figure(figsize=(10, 6), dpi=100)
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
            btn.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            btn.Bind(wx.EVT_BUTTON, handler)
            sizer.Add(btn, 0, wx.ALL, 5)

        # 窗口时长
        sizer.Add(wx.StaticText(panel, label="  窗口时长（s）:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)
        self.window_duration = wx.TextCtrl(panel, value="10.0", size=(60, -1), style=wx.TE_PROCESS_ENTER)
        self.window_duration.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.window_duration, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        # 竖直线控制
        sizer.Add(wx.StaticText(panel, label="  竖直线:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.red_line_check = wx.CheckBox(panel, label="红色")
        self.red_line_check.SetValue(False)
        sizer.Add(self.red_line_check, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        self.blue_line_check = wx.CheckBox(panel, label="蓝色")
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

    def plot(self, plots_data, parameters, show_actual_value_channels=None, top_channels=None):
        """绘制数据"""
        if show_actual_value_channels is None:
            show_actual_value_channels = set()
        if top_channels is None:
            top_channels = set()

        self._clear_plot()
        self._prepare_plot_data(plots_data, parameters, show_actual_value_channels, top_channels)
        self._setup_plot_appearance()
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
        linestyle = Config.LINESTYLE_MAP.get(param.get('linestyle', '实线'), '-')
        linewidth = float(param.get('linewidth', Config.DEFAULT_LINEWIDTH))

        show_actual = name in show_actual_value_channels
        is_top = name in top_channels

        # 百分比归一化
        y_data = plot_data['y_data']
        if self._is_percent_mode() and not show_actual:
            y_min, y_max = np.min(y_data), np.max(y_data)
            if y_max != y_min:
                y_data = (y_data - y_min) / (y_max - y_min) * 100

        return {
            'x_data': plot_data['x_data'],
            'y_data': y_data,
            'name': name,
            'display_name': simple_name,
            'color': color,
            'linestyle': linestyle,
            'linewidth': linewidth,
            'show_actual': show_actual,
            'is_top': is_top,
            'original_data': plot_data['y_data']
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
            right_ax.set_ylabel(simple_name, fontsize=8)
            right_ax.set_xlim(self.axes.get_xlim())

            self.right_axes_dict[channel_name] = right_ax

            # 绘制实际值数据
            self._draw_actual_value(right_ax, channel_name, parameters)

    def _draw_actual_value(self, right_ax, channel_name, parameters):
        """在右侧Y轴绘制实际值"""
        channel_data = self.original_data[channel_name]
        param = parameters[channel_name]

        color = param.get('color', '#1f77b4')
        linestyle = Config.LINESTYLE_MAP.get(param.get('linestyle', '实线'), '-')
        linewidth = float(param.get('linewidth', Config.DEFAULT_LINEWIDTH))

        is_top = channel_name in getattr(self.GetTopLevelParent().param_panel, 'top_channels', set())
        zorder = 10 if is_top else 1

        simple_name = self._extract_simple_name(channel_name)
        label_parts = [simple_name]
        if not self._is_percent_mode():
            label_parts.append("实际值")
        label = " ".join(label_parts)

        line, = right_ax.plot(channel_data['x'], channel_data['y'],
                              label=label, color=color, linestyle=linestyle,
                              linewidth=linewidth, zorder=zorder)

        self.current_plots[channel_name] = line

    def _draw_single_plot(self, plot_info):
        """绘制单个通道"""
        zorder = 10 if plot_info['is_top'] else 1

        line, = self.axes.plot(
            plot_info['x_data'], plot_info['y_data'],
            label=f"{plot_info['display_name']}",
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
            self.axes.legend(lines, labels, loc='upper right', fontsize=8)

        # 添加范围选择器
        if self.span_selector:
            self.span_selector.disconnect_events()
        self.span_selector = SpanSelector(self.axes, self._on_span_select, 'horizontal',
                                          useblit=True, props=dict(alpha=0.2, facecolor='red'))

    def _finalize_plot(self):
        """完成绘图设置"""
        self.figure.tight_layout()
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
        """鼠标移动事件"""
        if event.inaxes != self.axes or not self.dragging or event.xdata is None:
            return

        if self.dragging == 'red':
            self.red_line_x = event.xdata
        elif self.dragging == 'blue':
            self.blue_line_x = event.xdata

        self._update_vertical_lines()

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
        """更新竖直线"""
        # 移除现有线
        for line in [self.red_line, self.blue_line]:
            if line:
                line.remove()

        self.red_line = self.blue_line = None

        # 添加新线
        if self.red_line_check.GetValue() and self.red_line_x is not None:
            self.red_line = self.axes.axvline(x=self.red_line_x, color='red',
                                              linewidth=2, linestyle='-', zorder=10, alpha=0.8)

        if self.blue_line_check.GetValue() and self.blue_line_x is not None:
            self.blue_line = self.axes.axvline(x=self.blue_line_x, color='blue',
                                               linewidth=2, linestyle='-', zorder=10, alpha=0.8)

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

        # 收集主Y轴数据
        y_data_main = []
        for name, line in self.current_plots.items():
            if name not in self.right_axes_dict:
                y_data_main.extend(line.get_ydata())

        if y_data_main:
            y_min, y_max = np.min(y_data_main), np.max(y_data_main)
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
                status_text = f"📊 缩放已复原 | 数据范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s"
            elif is_duration_change:
                status_text = f"⚙️ 窗口时长已设置 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s"
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
                    status_text = f"🔍 已缩放 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s | 缩放: {zoom_ratio:.1f}x | 数据点: {visible_points}"
                else:
                    status_text = f"🔍 已缩放 | 范围: {xmin:.2f}s - {xmax:.2f}s | 时长: {duration:.2f}s | 缩放: {zoom_ratio:.1f}x"

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
        """保存图像"""
        if not self.current_plots:
            wx.MessageBox("没有图像可保存", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        wildcard = "PNG files (*.png)|*.png|JPEG files (*.jpg)|*.jpg|PDF files (*.pdf)|*.pdf|All files (*.*)|*.*"
        with wx.FileDialog(self, "保存图像", wildcard=wildcard,
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                try:
                    self.figure.savefig(dialog.GetPath(), dpi=300, bbox_inches='tight')
                    wx.MessageBox(f"图像已保存到: {dialog.GetPath()}", "成功", wx.OK | wx.ICON_INFORMATION)
                except Exception as e:
                    wx.MessageBox(f"保存图像失败: {str(e)}", "错误", wx.OK | wx.ICON_ERROR)

    def _export_data_advanced(self, file_path):
        """高级数据导出"""
        if not self.original_data:
            return

        # 按采样间隔分组
        groups = {}
        for channel_name, channel_data in self.original_data.items():
            sample_time = self._get_channel_sample_time(channel_name)
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

                simple_name = self._extract_simple_name(display_name)
                parameter_names.append(simple_name)

                if has_red_line:
                    red_values.append(param_panel.grid.GetCellValue(i, 12))
                    red_effective_values.append(param_panel.grid.GetCellValue(i, 14))

                if has_blue_line:
                    blue_values.append(param_panel.grid.GetCellValue(i, 13))
                    blue_effective_values.append(param_panel.grid.GetCellValue(i, 15))

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

        self._create_ui()
        self._create_menu()
        self._create_status_bar()

    def _get_display_index(self):
        """获取显示索引"""
        mouse_pos = wx.GetMousePosition()
        for i in range(wx.Display.GetCount()):
            if wx.Display(i).GetGeometry().Contains(mouse_pos):
                return i
        return 0

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
        self.search_ctrl = wx.TextCtrl(search_panel, style=wx.TE_PROCESS_ENTER)

        search_sizer.Add(search_text, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        search_sizer.Add(self.search_ctrl, 1, wx.EXPAND)
        search_panel.SetSizer(search_sizer)

        # 通道树
        self.channel_tree = wx.TreeCtrl(panel,
                                        style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_FULL_ROW_HIGHLIGHT)

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
        right_splitter.SetSashPosition(int(self.GetSize().height * 2 // 3))

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(right_splitter, 1, wx.EXPAND)
        panel.SetSizer(sizer)

        return panel

    def _create_menu(self):
        """创建菜单"""
        menubar = wx.MenuBar()

        # 文件菜单
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, "打开TDMS文件", "打开TDMS数据文件")
        batch_open_item = file_menu.Append(wx.ID_ANY, "批量打开", "批量打开多个TDMS文件")

        # 工具菜单
        tool_menu = wx.Menu()
        effective_value_item = tool_menu.Append(wx.ID_ANY, "有效值获取方式", "设置有效值计算方法")

        menubar.Append(file_menu, "文件")
        menubar.Append(tool_menu, "工具")
        self.SetMenuBar(menubar)

        # 事件绑定
        self.Bind(wx.EVT_MENU, self._on_open, open_item)
        self.Bind(wx.EVT_MENU, self._on_batch_open, batch_open_item)
        self.Bind(wx.EVT_MENU, self._on_effective_value_settings, effective_value_item)

    def _create_status_bar(self):
        """创建状态栏"""
        self.status_bar = self.CreateStatusBar(1)
        self.status_bar.SetStatusText("就绪")

    def _on_open(self, event):
        """打开文件"""
        wildcard = "TDMS files (*.tdms)|*.tdms|All files (*.*)|*.*"
        with wx.FileDialog(self, "打开TDMS文件", wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self._handle_file_open(dialog.GetPath())

    def _on_batch_open(self, event):
        """批量打开文件 - 优化版本"""
        wildcard = "TDMS files (*.tdms)|*.tdms|All files (*.*)|*.*"
        with wx.FileDialog(self, "批量打开TDMS文件", wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                file_paths = dialog.GetPaths()
                success_count = 0

                # 批量处理进度条
                progress_dialog = ProgressDialog(self, "批量加载", f"正在批量加载 {len(file_paths)} 个文件")
                progress_dialog.Show()

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
                self.SetStatusText(f"已加载文件: {osp.basename(loaded_file_path)}")
            else:
                wx.MessageBox(
                    f"加载文件失败: {osp.basename(loaded_file_path)}",
                    "错误",
                    wx.OK | wx.ICON_ERROR
                )
                self.SetStatusText("文件加载失败")

        # --- 核心修正：使用正确的公共方法进行异步加载 ---
        # 传入文件路径、父窗口和加载完成后的回调函数
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
        """有效值设置"""
        choices = list(Config.EFFECTIVE_VALUE_METHODS.keys())
        dlg = wx.SingleChoiceDialog(self, "选择有效值计算方法:", "有效值获取方式", choices)

        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()
            method_name = choices[selection]
            self.data_manager.effective_value_method = method_name
            self.data_manager.effective_value_window = Config.EFFECTIVE_VALUE_METHODS[method_name]

            self.status_bar.SetStatusText(f"有效值计算方法: {method_name}")
            self._update_effective_values()

        dlg.Destroy()

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
        group_name = self.channel_tree.GetItemText(parent)
        file_item = self.channel_tree.GetItemParent(parent)
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

        # 从后往前删除，避免索引问题
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
        """参数改变事件"""
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

        return {
            'sample_time': sample_time,
            'color': self.param_panel.grid.GetCellValue(row, 4),
            'linestyle': linestyle_val,
            'linewidth': linewidth,
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
        self.channel_tree.Expand(file_item)

    def _on_search(self, event):
        """实时搜索并重建树形控件"""
        search_term = self.search_ctrl.GetValue().strip()

        # 如果搜索框为空，恢复所有节点显示
        if not search_term:
            self._rebuild_full_tree()
            self.status_bar.SetStatusText("就绪")
            return

        # 清空当前树
        self.channel_tree.DeleteAllItems()
        root = self.channel_tree.AddRoot("TDMS文件")

        matched_count = 0
        search_term_lower = search_term.lower()

        # 遍历所有已加载的文件数据
        for file_name, groups in self.data_manager.files_data.items():
            file_item = None
            # 检查文件名是否匹配
            if search_term_lower in file_name.lower():
                file_item = self.channel_tree.AppendItem(root, file_name)
                matched_count += 1

            # 遍历组
            for group_name, channels in groups.items():
                group_item = None
                # 检查组名是否匹配
                if search_term_lower in group_name.lower():
                    # 如果文件还没创建，先创建文件节点
                    if not file_item:
                        file_item = self.channel_tree.AppendItem(root, file_name)
                    group_item = self.channel_tree.AppendItem(file_item, group_name)
                    matched_count += 1

                # 遍历通道
                for channel_name in channels.keys():
                    # 检查通道名是否匹配
                    if search_term_lower in channel_name.lower():
                        # 如果文件和组还没创建，先创建它们
                        if not file_item:
                            file_item = self.channel_tree.AppendItem(root, file_name)
                        if not group_item:
                            group_item = self.channel_tree.AppendItem(file_item, group_name)

                        self.channel_tree.AppendItem(group_item, channel_name)
                        matched_count += 1

            # 如果文件节点下有内容，则展开它
            if file_item and self.channel_tree.ItemHasChildren(file_item):
                self.channel_tree.Expand(file_item)

        # 更新状态栏
        if matched_count > 0:
            self.status_bar.SetStatusText(f"搜索: '{search_term}' | 找到 {matched_count} 个结果")
        else:
            self.status_bar.SetStatusText(f"搜索: '{search_term}' | 未找到匹配项")

    def _rebuild_full_tree(self):
        """根据 data_manager 的数据重建完整的树形结构"""
        self.channel_tree.DeleteAllItems()
        root = self.channel_tree.AddRoot("TDMS文件")
        if not self.data_manager.files_data:
            return
        for file_name in self.data_manager.files_data.keys():
            self._update_channel_tree(file_name)

    def _on_clear_search(self, event):
        """清除搜索框内容并重置显示"""
        if hasattr(self, 'search_ctrl'):
            self.search_ctrl.SetValue("")


if __name__ == "__main__":
    app = wx.App(False)
    frame = SignalScapeFrame()
    frame.Show()
    app.MainLoop()