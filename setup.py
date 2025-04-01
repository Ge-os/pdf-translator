#!/usr/bin/env python3
import os
import sys
import platform
import subprocess
from pathlib import Path

def check_python_version():
    if sys.version_info < (3, 10):
        print("Требуется Python 3.10 или новее")
        sys.exit(1)

def create_venv():
    venv_path = Path("venv")
    try:
        print("🐍 Создание виртуального окружения...")
        subprocess.run([sys.executable, "-m", "venv", venv_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка создания venv: {e}")
        sys.exit(1)

def get_pip_path():
    system = platform.system()
    if system == "Windows":
        return venv_path / "Scripts" / "pip.exe"
    return venv_path / "bin" / "pip"

def install_dependencies():
    pip_exec = get_pip_path()
    requirements = Path("requirements.txt")
    
    if not requirements.exists():
        print("❌ Файл requirements.txt не найден")
        sys.exit(1)

    try:
        print("📦 Установка зависимостей...")
        subprocess.run([str(pip_exec), "install", "-r", str(requirements)], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка установки зависимостей: {e}")
        sys.exit(1)

def post_install():
    system = platform.system()
    print("\n✅ Установка завершена! Для запуска:")
    
    if system == "Windows":
        print(f"  venv\\Scripts\\activate.bat")
        print("  python main.py")
    else:
        print(f"  source venv/bin/activate")
        print("  python3 main.py")

def main():
    check_python_version()
    create_venv()
    install_dependencies()
    post_install()

if __name__ == "__main__":
    venv_path = Path("venv")
    main()