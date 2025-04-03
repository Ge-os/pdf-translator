import os
import shutil
import time
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
from selenium.common.exceptions import (
    WebDriverException,
    ElementNotInteractableException,
    ElementClickInterceptedException,
    TimeoutException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import undetected_chromedriver as uc
import fitz
from PIL import Image


def handle_selenium_errors(func):
    def wrapper(*args, **kwargs):
        self = args[0]
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (ElementNotInteractableException, ElementClickInterceptedException) as e:
                self.log(f"Ошибка взаимодействия: {str(e)}")
                time.sleep(0.3)
                if attempt == max_retries - 1:
                    raise
            except TimeoutException as e:
                self.log(f"Таймаут операции: {str(e)}")
                time.sleep(0.3)
                if attempt == max_retries - 1:
                    raise
            except WebDriverException as e:
                self.log(f"Ошибка WebDriver: {str(e)}")
                time.sleep(0.3)
                if attempt == max_retries - 1:
                    raise
    return wrapper


class PDFTranslatorApp:
    def __init__(self, gui_queue, headless=False):
        self.gui_queue = gui_queue
        self.headless = headless
        self.driver = None
        self.stop_flag = False

    def log(self, message):
        self.gui_queue.put(("log", message))

    def update_progress(self, value):
        self.gui_queue.put(("progress", value))

    def convert_pdf_to_images(self, pdf_path, output_dir, dpi=300):
        doc = fitz.open(pdf_path)
        total = len(doc)
        max_size = 5 * 1024 * 1024  # 5 MB in bytes

        for page_num in range(total):
            if self.stop_flag:
                break
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=dpi)
            image_path = os.path.join(output_dir, f"{page_num + 1}.png")
            pix.save(image_path)

            with Image.open(image_path) as img:
                quality = img.info.get("quality", 90)

            while os.path.getsize(image_path) > max_size:
                self.log(f"Страница {page_num+1} слишком большая: сжимаем (качество: {quality})...")
                
                quality -= 5
                if quality < 5:
                    self.log("Достигнуто минимальное качество. Прерывание сжатия.")
                    break
                
                with Image.open(image_path) as img:
                    img.save(image_path, optimize=True, quality=quality)
            
                current_size = os.path.getsize(image_path)
                if current_size <= max_size:
                    self.log(f"Сжатие успешно.")
                    break

            self.update_progress((page_num + 1) * 30 / total)
        doc.close()
        return total

    def create_pdf_from_images(self, image_dir, output_pdf):
        images = []
        files = sorted(
            [f for f in os.listdir(image_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))],
            key=lambda x: int(x.split(".")[0]),
        )
        
        for idx, file in enumerate(files):
            if self.stop_flag:
                break
            path = os.path.join(image_dir, file)
            images.append(Image.open(path).convert("RGB"))
            self.update_progress(30 + (idx + 1) * 40 / len(files))
        
        if images:
            images[0].save(
                output_pdf,
                "PDF",
                resolution=100.0,
                save_all=True,
                append_images=images[1:],
            )

    @handle_selenium_errors
    def process_page(self, image_path, download_dir, page_num):
        original_image = image_path
        max_attempts = 2
        processed = False
        
        for attempt in range(max_attempts):
            try:
                # Попытка обработки страницы
                drop_area = WebDriverWait(self.driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#ocrContainer > div > div > div")))
                drop_area.click()
                
                file_input = self.driver.find_element(By.XPATH, "//input[@type='file']")
                file_input.send_keys(image_path)
                time.sleep(0.3)
                
                # Проверка на ошибку распознавания (только при второй попытке)
                if attempt >= 1:
                    error_elements = self.driver.find_elements(
                        By.CSS_SELECTOR, ".errorMessage_no_text")
                    if error_elements:
                        self.log(f"Страница {page_num}: Текст не распознан, используется оригинал")
                        shutil.copy(original_image, 
                                   os.path.join(download_dir, f"{page_num}.png"))
                        return

                WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-action="download"]')))
                
                download_btn = self.driver.find_element(
                    By.CSS_SELECTOR, 'button[data-action="download"]')
                download_btn.click()
                
                downloaded_file = self.wait_for_download_complete(download_dir)
                if downloaded_file:
                    new_name = os.path.join(download_dir, f"{page_num}.png")
                    os.replace(downloaded_file, new_name)
                    processed = True
                    break

            except (TimeoutException, ElementNotInteractableException) as e:
                if attempt == max_attempts - 1:
                    self.log(f"Страница {page_num}: Не удалось обработать, используется оригинал")
                    shutil.copy(original_image, 
                               os.path.join(download_dir, f"{page_num}.png"))
                else:
                    self.driver.refresh()
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#ocrContainer")))
        
        if not processed:
            self.log(f"Страница {page_num}: Использован оригинал после {max_attempts} попыток")
            shutil.copy(original_image, 
                       os.path.join(download_dir, f"{page_num}.png"))

    def wait_for_download_complete(self, download_dir, timeout=30):
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.stop_flag:
                return None
            files = os.listdir(download_dir)
            if files and not any(f.endswith(".crdownload") for f in files):
                return max(
                    [os.path.join(download_dir, f) for f in files],
                    key=os.path.getctime,
                )
            time.sleep(0.5)
        return None

    def run(self, pdf_path, output_dir):
        temp_dirs = {
            "images": "temp_images",
            "downloads": "temp_downloads",
        }
        success = False
        try:
            # Инициализация драйвера
            chrome_options = uc.ChromeOptions()
            prefs = {
                "download.default_directory": os.path.abspath("temp_downloads"),
                "download.prompt_for_download": False,
                "safebrowsing.enabled": True,
            }
            chrome_options.add_experimental_option("prefs", prefs)
            if self.headless:
                chrome_options.add_argument("--headless=new")

            self.driver = uc.Chrome(options=chrome_options)
            self.driver.get("https://translate.yandex.ru/ocr")

            for dir_path in temp_dirs.values():
                os.makedirs(dir_path, exist_ok=True)

            # Основной процесс
            total_pages = self.convert_pdf_to_images(pdf_path, temp_dirs["images"])
            processed_pages = 0
            self.update_progress(30)

            for page_num in range(1, total_pages + 1):
                if self.stop_flag:
                    break
                try:
                    image_path = os.path.abspath(os.path.join(temp_dirs["images"], f"{page_num}.png"))
                    self.process_page(image_path, temp_dirs["downloads"], page_num)
                    processed_pages += 1
                except Exception as e:
                    self.log(f"Ошибка при обработке страницы {page_num}: {str(e)}")
                self.update_progress(30 + (page_num * 40 / total_pages))
                self.log(f"Обработано страниц: {page_num}/{total_pages}")

            # Сборка PDF
            output_path = os.path.join(output_dir, "translated.pdf")
            self.create_pdf_from_images(temp_dirs["downloads"], output_path)
            success = True
            self.update_progress(100)

        except Exception as e:
            self.log(f"Критическая ошибка {str(e)}")
            self.log("Попытка сохранить частично обработанные страницы...")
            
            # Сборка частичного PDF
            if os.path.exists(temp_dirs["downloads"]):
                output_path = os.path.join(output_dir, "partial_translated.pdf")
                output_path = os.path.abspath(output_path)
                try:
                    self.create_pdf_from_images(temp_dirs["downloads"], output_path)
                    self.log(f"Сохранен частичный результат в: {output_path}")
                    self.log(f"Успешно обработано страниц: {processed_pages}")
                except Exception as pdf_error:
                    self.log(f"Ошибка при сохранении частичного PDF: {str(pdf_error)}")
        finally:
            # Очистка ресурсов
            if self.driver:
                try:
                    self.driver.quit()
                except Exception as e:
                    pass
            # Удаление временных файлов
            for dir_path in temp_dirs.values():
                if os.path.exists(dir_path):
                    shutil.rmtree(dir_path)
            if success:
                self.log("Процесс завершен успешно, окно можно закрывать")
                self.log(f"Создан PDF: {output_path}")
                self.gui_queue.put(("close", None))
            else:
                self.update_progress(0)
                self.gui_queue.put(("error", "Произошла ошибка. Частичный результат сохранен."))

class AppGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Translator")
        self.geometry("800x600")
        self.queue = queue.Queue()
        self.translator = None
        self.create_widgets()
        self.check_queue()

    def create_widgets(self):
        # Кнопки выбора файлов
        self.btn_choose_pdf = ttk.Button(self, text="Выбрать PDF файл", command=self.choose_pdf)
        self.btn_choose_pdf.pack(pady=5)

        self.btn_choose_dir = ttk.Button(self, text="Выбрать папку сохранения перевода", command=self.choose_dir)
        self.btn_choose_dir.pack(pady=5)

        # Прогресс бар
        self.progress = ttk.Progressbar(self, orient="horizontal", length=400, mode="determinate")
        self.progress.pack(pady=10)

        # Логи
        self.log_area = scrolledtext.ScrolledText(self, wrap=tk.WORD)
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Кнопка запуска
        self.btn_start = ttk.Button(self, text="Старт", command=self.start_process)
        self.btn_start.pack(pady=10)

        # Переменные
        self.pdf_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.headless_mode = tk.BooleanVar()

        # Чекбокс для фонового режима
        self.chk_headless = ttk.Checkbutton(
            self,
            text="Фоновый режим",
            variable=self.headless_mode,
        )
        self.chk_headless.pack(pady=5)

    def choose_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.pdf_path.set(path)
            self.log(f"Выбран файл: {path}")

    def choose_dir(self):
        path = filedialog.askdirectory()
        if path:
            self.output_dir.set(path)
            self.log(f"Выбрана папка: {path}")

    def log(self, message):
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)

    def start_process(self):
        if not self.pdf_path.get() or not self.output_dir.get():
            self.log("Ошибка: Выберите файл и папку для сохранения!")
            return

        self.btn_start["state"] = "disabled"
        self.translator = PDFTranslatorApp(
            gui_queue=self.queue,
            headless=self.headless_mode.get(),
        )

        threading.Thread(
            target=self.translator.run,
            args=(self.pdf_path.get(), self.output_dir.get()),
            daemon=True,
        ).start()

    def check_queue(self):
        while not self.queue.empty():
            try:
                msg_type, value = self.queue.get_nowait()
                if msg_type == "log":
                    self.log(value)
                elif msg_type == "progress":
                    self.progress["value"] = value
            except queue.Empty:
                pass
        self.after(100, self.check_queue)

    def on_closing(self):
        if self.translator:
            self.translator.stop_flag = True
        self.destroy()


if __name__ == "__main__":
    app = AppGUI()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()