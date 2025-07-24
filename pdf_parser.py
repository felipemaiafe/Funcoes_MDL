import tkinter as tk
import threading
import pdfplumber
import time
import re
import sys
import io

from datetime import datetime
from collections import defaultdict
from tkinter import filedialog, scrolledtext, messagebox, ttk
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC

from db_utils import load_all_initial_data

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

def extract_funcao_and_lotacao_from_page(page, unidades_data, default_lotacao):
    """
    Extracts (code, lotacao_string) tuples from all relevant tables on a page.
    Prioritizes row-specific Lotação over the default.
    """
    results = set()
    tables = page.extract_tables()
    if not tables:
        return results

    for table in tables:
        if not table or not table[0]: continue
        header = [h.replace('\n', '') if h else '' for h in table[0]]

        if "Função" not in header:
            continue

        funcao_idx = header.index("Função")
        lotacao_idx = header.index("Lotação") if "Lotação" in header else -1

        for row in table[1:]:
            if len(row) <= funcao_idx: continue
            
            funcao_text = row[funcao_idx]
            if not funcao_text: continue

            # Extract 3-digit code from function text
            match = re.search(r'\(Cod\.\s*(\d{3})\)', funcao_text)
            code = match.group(1) if match else (funcao_text.strip() if funcao_text.strip().isdigit() and len(funcao_text.strip()) == 3 else None)
            
            if not code: continue

            lotacao_display = default_lotacao
            
            # Check if this row has its own specific Lotação code (INEP or MDL)
            if lotacao_idx != -1 and len(row) > lotacao_idx and row[lotacao_idx]:
                lotacao_cell_text = row[lotacao_idx].replace('\n', ' ')
                potential_code = lotacao_cell_text.split(' ')[0].strip()
                
                # Check if this code exists in our database mapping
                if potential_code in unidades_data:
                    lotacao_display = unidades_data[potential_code]['display_string']
                else:
                    # If no code match, use the raw text from the cell as a fallback
                    lotacao_display = lotacao_cell_text

            results.add((code, lotacao_display))
            
    return results

def extract_funcao_codes_from_page(page):
    codes = set()
    tables = page.extract_tables()
    if tables:
        for table_data in enumerate(tables):
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

def aggregate_yearly_data_multi_report(pdf_path, log_area, unidades_data, progress_callback=None):
    yearly_funcoes = defaultdict(set)
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                log_area.write("Error: PDF has no pages.\n"); return {}
            
            total_pages = len(pdf.pages)
            current_report_date_obj = None
            current_report_funcao_tuples = set()

            for i, page in enumerate(pdf.pages):
                if progress_callback:
                    log_area.widget.master.after_idle(progress_callback, (i + 1) / total_pages * 100)
                
                page_num = i + 1
                page_text = page.extract_text()
                new_report_data_consulta_str = is_start_of_new_report(page_text)

                if new_report_data_consulta_str:
                    # Finalize previous report
                    if current_report_date_obj and current_report_funcao_tuples:
                        year_str = str(current_report_date_obj.year)
                        for code, lotacao in current_report_funcao_tuples:
                            yearly_funcoes[year_str].add((current_report_date_obj, code, "[MDL]", lotacao))
                    
                    # Start new report
                    try:
                        report_date = datetime.strptime(new_report_data_consulta_str, '%d/%m/%Y')
                        cutoff_date = datetime(2014, 5, 1)
                        if report_date >= cutoff_date:
                            current_report_date_obj = report_date
                            current_report_funcao_tuples = set()
                            log_area.write(f"  - Relatório VÁLIDO encontrado (>= 05/2014) na Pág {page_num} com data: {new_report_data_consulta_str}\n")
                        else:
                            log_area.write(f"  - Relatório IGNORADO (< 05/2014) na Pág {page_num} com data: {new_report_data_consulta_str}\n")
                            current_report_date_obj = None
                            
                    except ValueError:
                        log_area.write(f"  - AVISO: Data de consulta inválida '{new_report_data_consulta_str}' na Página {page_num}.\n")
                        current_report_date_obj = None
                
                if current_report_date_obj:
                    # Find the main Lotação for the report
                    default_lotacao = "-------"
                    for table in page.extract_tables() or []:
                        if table and len(table) > 1 and table[0] and len(table[0]) > 1 and table[0][1] == "Lotação":
                            lotacao_cell_text = table[1][1]
                            potential_code = lotacao_cell_text.split(' ')[0].replace('-', '').strip()
                            if potential_code in unidades_data:
                                default_lotacao = unidades_data[potential_code]['display_string']
                            else:
                                default_lotacao = lotacao_cell_text.replace('\n', ' ')
                            break
                    
                    # Get all function/lotacao pairs from the page's tables
                    tuples_from_page = extract_funcao_and_lotacao_from_page(page, unidades_data, default_lotacao)
                    current_report_funcao_tuples.update(tuples_from_page)

            # Finalize the very last report
            if current_report_date_obj and current_report_funcao_tuples:
                year_str = str(current_report_date_obj.year)
                for code, lotacao in current_report_funcao_tuples:
                    yearly_funcoes[year_str].add((current_report_date_obj, code, "[MDL]", lotacao))

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

def extract_name_from_pdf(pdf_path, log_area):
    """Extracts the Person's Name from the first page of the PDF."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            first_page_text = pdf.pages[0].extract_text()
            if first_page_text:
                match = re.search(r"Nome\s+([\w\s]+?)\s+Data Consulta", first_page_text)
                if match:
                    name = match.group(1).strip()
                    log_area.write(f"  - Nome do servidor: {name}\n")
                    return name
                else:
                    cpf_match = re.search(r"(\d{3}\.\d{3}\.\d{3}-\d{2})", first_page_text)
                    if cpf_match:
                        cpf = cpf_match.group(1)
                        for line in first_page_text.split('\n'):
                            if cpf in line:
                                name_match = re.search(fr"{re.escape(cpf)}\s+([\w\s]+?)\s+\d{{2}}/\d{{2}}/\d{{4}}", line)
                                if name_match:
                                    name = name_match.group(1).strip()
                                    log_area.write(f"  - Nome do servidor: {name}\n")
                                    return name
    except Exception as e:
        log_area.write(f"  - ERRO ao extrair Nome do PDF: {e}\n")
    log_area.write("  - AVISO: Não foi possível encontrar o nome no PDF.\n")
    return None

def scrape_mainframe_data(cpf, username, password, log_area, unidades_data):
    """
    Scrapes Power BI by following a precise multi-pass scroll and scrape logic.
    Horizontal scroll is now fixed using ActionChains to drag the custom scrollbar.
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
        wait = WebDriverWait(driver, 10)
        
        # --- Steps 1-6: Login, navigation, iframe switching, and CPF filtering ---
        log_area.write("  - Navegando para a página de login...\n")
        driver.get("https://intra.educacao.go.gov.br")
        wait.until(EC.element_to_be_clickable((By.ID, 'ctl00_PlaceHolderMain_signInControl_UserName'))).send_keys(username)
        wait.until(EC.element_to_be_clickable((By.ID, 'ctl00_PlaceHolderMain_signInControl_password'))).send_keys(password)
        wait.until(EC.element_to_be_clickable((By.ID, 'ctl00_PlaceHolderMain_signInControl_login'))).click()

        log_area.write("  - Clicando em 'SPG'...\n")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@style, 'SPG.png')]"))).click()

        log_area.write("  - Clicando em 'MAINFRAME - Aposentadoria'...\n")
        wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@title='MAINFRAME - Aposentadoria']"))).click()

        log_area.write("  - Mudando para o iframe container (dw-report)...\n")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.XPATH, "//iframe[contains(@src, 'dw-report.educacao.go.gov.br')]")))

        log_area.write("  - Mudando para o iframe principal do Power BI (app.powerbi.com)...\n")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.XPATH, "//iframe[contains(@src, 'app.powerbi.com')]")))

        log_area.write("  - Aguardando o carregamento inicial da tabela de dados...\n")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.tableEx")))

        log_area.write("  - Procurando e interagindo com o filtro de CPF...\n")
        cpf_visual_container = wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'visualContainer') and @aria-label='CPF ']")))
        search_iframe = cpf_visual_container.find_element(By.TAG_NAME, "iframe")
        wait.until(EC.frame_to_be_available_and_switch_to_it(search_iframe))
        cpf_numeric = cpf.replace('.', '').replace('-', '')
        search_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="search-field"]')))
        search_input.clear()
        search_input.send_keys(cpf_numeric)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button.search-button'))).click()
        driver.switch_to.parent_frame()

        log_area.write("  - Aguardando a tabela ser filtrada...\n")
        wait.until(EC.invisibility_of_element_located((By.TAG_NAME, "spinner")))
        time.sleep(2)

        # --- Step 7: Scrape in Two Passes with explicit scrolling ---        
        collected_data = {}

        # Find the main table container
        table_container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.tableEx")))
        vertical_scroll_container = table_container.find_element(By.CSS_SELECTOR, 'div.mid-viewport')

        # --- PASS 1: Get left-side columns (vertical scroll only) ---
        log_area.write("  - Iniciando 1ª passagem vertical (Código e Data)...\n")
        processed_row_keys_pass1 = set()
        last_known_row_count = -1
        
        while last_known_row_count != len(processed_row_keys_pass1):
            last_known_row_count = len(processed_row_keys_pass1)
            rows = table_container.find_elements(By.XPATH, './/div[@role="row" and contains(@class, "row")]')
            for row in rows:
                try:
                    row_index = row.get_attribute('aria-rowindex')
                    if row_index and row_index not in processed_row_keys_pass1:
                        processed_row_keys_pass1.add(row_index)
                        code_cell = row.find_element(By.XPATH, './/div[@role="gridcell" and @aria-colindex="2"]')
                        date_cell = row.find_element(By.XPATH, './/div[@role="gridcell" and @aria-colindex="9"]')
                        collected_data[row_index] = {'code': code_cell.text, 'date': date_cell.text}
                except NoSuchElementException:
                    continue
            
            driver.execute_script("arguments[0].scrollTop += arguments[0].clientHeight;", vertical_scroll_container)
            time.sleep(0.5)

        # --- Horizontal scroll (using ActionChains on Power BI's custom scrollbar) ---
        log_area.write("  - Rolando horizontalmente (drag do scrollbar)...\n")
        horizontal_scrollbar = table_container.find_element(
            By.XPATH,
            './/div[@class="scroll-bar-div" and contains(@style, "height: 9px")]//div[@class="scroll-bar-part-bar"]'
        )
        actions = ActionChains(driver)
        actions.click_and_hold(horizontal_scrollbar).move_by_offset(500, 0).release().perform()
        time.sleep(1)

        # Reset vertical scroll
        driver.execute_script("arguments[0].scrollTop = 0;", vertical_scroll_container)
        time.sleep(1)

        # --- PASS 2: Get right-side column after horizontal scroll ---
        log_area.write("  - Iniciando 2ª passagem vertical (Unidade)...\n")
        processed_row_keys_pass2 = set()
        last_known_row_count = -1
        while last_known_row_count != len(processed_row_keys_pass2):
            last_known_row_count = len(processed_row_keys_pass2)
            rows = table_container.find_elements(By.XPATH, './/div[@role="row" and contains(@class, "row")]')
            for row in rows:
                try:
                    row_index = row.get_attribute('aria-rowindex')
                    if row_index and row_index not in processed_row_keys_pass2:
                        processed_row_keys_pass2.add(row_index)
                        unidade_cell = row.find_element(By.XPATH, './/div[@role="gridcell" and @aria-colindex="15"]')
                        if row_index in collected_data:
                            collected_data[row_index]['unidade'] = unidade_cell.text
                except NoSuchElementException:
                    continue
            
            driver.execute_script("arguments[0].scrollTop += arguments[0].clientHeight;", vertical_scroll_container)
            time.sleep(0.5)
                
        # --- Combine results ---
        log_area.write("  - Processando e combinando dados coletados...\n")
        for row_index, data in collected_data.items():
            code = data.get('code')
            date_str = data.get('date')
            unidade_str = data.get('unidade')

            lotacao_display = unidade_str if unidade_str else "-------"
            if unidade_str:
                unidade_upper = unidade_str.upper().strip()
                for unit_info in unidades_data.values():
                    if unidade_upper == unit_info['nome_folha'].upper().strip():
                        lotacao_display = unit_info['display_string']
                        break
            
            if code and code.isdigit() and date_str:
                try:
                    formatted_code = code.zfill(3)
                    date_obj = datetime.strptime(date_str.split(' ')[0], '%d/%m/%Y')
                    year_str = str(date_obj.year)
                    scraped_data[year_str].add((date_obj, formatted_code, "[MAINFRAME]", lotacao_display))
                except ValueError:
                    pass

        log_area.write(f"SUCESSO: Scraping do MAINFRAME concluído. {len(collected_data)} linhas de dados processadas.\n")
        return scraped_data
        
    except Exception as e:
        log_area.write(f"\nERRO durante o scraping do MAINFRAME: {e}\n")
        import traceback
        log_area.write(traceback.format_exc() + "\n")
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

        initial_data = load_all_initial_data()
        if not initial_data or not initial_data.get('funcoes') or not initial_data.get('unidades'):
            master.destroy()
            return
        
        self.funcoes_data = initial_data['funcoes']
        self.unidades_data = initial_data['unidades']
        
        # --- Window Sizing and Centering ---
        window_width = 1100
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
        self.funcao_code_entry.bind("<Return>", self.consult_funcao)

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
        
        if not code_to_lookup.isdigit():
            self.funcao_result_text.set("Código inválido. Deve conter apenas dígitos.")
            return
        
        formatted_code = code_to_lookup.zfill(3)

        func_info = self.funcoes_data.get(formatted_code) 
        
        if func_info:
            self.funcao_result_text.set(func_info['descricao'])
        else:
            self.funcao_result_text.set("Nenhuma função encontrada")

    def consult_funcao(self):
        """Looks up the function code and updates the result label."""
        code_to_lookup = self.funcao_code_entry.get().strip()
        
        if not code_to_lookup.isdigit() or len(code_to_lookup) != 3:
            self.funcao_result_text.set("Código inválido. Deve conter 3 dígitos.")
            return

        # Look up the code in the new data structure
        func_info = self.funcoes_data.get(code_to_lookup)
        
        if func_info:
            # Display description and classification
            display_text = f"{func_info['descricao']} ({func_info['classificacao']})"
            self.funcao_result_text.set(display_text)
        else:
            self.funcao_result_text.set("Nenhuma função encontrada")

    def _run_analysis(self):
        # --- Get credentials and PDF path ---
        mainframe_user = self.mainframe_user.get()
        mainframe_pass = self.mainframe_pass.get()
        if not self.selected_pdf_path:
            self.master.after_idle(messagebox.showwarning, "Nenhum PDF", "Por favor, selecione um arquivo PDF primeiro.")
            return
        if not mainframe_user or not mainframe_pass:
            self.master.after_idle(messagebox.showwarning, "Credenciais Faltando", "Por favor, insira o usuário e a senha do MAINFRAME.")
            return

        # --- Disable buttons and reset UI elements ---
        self.master.after_idle(lambda: self.analyze_button.config(state=tk.DISABLED))
        self.master.after_idle(lambda: self.select_button.config(state=tk.DISABLED))
        self.master.after_idle(lambda: self.save_button.config(state=tk.DISABLED))
        self.master.after_idle(lambda: self.progress_bar.config(value=0, mode="indeterminate"))
        self.master.after_idle(self.progress_bar.start)

        # --- Clear results and logs ---
        self.master.after_idle(lambda: (
            self.results_area.config(state=tk.NORMAL),
            self.results_area.delete(1.0, tk.END),
            self.results_area.config(state=tk.DISABLED)
        ))
        self.master.after_idle(lambda: self.log_area.config(state=tk.NORMAL))
        self.master.after_idle(lambda: self.log_area.delete(1.0, tk.END))

        try:
            # --- EXTRACT CPF AND NAME FIRST ---
            self.stdout_redirector.write("Iniciando Etapa 0: Extraindo dados do cabeçalho do PDF...\n" + "="*50 + "\n")
            cpf = extract_cpf_from_pdf(self.selected_pdf_path, self.stdout_redirector)
            if not cpf:
                self.master.after_idle(messagebox.showerror, "Erro no PDF", "Não foi possível encontrar um CPF no arquivo PDF selecionado.")
                return
            
            self.report_name = extract_name_from_pdf(self.selected_pdf_path, self.stdout_redirector) or "Nome não encontrado"
            self.report_cpf = cpf

            # --- BLOCK 1: WEB SCRAPING ---
            self.master.after_idle(self.log_area_write_direct, "\nIniciando Etapa 1: Scraping de Dados do Power BI...\n" + "="*50 + "\n")
            scraped_data = scrape_mainframe_data(cpf, mainframe_user, mainframe_pass, self.stdout_redirector, self.unidades_data)
            
            # --- BLOCK 2: PDF ANALYSIS ---
            self.master.after_idle(self.log_area_write_direct, "\nIniciando Etapa 2: Análise do Arquivo PDF...\n" + "="*50 + "\n")
            pdf_data = aggregate_yearly_data_multi_report(self.selected_pdf_path, self.stdout_redirector, self.unidades_data, self.update_progress)

            # --- BLOCK 3: MERGE DATA ---
            self.master.after_idle(self.log_area_write_direct, "\nIniciando Etapa 3: Mesclando Dados com Base na Data...\n" + "="*50 + "\n")
            
            final_yearly_data = defaultdict(list)
            
            # Get a superset of all years from both sources
            all_years = set(pdf_data.keys()) | set(scraped_data.keys() if scraped_data else {})

            for year in sorted(list(all_years)):
                year_int = int(year)
                
                # The cutoff is the start of 2014. Inside 2014, we check the month.
                if year_int < 2014:
                    # --- BEFORE 2014: MAINFRAME ONLY ---
                    self.stdout_redirector.write(f"  - Ano {year}: Usando dados exclusivamente do MAINFRAME.\n")
                    if scraped_data and year in scraped_data:
                        for date_obj, code, source, lotacao in scraped_data[year]:
                            row = {"date": date_obj, "code": code, "lotacao": lotacao}
                            final_yearly_data[year].append(row)
                
                elif year_int > 2014:
                    # --- AFTER 2014: PDF (MDL) ONLY ---
                    self.stdout_redirector.write(f"  - Ano {year}: Usando dados exclusivamente do PDF (MDL).\n")
                    if year in pdf_data:
                        for date_obj, code, source, lotacao in pdf_data[year]:
                            row = {"date": date_obj, "code": code, "lotacao": lotacao}
                            final_yearly_data[year].append(row)

                else: # year_int == 2014
                    # --- THE TRANSITION YEAR: 2014 ---
                    self.stdout_redirector.write(f"  - Ano {year}: Mesclando dados (ano de transição).\n")
                    
                    # Add MAINFRAME data from BEFORE May 2014
                    if scraped_data and year in scraped_data:
                        for date_obj, code, source, lotacao in scraped_data[year]:
                            if date_obj.month < 5:
                                row = {"date": date_obj, "code": code, "lotacao": lotacao}
                                final_yearly_data[year].append(row)
                    
                    # Add PDF data from ON OR AFTER May 2014
                    if year in pdf_data:
                        for date_obj, code, source, lotacao in pdf_data[year]:
                            if date_obj.month >= 5:
                                row = {"date": date_obj, "code": code, "lotacao": lotacao}
                                final_yearly_data[year].append(row)

            # --- BLOCK 4: DE-DUPLICATE ALL DATA ---
            self.master.after_idle(self.log_area_write_direct, "\nIniciando Etapa 4: Removendo Registros Duplicados...\n" + "="*50 + "\n")
            
            for year in list(final_yearly_data.keys()):
                unique_entries_in_year = {}
                original_row_count = len(final_yearly_data[year])

                # Sort rows by date to ensure the earliest entry for a duplicate key is the one kept.
                sorted_rows = sorted(final_yearly_data[year], key=lambda r: r['date'])
                
                for row in sorted_rows:
                    # A unique entry is defined by its function code and its location (Lotação).
                    # Since "Tipo" is derived from the code and "Períodos" is static, this key is sufficient.
                    key = (row['code'], row['lotacao'])
                    if key not in unique_entries_in_year:
                        unique_entries_in_year[key] = row
                
                if original_row_count > len(unique_entries_in_year):
                    self.stdout_redirector.write(f"  - Ano {year}: {original_row_count} linhas -> {len(unique_entries_in_year)} linhas únicas.\n")

                # Replace the list of rows for the year with the de-duplicated list
                final_yearly_data[year] = list(unique_entries_in_year.values())
                            
            # --- BLOCK 5: UPDATE GUI ---
            def update_gui_post_analysis():
                self.results_area.config(state=tk.NORMAL)
                self.results_area.insert(tk.END, f"{self.report_name.upper()}\n{self.report_cpf}\n\n")
                headers = ["Ano", "Lotação", "Função", "Tipo", "Períodos"]
                header_string = f"{headers[0]:<6}{headers[1]:<35}{headers[2]:<60}{headers[3]:<15}{headers[4]:<25}\n"
                separator = "=" * (len(header_string) - 1) + "\n"
                self.results_area.insert(tk.END, header_string)
                self.results_area.insert(tk.END, separator)

                if final_yearly_data:
                    for year in sorted(final_yearly_data.keys()):
                        rows_for_year = sorted(final_yearly_data[year], key=lambda r: r['date'])
                        if rows_for_year:
                            for i, row in enumerate(rows_for_year):
                                year_display = year if i == 0 else ""
                                code = row['code']
                                func_info = self.funcoes_data.get(code, {'descricao': 'Função Desconhecida','classificacao': 'N/A'})
                                func_desc = f"{func_info['descricao']} (Cod. {code})"
                                func_display = (func_desc[:57] + '...') if len(func_desc) > 57 else func_desc
                                lotacao_display = (row['lotacao'][:32] + '...') if len(row['lotacao']) > 32 else row['lotacao']
                                tipo_display = func_info['classificacao']

                                row_string = (
                                    f"{year_display:<6}"
                                    f"{lotacao_display:<35}"
                                    f"{func_display:<60}"
                                    f"{tipo_display:<15}"
                                    f"{'-------':<25}\n"
                                )
                                self.results_area.insert(tk.END, row_string)
                        else:
                            empty_row = f"{year:<6}{'-------':<35}{'-------':<60}{'-------':<15}{'-------':<25}\n"
                            self.results_area.insert(tk.END, empty_row)
                    self.save_button.config(state=tk.NORMAL)
                else:
                    self.results_area.insert(tk.END, "Nenhum dado encontrado para gerar o relatório.\n")
                    self.save_button.config(state=tk.DISABLED)
                    messagebox.showinfo("Processamento Concluído", "Nenhum dado encontrado.")
                
                self._actual_handle_results_modified()

            self.master.after_idle(update_gui_post_analysis)

        finally:
            self.master.after_idle(self.progress_bar.stop)
            self.master.after_idle(self.log_area_write_direct, "\nAnálise completa.\n")
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

        suggested_filename = "MDL_FUNCOES.txt"
        if hasattr(self, 'report_cpf') and self.report_cpf:
            sanitized_cpf = self.report_cpf
            suggested_filename = f"MDL_{sanitized_cpf}_FUNCOES.txt"

        filepath = filedialog.asksaveasfilename(
            initialfile=suggested_filename,
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Salvar Resultados Como..."
        )

        if not filepath:
            return

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