import os
import shutil
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import undetected_chromedriver as uc
import fitz  # PyMuPDF
from PIL import Image


def convert_pdf_to_images(pdf_path, output_dir, dpi=300):
    """Конвертирует PDF в отдельные изображения"""
    doc = fitz.open(pdf_path)
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=dpi)
        image_path = os.path.join(output_dir, f"{page_num + 1}.png")
        pix.save(image_path)
    doc.close()
    return page_num


def wait_for_download_complete(download_dir, timeout=30):
    """Ожидает завершения скачивания файла"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        files = os.listdir(download_dir)
        if files and not any(f.endswith(".crdownload") for f in files):
            return max(
                [os.path.join(download_dir, f) for f in files],
                key=os.path.getctime,
            )
        time.sleep(1)
    return None


def create_pdf_from_images(image_dir, output_pdf):
    """Создает PDF из изображений"""
    images = []
    for file in sorted(
        os.listdir(image_dir),
        key=lambda x: int(x.split(".")[0]),
    ):
        if file.lower().endswith((".png", ".jpg", ".jpeg")):
            path = os.path.join(image_dir, file)
            images.append(Image.open(path).convert("RGB"))
    
    if not images:
        raise ValueError("No images found in directory")

    images[0].save(
        output_pdf,
        "PDF",
        resolution=100.0,
        save_all=True,
        append_images=images[1:],
    )


def main():
    # Шаг 1: Проверка наличия original.pdf
    if not os.path.exists("original.pdf"):
        raise FileNotFoundError("Файл original.pdf не найден")

    # Шаг 2: Подготовка директорий
    image_dir = "pdf_images"
    download_dir = "translated_images"
    
    for dir_path in [image_dir, download_dir]:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
        os.makedirs(dir_path)

    # Шаг 3: Конвертация PDF в изображения
    total_pages = convert_pdf_to_images("original.pdf", image_dir)

    # Шаг 4: Настройка ChromeDriver
    chrome_options = uc.ChromeOptions()
    prefs = {
        "download.default_directory": os.path.abspath(download_dir),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    chrome_options.add_experimental_option("prefs", prefs)

    driver = uc.Chrome(options=chrome_options)
    
    try:
        # Шаг 5: Открытие страницы
        driver.get("https://translate.yandex.ru/ocr")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#ocrContainer"))
        )

        # Шаг 6: Обработка каждой страницы
        for page_num in range(1, total_pages + 1):
            image_path = os.path.abspath(os.path.join(image_dir, f"{page_num}.png"))

            # Загрузка файла
            drop_area = driver.find_element(By.CSS_SELECTOR, "#ocrContainer > div > div > div")
            drop_area.click()
            
            file_input = driver.find_element(By.XPATH, "//input[@type='file']")
            file_input.send_keys(image_path)

            # Ожидание обработки
            WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'button[data-action="download"]')
                )
            )

            # Скачивание
            download_btn = driver.find_element(By.CSS_SELECTOR, 'button[data-action="download"]')
            download_btn.click()

            # Ожидание скачивания
            downloaded_file = wait_for_download_complete(download_dir)
            if not downloaded_file:
                print(f"Ошибка загрузки для страницы {page_num}")
                continue

            # Переименование
            new_name = os.path.join(download_dir, f"{page_num}.png")
            if os.path.exists(new_name):
                os.remove(new_name)
            os.rename(downloaded_file, new_name)
            print(f"Обработана страница {page_num}/{total_pages}")

    finally:
        driver.quit()

    # Шаг 7: Сборка PDF
    create_pdf_from_images(download_dir, "translated.pdf")
    print("PDF успешно создан!")


if __name__ == "__main__":
    main()