# SignalScape - TDMS 数据可视化分析工具

基于 Python 开发的专业 TDMS 数据可视化与分析工具，支持多文件加载、通道筛选、交互式绘图、统计分析及数据导出。

## 核心功能

- **TDMS 文件加载**：支持单文件/批量加载，主备双方案容错
- **智能通道筛选**：关键字过滤（故障/保留/备用/空闲/纯零点）+ 通配符模式
- **交互式绘图**：缩放、平移、十字光标跟踪、可拖拽红蓝竖直线分析
- **统计分析**：全局统计、区域统计、5 种有效值计算方式
- **多文件对比**：跨文件通道叠加对比，文件索引自动维护
- **数据导出**：原始数据/有效值导出 CSV，绘图保存 PNG/JPG/PDF

## 技术栈

- Python 3.8+
- wxPython 4.2+
- NumPy / pandas / Matplotlib
- nptdms

## 快速开始

```bash
pip install wxpython numpy pandas matplotlib nptdms
python SignalScape_v2.py
```

## 打包

```bash
pyinstaller SignalScape_v2.spec
```
