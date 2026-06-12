# -*- mode: python ; coding: utf-8 -*-

# ============================================================
# SignalScape - PyInstaller 打包配置（体积优化版）
# 打包命令: pyinstaller SignalScape.spec
# ============================================================

# --- 隐藏导入 (运行时动态导入的模块) ---
hidden_imports = [
    # matplotlib WXAgg 后端相关
    'matplotlib.backends.backend_wxagg',
    'matplotlib.backends.backend_wx',
    'wx._core',

    # fnmatch 动态导入 (在 DataManager._match_pattern 中使用)
    'fnmatch',

    # nptdms 子模块
    'nptdms.tdms',
    'nptdms.types',
    'nptdms.utils',

    # pandas/numpy 可能需要的隐藏依赖
    'pandas._libs',
    'pandas._libs.tslibs',
    'numpy.core._methods',
    'numpy.lib.format',

    # numpy 延迟导入的标准库模块
    'secrets',
]

# --- 排除模块 (大幅缩减体积) ---
excludes = [
    # ===== 其他 GUI 框架 =====
    'tkinter', '_tkinter', 'Tkinter',
    'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets',
    'PySide2', 'PySide6',

    # ===== 不需要的 matplotlib 后端 =====
    'matplotlib.backends.backend_qt5',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_qt6',
    'matplotlib.backends.backend_qt6agg',
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

    # ===== scipy (未使用) =====
    'scipy', 'scipy.signal', 'scipy.optimize', 'scipy.sparse',
    'scipy.stats', 'scipy.interpolate', 'scipy.fft',

    # ===== Jupyter 生态 =====
    'IPython', 'IPython.core', 'IPython.display',
    'jupyter', 'jupyter_client', 'jupyter_core',
    'notebook', 'nbformat', 'nbconvert',
    'traitlets', 'ipykernel',

    # ===== 网络/ZMQ (Jupyter依赖) =====
    'zmq', 'pyzmq', 'tornado',

    # ===== Web 框架 =====
    'django', 'flask', 'jinja2', 'markupsafe',
    'werkzeug', 'click',

    # ===== 数据库 =====
    'sqlalchemy', 'sqlite3', '_sqlite3',

    # ===== 测试框架 =====
    'pytest', 'nose', 'coverage', 'unittest.mock',

    # ===== 开发/构建工具 =====
    'setuptools', 'distutils', 'wheel', 'pip',
    'pkg_resources.extern',

    # ===== 密码学 =====
    'Crypto', 'cryptography', 'bcrypt',

    # ===== HTML/XML解析 =====
    # 注意: html/html.parser/html.entities 必须保留 — matplotlib -> pyparsing.helpers 依赖它们
    'lxml',
    'xml', 'xml.etree', 'xml.dom',

    # ===== 网络/HTTP =====
    # 注意: email/http 模块已被 nptdms -> importlib.metadata 依赖，不能排除
    'http.server',
    'urllib3', 'certifi', 'chardet', 'idna',

    # ===== 文档工具 =====
    'sphinx', 'docutils',

    # ===== 其他 =====
    # 注意: concurrent.futures 必须保留 — pandas._testing 在导入时依赖它
    'multiprocessing',
    'curses', '_curses',
    'asyncio',
    # bz2/_bz2 已保留 — pandas.compat.compressors 依赖
    'lzma', '_lzma',
    # ssl/_ssl/socket 已保留 — numpy 的 secrets 模块依赖它们
    'ctypes.test',
    'numpy.tests',
    'pandas.tests',
    'matplotlib.tests',
]

# --- 需要保留的数据文件 ---
datas = [
    # 如果程序需要中文字体文件，可以在这里添加
    # ('C:/Windows/Fonts/msyh.ttc', 'matplotlib/mpl-data/fonts/ttf/'),
]

a = Analysis(
    ['SignalScape.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,              # 保持docstring, numpy依赖运行时docstring
)

# --- 过滤掉 MKL MPI/BLACS 相关 DLL (桌面程序不需要分布式计算) ---
a.binaries = [
    (name, path, typ) for (name, path, typ) in a.binaries
    if not any(name.startswith(prefix) for prefix in [
        'mkl_blacs_',        # BLACS = 并行矩阵计算, 依赖 impi.dll / msmpi.dll
        'mkl_scalapack_',    # ScaLAPACK = 分布式线性代数
    ])
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,      # onedir模式: 二进制文件分离到COLLECT
    name='SignalScape_onedir',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'E:\python\SignalScape\Dashboard.ico',
)

# onedir模式: 收集所有二进制和数据文件到输出目录
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='SignalScape_onedir',
)

# onefile单文件模式: 所有二进制打包进单个exe
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
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'E:\python\SignalScape\Dashboard.ico',
)
