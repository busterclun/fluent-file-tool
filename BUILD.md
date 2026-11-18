# 从源码运行与构建

## 环境

Windows x64，本次构建使用 Python 3.14。界面使用 CustomTkinter；独立文件名整理仅依赖标准库和界面组件。真实转换由用户配置的独立 Python 环境运行 PyFluent，已验证的外部环境为 Python 3.13。

```powershell
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
& .\.venv\Scripts\python.exe src/app.py
```

在独立 Fluent Python 环境中安装 `requirements-fluent.txt`。不要把用户配置、CFD 数据或日志提交到仓库。

## 测试

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
```

自动测试使用临时目录、小型模拟文件和隐藏窗口，不调用 Fluent、不操作鼠标、不接触真实 CFD 数据。真实转换需单独准备受支持的 Fluent 环境和样例。

## 打包

在已激活构建环境的 PowerShell 中运行 `./build.ps1`。输出位于 `dist/Fluent文件转换工具/`，需完整分发该目录。PyInstaller 将 `worker.py`、`converter.py` 和 `environment_check.py` 作为内部运行资源打包；无需在发行目录放置源码。

发行包包含 EXE、运行组件、使用说明、快速开始和第三方许可；不包含 `设置.json`。版本号为 `src/app.py` 窗口标题中的正式版本。
