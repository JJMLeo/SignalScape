# -*- coding: utf-8 -*-
"""SignalScape (PySide2 版) 自动化测试。

运行::

    python -m unittest discover -s tests -v

说明：
* 使用 QT_QPA_PLATFORM=offscreen，无需真实显示设备；
* 屏蔽 QMessageBox，避免测试被模态对话框阻塞；
* 样本文件由 tests/make_fixtures.py 生成到 tests/fixtures/。
"""
import datetime
import os
import sys
import types
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
FIXTURES = os.path.join(ROOT, 'tests', 'fixtures')

from PySide2.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

import numpy as np  # noqa: E402

import SignalScape_pyside as ss  # noqa: E402

# 屏蔽所有模态对话框，防止测试阻塞
_ss_info = ss.QMessageBox.information
_ss_critical = ss.QMessageBox.critical
ss.QMessageBox.information = staticmethod(lambda *a, **k: None)
ss.QMessageBox.critical = staticmethod(lambda *a, **k: None)

TDMS_PATH = os.path.join(FIXTURES, 'sample.tdms')
XLSX_PATH = os.path.join(FIXTURES, 'sample.xlsx')
MIDNIGHT_PATH = os.path.join(FIXTURES, 'midnight.xlsx')


def _fake_panel(data):
    """构造一个仅含 original_data 的伪 plot panel（用于纯函数测试）"""
    return types.SimpleNamespace(original_data=data)


class TestParseHms(unittest.TestCase):
    def test_hms_text(self):
        self.assertAlmostEqual(ss.DataManager._parse_hms_to_seconds('1:02:03'), 3723.0)

    def test_hm_text(self):
        self.assertAlmostEqual(ss.DataManager._parse_hms_to_seconds('12:30'), 45000.0)

    def test_fractional_seconds(self):
        self.assertAlmostEqual(ss.DataManager._parse_hms_to_seconds('00:00:01.5'), 1.5)

    def test_reject_trailing_junk(self):
        """非法后缀不应被静默截断为合法时间"""
        self.assertIsNone(ss.DataManager._parse_hms_to_seconds('1:02:03abc'))

    def test_plain_seconds(self):
        self.assertAlmostEqual(ss.DataManager._parse_hms_to_seconds(123.5), 123.5)

    def test_excel_day_fraction(self):
        self.assertAlmostEqual(ss.DataManager._parse_hms_to_seconds(0.5), 43200.0)

    def test_time_object(self):
        self.assertAlmostEqual(
            ss.DataManager._parse_hms_to_seconds(datetime.time(1, 2, 3)), 3723.0)

    def test_invalid(self):
        self.assertIsNone(ss.DataManager._parse_hms_to_seconds('abc'))
        self.assertIsNone(ss.DataManager._parse_hms_to_seconds(None))


class TestMonotonicSeconds(unittest.TestCase):
    def test_normal(self):
        arr = np.array([0.0, 1.0, 2.0, 3.0])
        out = ss.DataManager._to_monotonic_seconds(arr)
        np.testing.assert_allclose(out, [0.0, 1.0, 2.0, 3.0])

    def test_cross_midnight(self):
        """23:59:58 → 00:00:03 跨零点应连续递增，不能出现负数"""
        arr = np.array([86398.0, 86399.0, 0.0, 1.0, 2.0, 3.0])
        out = ss.DataManager._to_monotonic_seconds(arr)
        np.testing.assert_allclose(out, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])

    def test_always_increasing(self):
        arr = np.array([10.0, 9.0, 8.0])
        out = ss.DataManager._to_monotonic_seconds(arr)
        self.assertTrue(np.all(np.diff(out) > 0))


class TestDownsample(unittest.TestCase):
    def test_short_data_untouched(self):
        x = np.linspace(0, 10, 100)
        y = np.sin(x)
        ox, oy = ss.MatplotlibPlotPanel._downsample(x, y, threshold=1000)
        self.assertIs(ox, x)
        self.assertIs(oy, y)

    def test_output_shape_and_endpoints(self):
        x = np.linspace(0, 100, 5000)
        y = np.sin(x) + np.linspace(0, 5, 5000)
        ox, oy = ss.MatplotlibPlotPanel._downsample(x, y, threshold=1000)
        self.assertEqual(len(ox), 1000)
        self.assertEqual(len(oy), 1000)
        self.assertAlmostEqual(ox[0], x[0])
        self.assertAlmostEqual(ox[-1], x[-1])
        self.assertAlmostEqual(oy[0], y[0])
        self.assertAlmostEqual(oy[-1], y[-1])

    def test_no_nan(self):
        """各种桶大小组合下都不能产出 NaN（空切片 mean 会导致静默失真）"""
        for n, th in ((1001, 1000), (5000, 1000), (10000, 999), (12345, 4000)):
            x = np.linspace(0, 100, n)
            y = np.sin(x)
            ox, oy = ss.MatplotlibPlotPanel._downsample(x, y, threshold=th)
            self.assertEqual(len(ox), th)
            self.assertFalse(np.any(np.isnan(ox)), msg='x 含 NaN: n=%d th=%d' % (n, th))
            self.assertFalse(np.any(np.isnan(oy)), msg='y 含 NaN: n=%d th=%d' % (n, th))

    def test_shape_preserved(self):
        """降采样必须保留波形特征（极值不丢失）"""
        n = 20000
        x = np.linspace(0, 20, n)
        y = np.sin(x) * 10
        ox, oy = ss.MatplotlibPlotPanel._downsample(x, y, threshold=4000)
        self.assertGreater(oy.max(), 9.5)
        self.assertLess(oy.min(), -9.5)


class TestDataManagerCache(unittest.TestCase):
    def test_put_cache_bounded(self):
        dm = ss.DataManager()
        limit = getattr(ss.Config, 'CACHE_MAX_ITEMS', None)
        self.assertIsNotNone(limit, 'Config 缺少 CACHE_MAX_ITEMS')
        for i in range(limit + 20):
            dm._put_cache(('f', 'g', str(i)), np.zeros(8))
        self.assertLessEqual(len(dm._data_cache), limit)

    def test_cache_lru_order(self):
        dm = ss.DataManager()
        limit = ss.Config.CACHE_MAX_ITEMS
        for i in range(limit):
            dm._put_cache(('f', 'g', str(i)), np.zeros(8))
        dm._put_cache(('f', 'g', 'new'), np.ones(8))
        self.assertIn(('f', 'g', 'new'), dm._data_cache)
        self.assertNotIn(('f', 'g', '0'), dm._data_cache)

    def test_get_unknown_channel_returns_none(self):
        dm = ss.DataManager()
        self.assertIsNone(dm.get_channel_data('nope', 'g', 'c'))

    def test_unload_releases_cache(self):
        dm = ss.DataManager()
        dm._put_cache(('f', 'g', 'c'), np.zeros(8))
        dm.files_data['f'] = {'g': {}}
        dm.unload_file('f')
        self.assertEqual(len(dm._data_cache), 0)


class TestDataManagerLoad(unittest.TestCase):
    def setUp(self):
        self.dm = ss.DataManager()

    def test_load_tdms(self):
        self.assertTrue(self.dm.load_tdms_file(TDMS_PATH))
        self.assertIn('sample.tdms', self.dm.files_data)
        group = self.dm.files_data['sample.tdms']['试验组']
        self.assertIn('温度', group)
        self.assertIn('压力', group)

    def test_filter_rules_applied(self):
        self.dm.load_tdms_file(TDMS_PATH)
        group = self.dm.files_data['sample.tdms']['试验组']
        self.assertNotIn('转速_status', group)   # 命中 '*_status'
        self.assertNotIn('故障标志', group)       # 命中 '故障'

    def test_channel_values(self):
        self.dm.load_tdms_file(TDMS_PATH)
        data = self.dm.get_channel_data('sample.tdms', '试验组', '温度')
        self.assertIsNotNone(data)
        self.assertEqual(len(data), 1000)
        self.assertAlmostEqual(data[0], 50.0, places=5)

    def test_dispatch_by_extension(self):
        """load_file_by_ext 应按扩展名分派，Excel 不能走 TDMS 加载流程"""
        self.assertTrue(self.dm.load_file_by_ext(XLSX_PATH))
        self.assertTrue(self.dm.load_file_by_ext(TDMS_PATH))
        self.assertFalse(self.dm.load_file_by_ext('unknown.bin'))

    def test_unload_closes_tdms(self):
        self.dm.load_tdms_file(TDMS_PATH)
        self.dm.unload_file('sample.tdms')
        self.assertNotIn('sample.tdms', self.dm.tdms_files)


class TestExcelLoad(unittest.TestCase):
    def setUp(self):
        self.dm = ss.DataManager()

    def test_load_xlsx(self):
        self.assertTrue(self.dm.load_excel_file(XLSX_PATH))
        file_data = self.dm.files_data['sample.xlsx']
        group_name = list(file_data.keys())[0]
        self.assertIn('温度', file_data[group_name])
        self.assertIn('压力', file_data[group_name])
        self.assertNotIn('状态_status', file_data[group_name])

    def test_time_axis_length_matches(self):
        self.dm.load_excel_file(XLSX_PATH)
        (axis,) = list(self.dm.xls_time_axis.values())
        self.assertEqual(len(axis), 50)
        self.assertTrue(np.all(np.diff(axis) > 0))
        self.assertAlmostEqual(axis[0], 0.0)

    def test_midnight_time_axis(self):
        """跨零点数据的时间轴必须单调递增"""
        self.dm.load_excel_file(MIDNIGHT_PATH)
        (axis,) = list(self.dm.xls_time_axis.values())
        self.assertEqual(len(axis), 6)
        self.assertTrue(np.all(np.diff(axis) > 0), '跨零点时间轴出现回退: %s' % axis)
        self.assertAlmostEqual(axis[0], 0.0)
        self.assertAlmostEqual(axis[-1], 5.0)

    def test_empty_cell_becomes_nan(self):
        self.dm.load_excel_file(XLSX_PATH)
        data = self.dm.get_channel_data('sample.xlsx',
                                        list(self.dm.files_data['sample.xlsx'].keys())[0],
                                        '压力')
        self.assertTrue(np.isnan(data[10]))

    def test_messages_instead_of_dialogs(self):
        """Excel 加载不得直接弹窗（工作线程调用会崩），改为收集消息"""
        self.dm.load_excel_file(XLSX_PATH)
        self.assertIsInstance(getattr(self.dm, '_last_messages', None), list)
        self.assertFalse(hasattr(self.dm, '_used_message_box'))


class TestEffectiveValue(unittest.TestCase):
    def setUp(self):
        x = np.arange(0, 10, 0.1)
        self.panel = _fake_panel({'ch': {'x': x, 'y': np.sin(x)},
                                  'empty': {'x': np.array([]), 'y': np.array([])}})
        self.calc = ss.MatplotlibPlotPanel._calc_effective_value

    def test_instant_value_two_decimals(self):
        val = self.calc(self.panel, 'ch', 1.0, 0.0, decimals=2)
        self.assertEqual(val, '0.84')

    def test_default_precision(self):
        val = self.calc(self.panel, 'ch', 1.0, 0.0)
        self.assertEqual(val, '0.841471')

    def test_window_mean(self):
        val = self.calc(self.panel, 'ch', 5.0, 1.0, decimals=4)
        x = np.arange(0, 10, 0.1)
        expect = np.mean(np.sin(x)[(x >= 4.0) & (x <= 6.0)])
        self.assertEqual(val, '%.4f' % expect)

    def test_out_of_range(self):
        self.assertIsNone(self.calc(self.panel, 'ch', 100.0, 1.0))

    def test_empty_channel(self):
        self.assertIsNone(self.calc(self.panel, 'empty', 1.0, 1.0))


class TestMainWindow(unittest.TestCase):
    """每个用例使用独立窗口，避免相互污染"""

    def setUp(self):
        self.win = ss.SignalScapeMainWindow()

    def tearDown(self):
        try:
            self.win.close()
        except Exception:
            pass

    def test_window_title_has_version(self):
        self.assertIn(ss.APP_VERSION, self.win.windowTitle())

    def test_load_and_plot(self):
        win = self.win
        self.assertTrue(win.data_manager.load_tdms_file(TDMS_PATH))
        win._update_channel_tree('sample.tdms')
        item = self._find_channel(win, '温度')
        self.assertIsNotNone(item)
        win._add_channel_to_grid(item)
        self.assertGreater(win.param_panel.grid.rowCount(), 0)
        win._plot_selected_channels()
        self.assertGreater(len(win.plot_panel.current_plots), 0)

    def test_plot_empty_channel_does_not_crash(self):
        pp = self.win.plot_panel
        plots = [
            {'x_data': np.linspace(0, 10, 100), 'y_data': np.linspace(0, 1, 100), 'name': 'a'},
            {'x_data': np.array([]), 'y_data': np.array([]), 'name': 'empty'},
        ]
        params = {'a': {'color': '#1f77b4', 'linestyle': '-', 'linewidth': 0.5,
                        'legend_name': 'a', 'sample_time': 20.0},
                  'empty': {'color': '#ff7f0e', 'linestyle': '-', 'linewidth': 0.5,
                            'legend_name': 'empty', 'sample_time': 20.0}}
        pp.plot(plots, params, set(), set())
        self.assertIn('a', pp.current_plots)

    def test_per_channel_actual_value_mode(self):
        """勾选单个通道显示实际值时，其余通道仍应保持百分比归一化"""
        pp = self.win.plot_panel
        x = np.linspace(0, 10, 500)
        plots = [
            {'x_data': x, 'y_data': np.sin(x), 'name': 'a'},
            {'x_data': x, 'y_data': np.cos(x) * 100 + 500, 'name': 'b'},
        ]
        params = {n: {'color': '#1f77b4', 'linestyle': '-', 'linewidth': 0.5,
                      'legend_name': n, 'sample_time': 20.0} for n in ('a', 'b')}
        pp.plot(plots, params, {'b'}, set())
        self.assertIn('b', pp.right_axes_dict)
        ya = pp.current_plots['a'].get_ydata()
        self.assertGreaterEqual(ya.min(), -1e-9)
        self.assertLessEqual(ya.max(), 100.0 + 1e-9)

    def test_record_lines(self):
        pp = self.win.plot_panel
        pp.record_lines = [{'x': 2.0}]
        pp._update_record_lines()
        self.assertGreater(len(pp.record_artists), 0)
        pp.record_lines = []
        pp._update_record_lines()

    def test_close_releases_data(self):
        win = self.win
        win.data_manager.load_tdms_file(TDMS_PATH)
        win.close()
        self.assertEqual(len(win.data_manager.files_data), 0)

    @staticmethod
    def _find_channel(win, name):
        root = win.channel_tree.invisibleRootItem()
        for fi in range(root.childCount()):
            file_item = root.child(fi)
            for gi in range(file_item.childCount()):
                group_item = file_item.child(gi)
                for ci in range(group_item.childCount()):
                    ch = group_item.child(ci)
                    if ch.text(0) == name:
                        return ch
        return None


if __name__ == '__main__':
    unittest.main(verbosity=2)
