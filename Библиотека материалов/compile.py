# -*- coding: utf-8 -*-
import sys
import os
import shutil
import subprocess
from pathlib import Path

try:
    import importlib.metadata as ilmd
except Exception:
    import importlib_metadata as ilmd  # type: ignore

PROJECT_DIR = Path(__file__).resolve().parent
MAIN_SCRIPT = PROJECT_DIR / "main.py"
EXE_NAME = "Material_Lib"
DIST_DIR = PROJECT_DIR / "dist"
BUILD_DIR = PROJECT_DIR / "build"
SPEC_FILE = PROJECT_DIR / f"{EXE_NAME}.spec"

EXTERNAL_FILES = ["app_list.txt", "instruction_list.txt", "change_list.txt"]

CUSTOM_HOOKS_DIR = PROJECT_DIR / "_pyi_custom_hooks"
RUNTIME_HOOKS_DIR = PROJECT_DIR / "_pyi_runtime_hooks"

def step(msg: str):
    print(f"[compile] {msg}")

def run(cmd):
    return subprocess.run(cmd, cwd=str(PROJECT_DIR))

def validate_structure():
    if not MAIN_SCRIPT.exists():
        step(f"Не найден {MAIN_SCRIPT.name}")
        sys.exit(1)

def ensure_packaging_compatible():
    step("Гарантирую packaging<25 ...")
    res = run([sys.executable, "-m", "pip", "install", "--upgrade", "packaging>=22,<25"])
    if res.returncode != 0:
        step("Не удалось установить packaging<25")
        sys.exit(1)

def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa
        step("PyInstaller найден.")
    except ImportError:
        step("Устанавливаю PyInstaller...")
        res = run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])
        if res.returncode != 0:
            step("Ошибка установки PyInstaller.")
            sys.exit(1)

def get_version(pkg: str) -> str | None:
    try:
        return ilmd.version(pkg)
    except Exception:
        return None

def ensure_dist(spec: str, name: str):
    ver = get_version(name)
    if ver is None:
        step(f"{name} не найден. Устанавливаю {spec} ...")
        res = run([sys.executable, "-m", "pip", "install", spec])
        if res.returncode != 0:
            step(f"Не удалось установить {spec}.")
            sys.exit(1)
    else:
        step(f"{name} установлен (версия {ver}).")

def ensure_requirements():
    ensure_dist("matplotlib>=3.7", "matplotlib")

def clean_prev_build():
    for p in [DIST_DIR, BUILD_DIR, SPEC_FILE, CUSTOM_HOOKS_DIR, RUNTIME_HOOKS_DIR]:
        try:
            if isinstance(p, Path) and p.exists():
                if p.is_dir():
                    step(f"Удаляю {p} ...")
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    step(f"Удаляю {p} ...")
                    p.unlink(missing_ok=True)
        except Exception as e:
            step(f"Предупреждение: не удалось удалить {p}: {e}")

def create_runtime_hook() -> Path:
    RUNTIME_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    hook = RUNTIME_HOOKS_DIR / "set_cwd_to_exe.py"
    hook.write_text(
        "import sys, os\n"
        "from pathlib import Path\n"
        "if getattr(sys, 'frozen', False):\n"
        "    try:\n"
        "        os.chdir(Path(sys.executable).parent)\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )
    return hook

def create_custom_hooks_for_matplotlib() -> None:
    CUSTOM_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    (CUSTOM_HOOKS_DIR / "hook-matplotlib.py").write_text(
        "from PyInstaller.utils.hooks import collect_data_files, collect_submodules\n"
        "import importlib.util\n"
        "hiddenimports = []\n"
        "datas = []\n"
        "binaries = []\n"
        "excludedimports = ['matplotlib.tests', 'matplotlib.testing']\n"
        "if importlib.util.find_spec('matplotlib') is not None:\n"
        "    try:\n"
        "        hiddenimports = collect_submodules('matplotlib')\n"
        "    except Exception:\n"
        "        hiddenimports = []\n"
        "    try:\n"
        "        datas = collect_data_files('matplotlib')\n"
        "    except Exception:\n"
        "        datas = []\n",
        encoding="utf-8",
    )
    (CUSTOM_HOOKS_DIR / "hook-mpl_toolkits.py").write_text(
        "from PyInstaller.utils.hooks import collect_submodules\n"
        "import importlib.util\n"
        "hiddenimports = []\n"
        "if importlib.util.find_spec('mpl_toolkits') is not None:\n"
        "    try:\n"
        "        hiddenimports = collect_submodules('mpl_toolkits')\n"
        "    except Exception:\n"
        "        hiddenimports = []\n",
        encoding="utf-8",
    )

def add_data_args(files: list[str]) -> list[str]:
    sep = ";" if os.name == "nt" else ":"
    args = []
    for name in files:
        src = (PROJECT_DIR / name)
        if src.exists():
            args += ["--add-data", f"{str(src.resolve())}{sep}."]  # кладём в корень бандла
        else:
            step(f"Предупреждение: {name} не найден — пропускаю --add-data")
    return args

def build_exe():
    import PyInstaller.__main__

    runtime_hook = create_runtime_hook()
    create_custom_hooks_for_matplotlib()

    args = [
        "--noconfirm",
        "--clean",
        "--onefile",
        "--noconsole",
        "--name", EXE_NAME,
        "--log-level", "WARN",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--exclude-module", "matplotlib.tests",
        "--exclude-module", "matplotlib.testing",
        "--additional-hooks-dir", str(CUSTOM_HOOKS_DIR),
        "--collect-all", "matplotlib",
        "--runtime-hook", str(runtime_hook),
    ]

    # ВКЛАДЫВАЕМ текстовые файлы ВНУТРЬ exe
    args += add_data_args(EXTERNAL_FILES)

    # Главный скрипт в конце
    args.append(str(MAIN_SCRIPT))

    step("Запускаю PyInstaller...")
    PyInstaller.__main__.run(args)

    exe_path = DIST_DIR / f"{EXE_NAME}.exe"
    if not exe_path.exists():
        step("Сборка завершилась, но .exe не найден. Проверьте логи.")
        sys.exit(1)
    step(f"Собрано: {exe_path}")
    return exe_path

def copy_external_files():
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    for name in EXTERNAL_FILES:
        src = PROJECT_DIR / name
        if src.exists():
            dst = DIST_DIR / name
            try:
                shutil.copy2(src, dst)
                step(f"Скопирован файл рядом с exe: {dst.name}")
            except Exception as e:
                step(f"Не удалось скопировать {name}: {e}")
        else:
            step(f"Файл {name} не найден — пропускаю.")

def main():
    step(f"Папка проекта: {PROJECT_DIR}")
    validate_structure()
    ensure_packaging_compatible()
    ensure_pyinstaller()
    ensure_requirements()
    clean_prev_build()
    _ = build_exe()
    copy_external_files()

    try:
        if os.name == "nt":
            os.startfile(str(DIST_DIR))
    except Exception:
        pass

    step("Готово. Положите рядом с .exe папки «БД Материалов» и «Источники», если нужны.")

if __name__ == "__main__":
    main()