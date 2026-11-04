import os
import subprocess
import sys
import shutil


def compile_to_exe():
    # Определяем базовую директорию
    base_dir = "C:/1"
    script_name = "1.py"  # Замените на имя вашего скрипта
    script_path = os.path.join(base_dir, script_name)
    exe_name = os.path.splitext(script_name)[0] + ".exe"

    if not os.path.exists(script_path):
        print(f"Ошибка: Файл {script_path} не найден!")
        return

    # Проверка и установка PyInstaller
    try:
        print("Проверка установки PyInstaller...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        print("Ошибка установки PyInstaller")
        return

    # Установка необходимых зависимостей
    dependencies = ["PyPDF2", "openpyxl"]
    print("Установка зависимостей...")
    for dep in dependencies:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", dep],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print(f"  {dep} установлен")
        except subprocess.CalledProcessError:
            print(f"  Ошибка установки {dep}")

    # Создание временной папки
    temp_dir = os.path.join(base_dir, "build_temp")
    os.makedirs(temp_dir, exist_ok=True)

    # Команда для компиляции
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--distpath", base_dir,
        "--workpath", temp_dir,
        "--specpath", temp_dir,
        "--clean",
        "--name", os.path.splitext(script_name)[0],
        script_path
    ]

    # Запуск компиляции
    print(f"\nКомпиляция {script_name} в {exe_name}...")
    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )

        # Путь к скомпилированному EXE
        exe_path = os.path.join(base_dir, exe_name)
        print("\nУспешно! EXE-файл создан:")
        print(exe_path)

        # Создаем папку для конечного результата
        result_dir = os.path.join(base_dir, "PDF_Bookmark_Extractor")
        os.makedirs(result_dir, exist_ok=True)

        # Копируем EXE в целевую папку
        shutil.copy2(exe_path, result_dir)

        # Создаем пустые управляющие файлы в целевой папке
        required_files = ["tags.txt", "equipment.txt", "file_path.txt"]
        for file in required_files:
            file_path = os.path.join(result_dir, file)
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    if file == "tags.txt":
                        f.write("# Список тегов для поиска (по одному на строку)\n")
                        f.write("# Пример:\n# Договор\n# Акт\n# Спецификация\n")
                    elif file == "equipment.txt":
                        f.write("# Шаблоны для поиска оборудования (регулярные выражения)\n")
                        f.write("# Пример:\n# [А-Я]{2,}-\\d{3,}\n# [A-Z]{3,}-\\d{4,}(-\\d+)*\n")
                    elif file == "file_path.txt":
                        f.write("# Пути к папкам с PDF-файлами (по одному на строку)\n")
                        f.write("# Пример:\n# C:\\Documents\\PDFs\\Project1\n# D:\\Technical\\Project2\\Docs\n")

        print("\nГотово! Все файлы находятся в папке:")
        print(result_dir)
        print("\nИнструкция:")
        print("1. Поместите EXE-файл и управляющие файлы в папку с PDF-документами")
        print("2. Заполните управляющие файлы:")
        print("   - tags.txt: список тегов для поиска")
        print("   - equipment.txt: шаблоны для поиска оборудования")
        print("   - file_path.txt: пути к папкам с PDF (если нужно обрабатывать несколько папок)")
        print("3. Запустите EXE-файл")
        print("4. Результаты будут сохранены в файле PDF_Bookmarks.xlsx")

    except subprocess.CalledProcessError as e:
        print(f"\nОшибка компиляции (код {e.returncode}):")
        print("Сообщение:", e.stderr)
        print("Вывод:", e.stdout)
    except Exception as e:
        print(f"Неожиданная ошибка: {str(e)}")
    finally:
        # Удаление временных файлов
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

        # Удаление файла .spec
        spec_file = os.path.join(base_dir, os.path.splitext(script_name)[0] + ".spec")
        if os.path.exists(spec_file):
            os.remove(spec_file)

        # Удаление папки build
        build_dir = os.path.join(base_dir, "build")
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 50)
    print("Компилятор скрипта в EXE-файл")
    print("=" * 50)
    compile_to_exe()
    input("\nНажмите Enter для выхода...")