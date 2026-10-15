# -*- mode: python ; coding: utf-8 -*-

# ============================================================
# SignalScape (PySide2 版本) - PyInstaller 打包配置
# 打包命令: pyinstaller SignalScape_pyside.spec
# ============================================================

import os
import sys
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

# 收集 python-calamine（Excel .xls/.xlsx 读取，Rust 编译扩展，需随包携带二进制）
try:
    calamine_binaries = collect_dynamic_libs('python_calamine')
    calamine_hidden_imports = collect_submodules('python_calamine')
except Exception:
    calamine_binaries = []
    calamine_hidden_imports = ['python_calamine']

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

hidden_imports = pyside2_hidden_imports + extra_hidden_imports + calamine_hidden_imports

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

    # --- 本应用未使用的第三方库（传递依赖误入，TOC 过滤再兜底）---
    'numba', 'llvmlite', 'pandas', 'lxml', 'h5py', 'Cython', 'scipy',
    # --- 未使用的 Qt Python 模块（对应 DLL 由下方 TOC 过滤移除）---
    'PySide2.QtDesigner', 'PySide2.QtPdf', 'PySide2.QtWebEngine',
    'PySide2.QtWebView', 'PySide2.Qt3DCore', 'PySide2.Qt3DRender',
    'PySide2.Qt3DAnimation', 'PySide2.Qt3DInput', 'PySide2.Qt3DLogic',
    'PySide2.Qt3DExtras', 'PySide2.QtGamepad', 'PySide2.QtSerialBus',
    'PySide2.QtNetworkAuth', 'PySide2.QtScript', 'PySide2.QtScriptTools',
    'PySide2.QtBodymovin', 'PySide2.QtPurchasing',
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

# 合并 python-calamine 二进制（去重，Rust 扩展 .pyd 及依赖 DLL）
for name, path in calamine_binaries:
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
# 补收 conda 原生库依赖（<env>/Library/bin）
# PyInstaller 默认不收集 conda 版 Pillow/matplotlib 在 Library/bin 的原生依赖
# （jpeg/tiff/openjp2/lcms2/webp/freetype 等），冻结后 import matplotlib -> PIL
# 会报 "DLL load failed while importing _imaging"。源码/venv 运行时 Library/bin
# 在 PATH 上故不暴露，冻结后才需显式带入。此处收集这些 DLL 及其传递依赖并去重。
# ============================================================
def _collect_libbin_binaries(seed_names):
    try:
        import pefile
    except ImportError:
        pefile = None
    libbin = os.path.join(sys.prefix, 'Library', 'bin')
    picked, queue, seen = {}, list(seed_names), set()
    while queue:
        name = queue.pop(0)
        low = name.lower()
        if low in seen:
            continue
        seen.add(low)
        path = os.path.join(libbin, name)
        if not os.path.isfile(path):
            continue
        picked[name] = path
        if pefile is None:
            continue
        try:
            pe = pefile.PE(path)
            for e in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', []):
                queue.append(e.dll.decode('utf-8', 'ignore'))
        except Exception:
            pass
    if pefile is None:  # 无 pefile 时退化为固定清单（不含传递依赖）
        picked = {n: os.path.join(libbin, n) for n in seed_names
                  if os.path.isfile(os.path.join(libbin, n))}
    return [(n, p, 'BINARY') for n, p in picked.items()]


_libbin_bins = _collect_libbin_binaries([
    'freetype.dll',                                     # matplotlib.ft2font
    'jpeg8.dll', 'tiff.dll', 'openjp2.dll', 'lcms2.dll',  # PIL._imaging / _imagingcms
    'libwebp.dll', 'libwebpmux.dll', 'libwebpdemux.dll',  # PIL._webp
])
_existing_bin = {os.path.basename(n).lower() for n, _, _ in a.binaries}
for _n, _p, _t in _libbin_bins:
    if os.path.basename(_n).lower() not in _existing_bin:
        a.binaries.append((_n, _p, _t))
        _existing_bin.add(os.path.basename(_n).lower())

# ============================================================
# 产物瘦身：Analysis 后 TOC 级过滤
# （collect_dynamic_libs('PySide2') 会 indiscriminately 收齐全部 DLL；
#  excludes 只挡 Python 模块、挡不住 DLL，故在此按白名单/名称裁减）
# ============================================================
# 保留的 Qt 核心 DLL（QtWidgets + matplotlib Qt5Agg + shiboken/abi3 硬链所需：
#  pyside2.abi3.dll -> Qt5Qml.dll -> Qt5Network.dll，故 Qml/Network 必留）
_KEEP_QT_DLLS = {
    'qt5core.dll', 'qt5gui.dll', 'qt5widgets.dll', 'qt5network.dll',
    'qt5qml.dll', 'qt5opengl.dll', 'qt5svg.dll', 'qt5xml.dll',
    'qt5concurrent.dll',
}
# 运行库 / ABI（无论位于 PySide2/ 还是 _internal 根都保留）
_KEEP_RUNTIME_DLLS = {
    'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
    'msvcp140_codecvt_ids.dll', 'vcruntime140.dll', 'vcruntime140_1.dll',
    'vcamp140.dll', 'vccorlib140.dll', 'concrt140.dll', 'vcomp140.dll',
    'ucrtbase.dll', 'pyside2.abi3.dll', 'libcrypto-3-x64.dll',
    'libssl-3-x64.dll', 'libcrypto-1_1-x64.dll', 'libssl-1_1-x64.dll',
    'libffi-8.dll', 'zlib.dll', 'libzlib.dll',
}
# 整目录移除的、本应用未使用的第三方包
# 整目录移除：未使用的第三方包 + PySide2 非运行期开发产物(examples/typesystems/glue)
_DROP_PREFIXES = (
    'llvmlite/', 'numba/', 'pandas/', 'lxml/', 'h5py/', 'cython/',
    'pyside2/examples/', 'pyside2/typesystems/', 'pyside2/glue/',
)
# imageformats 只保留这三种；platforms 只保留 qwindows
_KEEP_IMAGEFORMATS = {'qgif.dll', 'qico.dll', 'qjpeg.dll'}


def _keep_entry(entry):
    name = entry[0].replace('\\', '/')
    low = name.lower()
    base = low.rsplit('/', 1)[-1]
    # WebEngine 资源及一切 qtwebengine
    if 'qtwebengine' in low:
        return False
    # 未使用的第三方包 / PySide2 开发产物目录
    for pfx in _DROP_PREFIXES:
        if low.startswith(pfx):
            return False
    parts = name.split('/')
    # PySide2 插件白名单（必须先于顶层 DLL 判断：插件也是 .dll，
    #  否则 qwindows/qjpeg/qico 会被顶层 DLL 白名单误裁 → 缺平台插件无法启动）
    if len(parts) > 2 and parts[0] == 'PySide2' and parts[1] == 'plugins':
        sub = parts[2]
        if sub == 'platforms':
            return base == 'qwindows.dll'
        if sub == 'imageformats':
            return base in _KEEP_IMAGEFORMATS
        if sub == 'styles':
            return True
        return False
    # PySide2 顶层 DLL 白名单（其余 Qt5*.dll：WebEngine/3D/Charts/Location/
    #  Multimedia/Quick/Pdf/Designer/ANGLE(opengl32sw,d3dcompiler,libGLESv2)
    #  等一律裁掉）
    if len(parts) == 2 and parts[0] == 'PySide2' and base.endswith('.dll'):
        return base in _KEEP_RUNTIME_DLLS or base in _KEEP_QT_DLLS
    return True


a.binaries = [e for e in a.binaries if _keep_entry(e)]
a.datas = [e for e in a.datas if _keep_entry(e)]
# tkinter 已整体排除；其运行时钩子 pyi_rth__tkinter 若被收集，装配期找不到
# _tcl_data 会直接 FileNotFoundError —— 从 scripts TOC 摘掉（防御性处理）
a.scripts = [e for e in a.scripts if e[0] != 'pyi_rth__tkinter']

# ============================================================
# PYZ + EXE
# ============================================================
# 控制台调试开关：设环境变量 SIGNALSCAPE_CONSOLE=1 -> 控制台 exe，
# 未处理异常/缺模块堆栈直接打到 stderr（窗口版只有弹窗，看不到栈）
_console_dbg = os.environ.get('SIGNALSCAPE_CONSOLE') == '1'
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
    console=_console_dbg,
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
    console=_console_dbg,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'E:\python\SignalScape\Dashboard.ico',
)
