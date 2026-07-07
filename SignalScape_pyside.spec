# -*- mode: python ; coding: utf-8 -*-

# ============================================================
# SignalScape (PySide2 版本) - PyInstaller 打包配置
# 打包命令: pyinstaller SignalScape_pyside.spec
# ============================================================

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

# ============================================================
# PySide2 自动收集（解决 DLL 找不到问题）
# ============================================================

# 收集所有 PySide2 子模块（覆盖运行时动态导入的所有模块）
pyside2_hidden_imports = collect_submodules('PySide2')

# 收集 PySide2 数据文件，最关键的是 platforms/qwindows.dll（Qt 平台插件）
# 缺少它会在非开发机上直接崩溃报 "找不到 Qt platform plugin"
pyside2_datas = collect_data_files('PySide2')
# 过滤不需要的 PySide2 插件和翻译文件（减小体积约 10-20 MB）
pyside2_datas = [
    (src, dst) for (src, dst) in pyside2_datas
    if not any(skip in dst.lower() for skip in [
        'sqldrivers', 'printsupport', 'bearers', 'position',
        'sensors', 'gamepads', 'translations', 'qml',
        'scenegraph', 'virtualkeyboard', 'texttospeech',
        'canbus', 'webview', 'playlistformats', 'mediaservice',
        'audio', 'video', 'geometryloaders',
    ])
]

# 收集 PySide2 动态库
pyside2_binaries = collect_dynamic_libs('PySide2')

# ============================================================
# 额外隐藏导入
# ============================================================
extra_hidden_imports = [
    # --- matplotlib Qt 后端 ---
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_qt',
    'matplotlib.backends.qt_compat',
    'matplotlib.backends.qt_editor.figureoptions',

    # --- 标准库（动态导入）---
    're',
    'fnmatch',

    # --- nptdms ---
    'nptdms.tdms',
    'nptdms.types',
    'nptdms.utils',

    # --- numpy ---
    'numpy.core._methods',
    'numpy.core._multiarray_tests',
    'numpy.core._multiarray_umath',
    'numpy.lib.format',
    'secrets',

    # --- PySide2 隐性依赖（QtWidgets 运行时可能动态加载）---
    'PySide2.QtOpenGL',
]

hidden_imports = pyside2_hidden_imports + extra_hidden_imports

# ============================================================
# 排除不需要的模块（减小体积）
# ============================================================
excludes = [
    # --- 其他 GUI 框架 ---
    'tkinter', '_tkinter', 'Tkinter',
    'wx', 'wx._core', 'wx._gdi', 'wx._misc', 'wx._html', 'wx._adv',
    'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
    'PySide6',

    # --- QtWebEngine（嵌入式浏览器，本应用不需要，且 conda 环境可能文件缺失）---
    'PySide2.QtWebEngineCore',
    'PySide2.QtWebEngineWidgets',
    'PySide2.QtWebEngineQuick',
    'PySide2.QtWebChannel',
    'PySide2.QtWebSockets',
    'PySide2.QtQml',
    'PySide2.QtQuick',
    'PySide2.QtQuickWidgets',
    'PySide2.QtQuick3D',
    'PySide2.Qt3DCore',
    'PySide2.QtCharts',
    'PySide2.QtDataVisualization',
    'PySide2.QtLocation',
    'PySide2.QtMultimedia',
    'PySide2.QtPositioning',
    'PySide2.QtSensor',
    'PySide2.QtSerialPort',
    'PySide2.QtSql',

    # --- 更多不需要的 PySide2 模块 ---
    'PySide2.QtTest',
    'PySide2.QtConcurrent',
    'PySide2.QtHelp',
    'PySide2.QtPrintSupport',
    'PySide2.QtXmlPatterns',
    'PySide2.QtUiTools',
    'PySide2.QtBluetooth',
    'PySide2.QtNfc',
    'PySide2.QtRemoteObjects',
    'PySide2.QtScxml',
    'PySide2.QtTextToSpeech',
    'PySide2.QtVirtualKeyboard',

    # --- 不需要的 matplotlib 后端 ---
    'matplotlib.backends.backend_wxagg',
    'matplotlib.backends.backend_wx',
    'matplotlib.backends.backend_tkagg',
    'matplotlib.backends.backend_tkcairo',
    'matplotlib.backends.backend_gtk3agg',
    'matplotlib.backends.backend_gtk3cairo',
    'matplotlib.backends.backend_gtk4agg',
    'matplotlib.backends.backend_gtk4cairo',
    'matplotlib.backends.backend_macosx',
    'matplotlib.backends.backend_webagg',
    'matplotlib.backends.backend_webagg_core',
    'matplotlib.backends.backend_nbagg',
    'matplotlib.backends.backend_cairo',
    'matplotlib.backends.backend_pgf',
    'matplotlib.backends.backend_ps',
    'matplotlib.backends.backend_template',

    # --- scipy（未使用）---
    'scipy', 'scipy.signal', 'scipy.optimize', 'scipy.sparse',
    'scipy.stats', 'scipy.interpolate', 'scipy.fft',

    # --- Jupyter ---
    'IPython', 'IPython.core', 'IPython.display',
    'jupyter', 'jupyter_client', 'jupyter_core',
    'notebook', 'nbformat', 'nbconvert',
    'traitlets', 'ipykernel',

    # --- ZMQ ---
    'zmq', 'pyzmq', 'tornado',

    # --- Web ---
    'django', 'flask', 'jinja2', 'markupsafe',
    'werkzeug', 'click',

    # --- 数据库 ---
    'sqlalchemy', 'sqlite3', '_sqlite3',

    # --- 测试 ---
    'pytest', 'nose', 'coverage', 'unittest.mock',

    # --- 构建工具 ---
    'setuptools', 'distutils', 'wheel', 'pip',
    'pkg_resources.extern',

    # --- 密码学 ---
    'Crypto', 'cryptography', 'bcrypt',

    # --- XML（PySide2 部分模块初始化时需要 xml，仅排除不需要的子模块）---
    'xml.dom',

    # --- 网络 ---
    'http.server',
    'urllib3', 'certifi', 'chardet', 'idna',

    # --- 文档 ---
    'sphinx', 'docutils',

    # --- 其他 ---
    'multiprocessing',
    'curses', '_curses',
    'asyncio',
    'lzma', '_lzma',
    'ctypes.test',
    'numpy.tests',
    'numpy.distutils', 'numpy.f2py', 'numpy.testing',
    'pandas.tests',
    'pandas.io.html', 'pandas.io.excel', 'pandas.io.sql',
    'pandas.io.parquet', 'pandas.io.feather', 'pandas.io.orc',
    'pandas.io.stata', 'pandas.io.spss',
    'matplotlib.tests',
    'pydoc', 'doctest',
]

# ============================================================
# Analysis
# ============================================================
a = Analysis(
    ['SignalScape_pyside.py'],
    pathex=[],
    binaries=[],
    datas=pyside2_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# ============================================================
# 过滤 DLL 和数据文件
# ============================================================

# 移除 matplotlib 不需要的字体文件（只保留 DejaVuSans 和 DejaVuSans-Bold）
# Computer Modern 和 STIX 字体约占 5 MB，DejaVuSerif/Mono 约占 5 MB
a.datas = [
    (dest, src, kind) for (dest, src, kind) in a.datas
    if not ('mpl-data/fonts' in dest.lower() and
            any(f.lower() in dest.lower() for f in [
                'cmb10', 'cmex10', 'cmmi10', 'cmr10', 'cmss10', 'cmsy10', 'cmtt10',
                'stix', 'dejavuserif', 'dejavusansdisplay',
                'dejavusansmono-bold', 'dejavusansmono-oblique',
                'dejavusansmono-boldoblique', 'dejavusansmono.ttf',
            ]))
]

# 将软件图标随包收集，供运行时 QIcon 加载（解决标题栏/任务栏图标问题）
a.datas.append(('Dashboard.ico', r'E:\python\SignalScape\Dashboard.ico', 'DATA'))

# 去重 PySide2 二进制文件（避免与自动收集的 DLL 重复）
# 注意：只比较文件名（不含路径），因为内置 hook 的 name 是 'Qt5Widgets.dll'
# 而 collect_dynamic_libs 返回的 name 是 'PySide2/Qt5Widgets.dll'，直接比较会误判
existing_basenames = {os.path.basename(name).lower() for name, _, _ in a.binaries}
for name, path in pyside2_binaries:
    basename = os.path.basename(name).lower()
    if basename not in existing_basenames:
        a.binaries.append((name, path, 'BINARY'))
        existing_basenames.add(basename)

# 移除 MKL MPI/BLACS DLL（桌面程序不需要分布式计算）
a.binaries = [
    (name, path, typ) for (name, path, typ) in a.binaries
    if not any(name.startswith(prefix) for prefix in [
        'mkl_blacs_',
        'mkl_scalapack_',
    ])
]

# ============================================================
# PYZ + EXE
# ============================================================
pyz = PYZ(a.pure)

# onedir 目录版
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='SignalScape_onedir',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=['python38.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'E:\python\SignalScape\Dashboard.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='SignalScape_onedir',
)

# onefile 单文件版
exe_onefile = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SignalScape',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'E:\python\SignalScape\Dashboard.ico',
)
