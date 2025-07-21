import tkinter as tk
import threading
import pdfplumber
import time
import re
import sys
import io

from datetime import datetime
from collections import defaultdict
from funcoes_map import FUNCOES_DICT
from tkinter import filedialog, scrolledtext, messagebox, ttk
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.support import expected_conditions as EC


# --- TextRedirector ---
class TextRedirector(io.StringIO):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget

    def write(self, s):
        self.widget.after_idle(self._write_to_widget, s)

    def _write_to_widget(self, s):
        self.widget.config(state=tk.NORMAL)
        self.widget.insert(tk.END, s)
        self.widget.see(tk.END)
        self.widget.config(state=tk.DISABLED)

    def flush(self):
        pass

# --- PDF Parsing Logic ---
def extract_year_from_date_string(date_str):
    if not date_str: return None
    match = re.search(r'\d{2}/\d{2}/(\d{4})', date_str)
    if match: return match.group(1)
    return None

def is_start_of_new_report(page_text):
    if not page_text: return None
    page_marker_match = re.search(r"Página\s*1(?:$|\s*de\s*\d+)", page_text, re.IGNORECASE | re.MULTILINE)
    if not page_marker_match:
        return None
    page_text_lines = page_text.split('\n')
    data_consulta_date_str = None
    for i, line in enumerate(page_text_lines):
        if "Data Consulta" in line and "CPF" in line and "Nome" in line and "Vínculo" in line:
            if i + 1 < len(page_text_lines):
                value_line = page_text_lines[i + 1]
                date_match_in_line = re.search(r"(\d{2}/\d{2}/\d{4})", value_line)
                if date_match_in_line:
                    data_consulta_date_str = date_match_in_line.group(1)
                    return data_consulta_date_str
    match_dc_fallback = re.search(r"Data Consulta\s*[\n\r]?\s*(\d{2}/\d{2}/\d{4})", page_text)
    if match_dc_fallback:
        data_consulta_date_str = match_dc_fallback.group(1)
        return data_consulta_date_str
    return None

def extract_funcao_codes_from_page(page):
    codes = set()
    tables = page.extract_tables()
    if tables:
        for table_num, table_data in enumerate(tables):
            if not table_data: continue
            header = table_data[0]
            funcao_col_index = -1
            if len(header) > 1 and header[1] and isinstance(header[1], str) and "Função" in header[1]:
                funcao_col_index = 1
            elif any(isinstance(cell, str) and "Função" in cell for cell in header if cell):
                try:
                    funcao_col_index = next(idx for idx, cell in enumerate(header) if cell and isinstance(cell, str) and "Função" in cell)
                except StopIteration: pass
            if funcao_col_index != -1:
                for row_idx, row in enumerate(table_data):
                    if row_idx == 0: continue
                    if len(row) > funcao_col_index and row[funcao_col_index]:
                        cell_content = str(row[funcao_col_index]).strip()
                        potential_code = ""
                        match = re.match(r"^\s*(\d{3})\s*-", cell_content)
                        if match:
                            potential_code = match.group(1)
                        else:
                            first_line = cell_content.split('\n')[0].strip()
                            if re.fullmatch(r"\d{3}\s*", first_line):
                                potential_code = first_line.strip()
                            elif re.fullmatch(r"\d{3}", first_line):
                                potential_code = first_line
                        if potential_code.isdigit() and len(potential_code) == 3:
                            codes.add(potential_code)
    return codes

def aggregate_yearly_data_multi_report(pdf_path, log_area, progress_callback=None):
    """
    Processes the entire PDF, handling multi-page reports and associating the full
    'Data Consulta' with each function code found.
    Returns data in the format {year: {set of (date_obj, code, '[MDL]')}}.
    """
    yearly_funcoes = defaultdict(set)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                log_area.write("Error: PDF has no pages.\n")
                return {}
            
            total_pages = len(pdf.pages)
            current_report_date_obj = None
            current_report_funcao_codes = set()

            for i, page in enumerate(pdf.pages):
                if progress_callback:
                    log_area.widget.master.after_idle(progress_callback, (i + 1) / total_pages * 100)
                
                page_num = i + 1
                page_text = page.extract_text()
                
                new_report_data_consulta_str = is_start_of_new_report(page_text)

                if new_report_data_consulta_str:
                    if current_report_date_obj and current_report_funcao_codes:
                        year_str = str(current_report_date_obj.year)
                        for code in current_report_funcao_codes:
                            yearly_funcoes[year_str].add((current_report_date_obj, code, "[MDL]"))
                    
                    try:
                        current_report_date_obj = datetime.strptime(new_report_data_consulta_str, '%d/%m/%Y')
                        current_report_funcao_codes = set()
                        log_area.write(f"  - Novo relatório encontrado na Página {page_num} com data: {new_report_data_consulta_str}\n")
                    except ValueError:
                        log_area.write(f"  - AVISO: Data de consulta inválida '{new_report_data_consulta_str}' na Página {page_num}.\n")
                        current_report_date_obj = None
                
                if current_report_date_obj:
                    codes_from_this_page = extract_funcao_codes_from_page(page)
                    current_report_funcao_codes.update(codes_from_this_page)

            if current_report_date_obj and current_report_funcao_codes:
                year_str = str(current_report_date_obj.year)
                for code in current_report_funcao_codes:
                    yearly_funcoes[year_str].add((current_report_date_obj, code, "[MDL]"))

    except Exception as e:
        log_area.write(f"Error processing PDF {pdf_path}: {e}\n")
        import traceback
        log_area.write(traceback.format_exc() + "\n")
        return {}
        
    return yearly_funcoes
      
def extract_cpf_from_pdf(pdf_path, log_area):
    """Extracts the CPF number from the first page of the PDF."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            first_page_text = pdf.pages[0].extract_text()
            if first_page_text:
                # Regex to find a CPF pattern. Catches XXX.XXX.XXX-XX format.
                match = re.search(r'(\d{3}\.\d{3}\.\d{3}-\d{2})', first_page_text)
                if match:
                    cpf = match.group(1)
                    log_area.write(f"  - CPF do servidor: {cpf}\n")
                    return cpf
    except Exception as e:
        log_area.write(f"  - ERRO ao extrair CPF do PDF: {e}\n")
    return None

def scrape_mainframe_data(cpf, username, password, log_area):
    """
    Logs into intra.educacao.go.gov.br, navigates to the Power BI dashboard,
    searches for the CPF, scrolls through the entire results table by row index, and scrapes data.
    Returns a dictionary of {year: {set of (date_obj, code, source)}}.
    """
    log_area.write("Iniciando scraping do MAINFRAME...\n")
    scraped_data = defaultdict(set)
    
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1200")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--log-level=3")
    
    driver = None
    try:
        log_area.write("  - Configurando e iniciando o ChromeDriver...\n")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 45)
        
        # --- Steps 1-3: Login, Navigate ---
        log_area.write("  - Navegando para a página de login...\n")
        driver.get("https://intra.educacao.go.gov.br")
        wait.until(EC.element_to_be_clickable((By.ID, 'ctl00_PlaceHolderMain_signInControl_UserName'))).send_keys(username)
        wait.until(EC.element_to_be_clickable((By.ID, 'ctl00_PlaceHolderMain_signInControl_password'))).send_keys(password)
        wait.until(EC.element_to_be_clickable((By.ID, 'ctl00_PlaceHolderMain_signInControl_login'))).click()
        
        log_area.write("  - Clicando em 'SPG'...\n")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@style, 'SPG.png')]"))).click()
        
        log_area.write("  - Clicando em 'MAINFRAME - Aposentadoria'...\n")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@title='MAINFRAME - Aposentadoria']"))).click()

        # --- Step 4: Switch to iframes ---
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.XPATH, "//iframe[contains(@src, 'dw-report.educacao.go.gov.br')]")))
        
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.XPATH, "//iframe[contains(@src, 'app.powerbi.com')]")))

        log_area.write("  - Aguardando o carregamento inicial da tabela de dados...\n")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.tableEx")))
        log_area.write("  - Tabela inicial carregada.\n")
        
        # --- Step 5: Interact with CPF Slicer ---
        log_area.write("  - Procurando o CPF...\n")
        cpf_visual_container = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'visualContainer') and @aria-label='CPF ']")))
        search_iframe = cpf_visual_container.find_element(By.TAG_NAME, "iframe")
        wait.until(EC.frame_to_be_available_and_switch_to_it(search_iframe))
        
        cpf_numeric = cpf.replace('.', '').replace('-', '')
        search_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="search-field"]')))
        search_input.clear()
        search_input.send_keys(cpf_numeric)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button.search-button'))).click()
        
        # --- Step 6: Wait for filter to apply ---
        driver.switch_to.parent_frame()
        log_area.write("  - Aguardando a tabela ser filtrada...\n")
        wait.until(EC.invisibility_of_element_located((By.TAG_NAME, "spinner")))
        time.sleep(2)

        # --- Step 7: Scrape table by row index ---
        log_area.write("  - Coletando dados da tabela...\n")
        grid_container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.interactive-grid')))
        
        try:
            total_rows = int(grid_container.get_attribute('aria-rowcount'))
            log_area.write(f"  - Tabela indica um total de {total_rows - 1} linhas de dados.\n")
        except (ValueError, TypeError):
            log_area.write("  - AVISO: Não foi possível determinar o número total de linhas. Scraping pode ser incompleto.\n")
            return None

        scroll_container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.mid-viewport')))
        
        for i in range(2, total_rows + 1):
            attempts = 0
            while attempts < 20:
                try:
                    code_cell = driver.find_element(By.XPATH, f'.//div[@role="row" and @aria-rowindex="{i}"]//div[@role="gridcell" and @aria-colindex="2"]')
                    date_cell = driver.find_element(By.XPATH, f'.//div[@role="row" and @aria-rowindex="{i}"]//div[@role="gridcell" and @aria-colindex="9"]')
                    
                    code = code_cell.text
                    date_str = date_cell.text

                    if code and code.isdigit() and date_str:
                        try:
                            formatted_code = code.zfill(3)
                            
                            # Convert the date string to a datetime object
                            date_obj = datetime.strptime(date_str.split(' ')[0], '%d/%m/%Y')
                            year_str = str(date_obj.year)
                            
                            # Store a tuple (date_object, formatted_code, source)
                            scraped_data[year_str].add((date_obj, formatted_code, "[MAINFRAME]"))
                            log_area.write(f"    - Linha {i-1}: Encontrado Código={formatted_code}, Data={date_str}\n")
                        except ValueError:
                            log_area.write(f"    - AVISO: Formato de data inválido na tabela: '{date_str}'\n")
                    
                    break
                    
                except NoSuchElementException:
                    scroll_container.send_keys(Keys.PAGE_DOWN)
                    time.sleep(0.2)
                    attempts += 1
            
            if attempts >= 20:
                log_area.write(f"  - AVISO: Não foi possível encontrar a linha com aria-rowindex='{i}' após várias tentativas de rolagem.\n")
        
        log_area.write(f"SUCESSO: Scraping do MAINFRAME concluído. Dados coletados de {len(scraped_data)} anos.\n")
        return scraped_data
        
    except Exception as e:
        log_area.write(f"\nERRO durante o scraping do MAINFRAME: {e}\n")
        return None
        
    finally:
        if driver:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
            driver.quit()

# --- Tkinter GUI Application ---
class PdfAnalyzerApp:
    def __init__(self, master):
        self.master = master
        master.title("Funções MDL")
        
        # --- Window Sizing and Centering ---
        window_width = 800
        window_height = 700 
        screen_width = master.winfo_screenwidth()
        screen_height = master.winfo_screenheight()
        center_x = int(screen_width/2 - window_width / 2)
        center_y = int(screen_height/2 - window_height / 2)
        master.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')

        self.selected_pdf_path = None
        self._results_modified_event_id = None 

        # --- Top Controls Frame ---
        top_controls_frame = tk.Frame(master, pady=10)
        top_controls_frame.pack(fill=tk.X, padx=10)

        self.select_button = tk.Button(top_controls_frame, text="Selecione o PDF", command=self.select_pdf)
        self.select_button.pack(side=tk.LEFT)

        self.pdf_path_entry = tk.Entry(top_controls_frame, width=60, state='readonly')
        self.pdf_path_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # --- MAINFRAME Login Frame ---
        mainframe_frame = tk.LabelFrame(master, text="MAINFRAME Login", padx=10, pady=5)
        mainframe_frame.pack(fill=tk.X, padx=10, pady=(5, 0))

        # Username
        tk.Label(mainframe_frame, text="Usuário:").pack(side=tk.LEFT, padx=(0, 5))
        self.mainframe_user = tk.StringVar()
        self.mainframe_user.trace_add("write", self._update_analyze_button_state)
        mainframe_user_entry = tk.Entry(mainframe_frame, textvariable=self.mainframe_user, width=25)
        mainframe_user_entry.pack(side=tk.LEFT, padx=(0, 15))

        # Password
        tk.Label(mainframe_frame, text="Senha:").pack(side=tk.LEFT, padx=(0, 5))
        self.mainframe_pass = tk.StringVar()
        self.mainframe_pass.trace_add("write", self._update_analyze_button_state)
        mainframe_pass_entry = tk.Entry(mainframe_frame, textvariable=self.mainframe_pass, show="*", width=25)
        mainframe_pass_entry.pack(side=tk.LEFT)

        # 'Procurar Funções' button
        self.analyze_button = tk.Button(mainframe_frame, text="PROCURAR FUNÇÕES", command=self.start_analysis_thread, state=tk.DISABLED)
        self.analyze_button.pack(side=tk.RIGHT, padx=(10, 0))

        # --- Consultar Função Frame ---
        consultar_funcao_frame = tk.LabelFrame(master, text="Consultar Função", padx=10, pady=10)
        consultar_funcao_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        tk.Label(consultar_funcao_frame, text="Código:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.funcao_code_entry = tk.Entry(consultar_funcao_frame, width=10)
        self.funcao_code_entry.pack(side=tk.LEFT, padx=(0, 5))
        self.funcao_code_entry.bind("<Return>", self.consult_funcao_event)

        self.consultar_funcao_button = tk.Button(consultar_funcao_frame, text="Consultar", command=self.consult_funcao)
        self.consultar_funcao_button.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(consultar_funcao_frame, text="Função:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.funcao_result_text = tk.StringVar()
        self.funcao_result_entry = tk.Entry(consultar_funcao_frame, textvariable=self.funcao_result_text, width=50, state='readonly', relief="sunken", borderwidth=1)
        self.funcao_result_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.funcao_result_text.set("")

        # --- Progress Bar ---
        self.progress_bar = ttk.Progressbar(master, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.pack(pady=(0,10), padx=10, fill=tk.X)

        # Save button frame
        save_button_frame = tk.Frame(master)
        self.save_button = tk.Button(save_button_frame, text="SALVAR RESULTADOS", command=self.save_results, state=tk.DISABLED)
        self.save_button.pack(pady=5)
        save_button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 10))

        # PanedWindow
        self.paned_window = tk.PanedWindow(master, orient=tk.VERTICAL, sashrelief=tk.RAISED, sashwidth=8)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        # Add the Results Area to the PanedWindow
        results_frame = tk.LabelFrame(self.paned_window, text="Resultados Agregados por Ano", padx=5, pady=5)
        self.results_area = scrolledtext.ScrolledText(results_frame, wrap=tk.WORD, state=tk.DISABLED) 
        self.results_area.pack(fill=tk.BOTH, expand=True)
        self.paned_window.add(results_frame)
        self.results_area.bind("<<Modified>>", self._on_results_text_changed_debounced_setup)

        # Add the Log Area to the PanedWindow
        log_frame = tk.LabelFrame(self.paned_window, text="Log de Processamento", padx=5, pady=5)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        self.paned_window.add(log_frame)

        # --- Final Setup ---
        self.master.after(150, self.set_initial_pane_sizes)
        self.stdout_redirector = TextRedirector(self.log_area)
        self.stderr_redirector = TextRedirector(self.log_area)
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = self.stdout_redirector
        sys.stderr = self.stderr_redirector
        
        try:
            import logging
            logging.getLogger("pdfminer").setLevel(logging.ERROR)
        except ImportError:
            self.log_area_write_direct("Logging module not imported.\n")
            
    def set_initial_pane_sizes(self):
        self.master.update_idletasks() 
        try:
            total_height = self.paned_window.winfo_height()
            if total_height > 100:
                sash_position = int(total_height * 0.75)                
                self.paned_window.sash_place(0, 0, sash_position)
            else: 
                self.master.after(200, self.set_initial_pane_sizes)
        except tk.TclError as e:
            self.log_area_write_direct(f"Error setting pane sizes: {e}\n")

    def log_area_write_direct(self, message):
        self.log_area.config(state=tk.NORMAL)
        self.log_area.insert(tk.END, message)
        self.log_area.see(tk.END)
        self.log_area.config(state=tk.DISABLED)
      
    def select_pdf(self):
            filepath = filedialog.askopenfilename(
                title="Selecione o arquivo PDF",
                filetypes=(("PDF files", "*.pdf"), ("All files", "*.*"))
            )
            
            if not filepath:
                self.selected_pdf_path = None
                self.pdf_path_entry.config(state='normal')
                self.pdf_path_entry.delete(0, tk.END)
                self.pdf_path_entry.config(state='readonly')
            else:
                self.selected_pdf_path = filepath
                self.pdf_path_entry.config(state='normal')
                self.pdf_path_entry.delete(0, tk.END)
                self.pdf_path_entry.insert(0, filepath)
                self.pdf_path_entry.config(state='readonly')

            self._update_analyze_button_state()

    def update_progress(self, value):
        self.progress_bar['value'] = value

    def _update_analyze_button_state(self, *args):
        """
        Enables or disables the 'Analisar PDF' button based on whether all
        required inputs (PDF path, username, password) are filled.
        The *args is necessary because this method is used as a callback for StringVar traces.
        """
        # Check if all conditions are met
        pdf_path_filled = bool(self.selected_pdf_path)
        user_filled = bool(self.mainframe_user.get())
        pass_filled = bool(self.mainframe_pass.get())

        if pdf_path_filled and user_filled and pass_filled:
            self.analyze_button.config(state=tk.NORMAL)
        else:
            self.analyze_button.config(state=tk.DISABLED)

    def consult_funcao(self):
        """Looks up the function code and updates the result label."""
        code_to_lookup = self.funcao_code_entry.get().strip()
        
        if not code_to_lookup:
            self.funcao_result_text.set("Por favor, insira um código.")
            return
        
        if not code_to_lookup.isdigit() or len(code_to_lookup) != 3:
            self.funcao_result_text.set("Código inválido. Deve conter 3 dígitos.")
            return

        description = FUNCOES_DICT.get(code_to_lookup) 
        
        if description:
            self.funcao_result_text.set(description)
        else:
            self.funcao_result_text.set("Nenhuma função encontrada")

    def consult_funcao_event(self, event):
        """Handles the Enter key press in the funcao_code_entry."""
        self.consult_funcao()
        return "break"

    def _run_analysis(self):
        # Get credentials and PDF path
        mainframe_user = self.mainframe_user.get()
        mainframe_pass = self.mainframe_pass.get()

        if not self.selected_pdf_path:
            self.master.after_idle(messagebox.showwarning, "Nenhum PDF", "Por favor, selecione um arquivo PDF primeiro.")
            return
            
        if not mainframe_user or not mainframe_pass:
            self.master.after_idle(messagebox.showwarning, "Credenciais Faltando", "Por favor, insira o usuário e a senha do MAINFRAME.")
            return

        # Disable buttons and reset UI elements
        self.master.after_idle(lambda: self.analyze_button.config(state=tk.DISABLED))
        self.master.after_idle(lambda: self.select_button.config(state=tk.DISABLED))
        self.master.after_idle(lambda: self.save_button.config(state=tk.DISABLED))
        self.master.after_idle(lambda: self.progress_bar.config(value=0, mode="indeterminate"))
        self.master.after_idle(self.progress_bar.start)

        # Clear results and logs
        self.master.after_idle(lambda: (
            self.results_area.config(state=tk.NORMAL),
            self.results_area.delete(1.0, tk.END),
            self.results_area.config(state=tk.DISABLED)
        ))
        self.master.after_idle(lambda: self.log_area.config(state=tk.NORMAL))
        self.master.after_idle(lambda: self.log_area.delete(1.0, tk.END))

        try:
            # --- EXTRACT CPF FIRST ---
            cpf = extract_cpf_from_pdf(self.selected_pdf_path, self.stdout_redirector)
            if not cpf:
                self.master.after_idle(messagebox.showerror, "Erro no PDF", "Não foi possível encontrar um CPF no arquivo PDF selecionado.")
                return

            # --- BLOCK 1: WEB SCRAPING ---
            self.master.after_idle(self.log_area_write_direct, "Iniciando Etapa 1: Scraping de Dados do Power BI...\n" + "="*50 + "\n")
            self.master.after_idle(self.progress_bar.start)

            scraped_data = scrape_mainframe_data(cpf, mainframe_user, mainframe_pass, self.stdout_redirector)
            
            self.master.after_idle(self.progress_bar.stop)
            if scraped_data is None:
                self.master.after_idle(messagebox.showerror, "Erro de Scraping", "Falha ao buscar dados do MAINFRAME. Verifique o log para detalhes.")
                return 

            # --- BLOCK 2: PDF ANALYSIS ---
            self.master.after_idle(self.log_area_write_direct, "\nIniciando Etapa 2: Análise do Arquivo PDF...\n" + "="*50 + "\n")
            self.master.after_idle(lambda: self.progress_bar.config(mode="determinate"))

            pdf_data = aggregate_yearly_data_multi_report(self.selected_pdf_path, self.stdout_redirector, self.update_progress)

            # --- BLOCK 3: MERGE DATA ---
            self.master.after_idle(self.log_area_write_direct, "\nIniciando Etapa 3: Mesclando e Removendo Duplicatas...\n" + "="*50 + "\n")
            
            final_yearly_data = defaultdict(list)
            
            # Get a set of all years from both sources
            all_years = set(pdf_data.keys()) | set(scraped_data.keys() if scraped_data else {})

            for year in sorted(list(all_years)):
                processed_codes_for_year = set()
                pdf_entries = pdf_data.get(year, set())
                mainframe_entries = scraped_data.get(year, set()) if scraped_data else set()

                # 1. Add all unique PDF entries first (priority)
                for date_obj, code, source in sorted(list(pdf_entries)):
                    if code not in processed_codes_for_year:
                        final_yearly_data[year].append((date_obj, code, source))
                        processed_codes_for_year.add(code)
                        self.stdout_redirector.write(f"  - Ano {year}: Adicionando código {code} do PDF.\n")

                # 2. Add MAINFRAME entries only if the code has not been added from the PDF
                for date_obj, code, source in sorted(list(mainframe_entries)):
                    if code not in processed_codes_for_year:
                        final_yearly_data[year].append((date_obj, code, source))
                        processed_codes_for_year.add(code)
                        self.stdout_redirector.write(f"  - Ano {year}: Adicionando código {code} do MAINFRAME (não encontrado no PDF).\n")
                    else:
                         self.stdout_redirector.write(f"  - Ano {year}: Ignorando código {code} do MAINFRAME (já existe no PDF).\n")

            # --- update_gui_post_analysis function to run in main thread ---
            def update_gui_post_analysis():
                self.results_area.config(state=tk.NORMAL)
                if final_yearly_data:
                    sorted_years = sorted(final_yearly_data.keys(), key=lambda y: int(y))
                    for year in sorted_years:
                        self.results_area.insert(tk.END, f"Ano: {year}\n")
                        self.results_area.insert(tk.END, "Funções:\n")
                        
                        # Sort the final, de-duplicated list by date
                        sorted_entries = sorted(final_yearly_data[year], key=lambda x: x[0])
                        
                        if sorted_entries:
                            for date_obj, code, source in sorted_entries:
                                description = FUNCOES_DICT.get(code, f"DESCRIÇÃO NÃO ENCONTRADA PARA {code}")
                                self.results_area.insert(tk.END, f"  {source} {code} - {description}\n")
                        else:
                            self.results_area.insert(tk.END, "  -\n")
                        self.results_area.insert(tk.END, "\n")
                    self.save_button.config(state=tk.NORMAL)
                else:
                    self.results_area.insert(tk.END, "Nenhum dado encontrado após scraping e análise do PDF.\n")
                    self.save_button.config(state=tk.DISABLED)
                    messagebox.showinfo("Processamento Concluído", "Nenhum dado encontrado.")
                
                self._actual_handle_results_modified()

            self.master.after_idle(update_gui_post_analysis)

        finally:
            self.master.after_idle(self.progress_bar.stop)
            self.master.after_idle(self.log_area_write_direct, "\n" + "="*50 + "\nAnálise completa.\n")
            self.master.after_idle(lambda: self.analyze_button.config(state=tk.NORMAL))
            self.master.after_idle(lambda: self.select_button.config(state=tk.NORMAL))
            self.master.after_idle(lambda: self.progress_bar.config(value=0))

    def start_analysis_thread(self):
        analysis_thread = threading.Thread(target=self._run_analysis, daemon=True)
        analysis_thread.start()

    def save_results(self):
        results_content = self.results_area.get("1.0", "end-1c").strip() 

        if not results_content:
            messagebox.showwarning("Nada para Salvar", "A área de resultados está vazia.")
            self.save_button.config(state=tk.DISABLED) 
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Salvar Resultados Como..."
        )
        if not filepath: return

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(results_content) 
            messagebox.showinfo("Salvo com Sucesso", f"Resultados salvos em:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar o arquivo:\n{e}")
            self.log_area_write_direct(f"Error saving results to {filepath}: {e}\n")

    def _on_results_text_changed_debounced_setup(self, event=None):
        if self._results_modified_event_id:
            self.master.after_cancel(self._results_modified_event_id)
        if self.results_area['state'] == tk.NORMAL:
             self._results_modified_event_id = self.master.after(300, self._actual_handle_results_modified)

    def _actual_handle_results_modified(self):
        self._results_modified_event_id = None 
        try:
            if self.results_area['state'] == tk.NORMAL and self.results_area.edit_modified(): 
                current_results_text = self.results_area.get("1.0", "end-1c").strip()
                if current_results_text:
                    if self.save_button['state'] == tk.DISABLED:
                        self.save_button.config(state=tk.NORMAL)
                else:
                    if self.save_button['state'] == tk.NORMAL:
                        self.save_button.config(state=tk.DISABLED)
            self.results_area.edit_modified(False) 
        except tk.TclError:
            pass

def main():
    root = tk.Tk()
    app = PdfAnalyzerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()