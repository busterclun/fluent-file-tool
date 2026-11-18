"""Check the selected interpreter's Fluent support without starting a solver."""
import argparse
import re
import sys
import json
from pathlib import Path


def check_environment(version, fluent_root=''):
    if not re.fullmatch(r'\d{2}\.[12]\.0', version):
        raise ValueError('版本号格式示例：2024 R1 填 24.1.0，2024 R2 填 24.2.0。')
    if fluent_root:
        root = Path(fluent_root)
        if not (root / 'fluent/ntbin/win64/fluent.exe').is_file():
            raise ValueError('Fluent 安装位置应选择包含 fluent 文件夹的版本根目录，例如 v241。')
        expected = 'v' + version.replace('.', '')[:-1]
        if re.fullmatch(r'v\d{3}', root.name.lower()) and root.name.lower() != expected:
            raise ValueError(f'安装目录 {root.name} 与版本号 {version} 不一致，应为 {expected}。')
    import numpy
    import ansys.fluent.core as pyfluent
    from ansys.fluent.core.utils.fluent_version import FluentVersion
    print(f'Python {sys.version.split()[0]} | PyFluent {pyfluent.__version__} | NumPy {numpy.__version__}', flush=True)
    try:
        FluentVersion(version)
    except (ValueError, RuntimeError) as exc:
        supported = ', '.join(item.value for item in FluentVersion)
        advice = ('Fluent 2024 R1 可使用已验证的 Python 3.13 + PyFluent 0.37.2 独立环境。'
                  if version == '24.1.0' else '请选择支持该 Fluent 版本的 PyFluent 独立环境。')
        raise ValueError(f'当前 Python 中的 PyFluent {pyfluent.__version__} 不支持 Fluent {version}。\n'
                         f'该 PyFluent 支持：{supported}。\n{advice}\n'
                         '在“运行环境”切换 Python 解释器后重新检查；不要把版本号改成未安装的 Fluent 版本。') from exc
    print(f'Fluent {version} 的路径、依赖与 PyFluent 版本兼容性检查通过。'
          '许可证及实际启动能力需在启动 Fluent 时验证。', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version')
    parser.add_argument('--fluent-root', default='')
    parser.add_argument('--describe-json', action='store_true')
    args = parser.parse_args()
    try:
        if args.describe_json:
            import numpy
            import ansys.fluent.core as pyfluent
            from ansys.fluent.core.utils.fluent_version import FluentVersion
            print(json.dumps(dict(python=sys.version.split()[0], pyfluent=pyfluent.__version__,
                                  numpy=numpy.__version__, supported=[v.value for v in FluentVersion])))
        else:
            check_environment(args.version or '', args.fluent_root)
    except Exception as exc:
        print('环境检查失败：' + str(exc), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
