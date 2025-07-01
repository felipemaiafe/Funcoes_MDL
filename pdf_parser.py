import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
import pdfplumber
import re
import sys
import io
from collections import defaultdict
from funcoes_map import FUNCOES_DICT # Ensure this file is correct and in the same directory
import threading

# --- TextRedirector ---
class TextRedirector(io.StringIO):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget

    def write(self, s):
        # Schedule the GUI update to happen in the main Tkinter thread
        self.widget.after_idle(self._write_to_widget, s)

    def _write_to_widget(self, s):
        self.widget.config(state=tk.NORMAL)
        self.widget.insert(tk.END, s)
        self.widget.see(tk.END)
        self.widget.config(state=tk.DISABLED)

    def flush(self):
        pass

# --- PDF Parsing Logic (Assumed correct from previous iterations) ---
def extract_year_from_date_string(date_str, log_area):
    if not date_str: return None
    match = re.search(r'\d{2}/\d{2}/(\d{4})', date_str)
    if match: return match.group(1)
    log_area.write(f"Debug: Could not parse year from date string: {date_str}\n")
    return None

def is_start_of_new_report(page_text, page_num, log_area):
    if not page_text: return None
    page_marker_match = re.search(r"Página\s*1(?:$|\s*de\s*\d+)", page_text, re.IGNORECASE | re.MULTILINE)
    if not page_marker_match:
        # log_area.write(f"Debug (Page {page_num}): No 'Página 1' marker.\n")
        return None
    # log_area.write(f"Debug (Page {page_num}): Found 'Página 1' marker.\n")
    page_text_lines = page_text.split('\n')
    data_consulta_date_str = None
    for i, line in enumerate(page_text_lines):
        if "Data Consulta" in line and "CPF" in line and "Nome" in line and "Vínculo" in line:
            if i + 1 < len(page_text_lines):
                value_line = page_text_lines[i + 1]
                date_match_in_line = re.search(r"(\d{2}/\d{2}/\d{4})", value_line)
                if date_match_in_line:
                    data_consulta_date_str = date_match_in_line.group(1)
                    log_area.write(f"Debug (Page {page_num}): New report - 'Data Consulta' {data_consulta_date_str}\n")
                    return data_consulta_date_str
    match_dc_fallback = re.search(r"Data Consulta\s*[\n\r]?\s*(\d{2}/\d{2}/\d{4})", page_text)
    if match_dc_fallback:
        data_consulta_date_str = match_dc_fallback.group(1)
        log_area.write(f"Debug (Page {page_num}): New report - 'Data Consulta' {data_consulta_date_str} via fallback.\n")
        return data_consulta_date_str
    log_area.write(f"Debug (Page {page_num}): Has 'Página 1' but no 'Data Consulta'. Not new report start.\n")
    return None

def extract_funcao_codes_from_page(page, page_num, log_area):
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
    yearly_funcoes = defaultdict(set)
    min_year_overall, max_year_overall = float('inf'), float('-inf')
    all_found_years_in_pdf = set()
    current_report_year_str, current_report_funcao_codes = None, set()
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                log_area.write("Error: PDF has no pages.\n"); return {}
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                if progress_callback:
                    # Schedule GUI update from the main thread
                    log_area.widget.master.after_idle(progress_callback, (i + 1) / total_pages * 100)

                page_num = i + 1
                page_text = page.extract_text()
                new_report_data_consulta_str = is_start_of_new_report(page_text, page_num, log_area)
                if new_report_data_consulta_str:
                    if current_report_year_str and current_report_funcao_codes:
                        yearly_funcoes[current_report_year_str].update(current_report_funcao_codes)
                    current_report_year_str = extract_year_from_date_string(new_report_data_consulta_str, log_area)
                    current_report_funcao_codes = set()
                    if current_report_year_str:
                        year_int = int(current_report_year_str)
                        min_year_overall, max_year_overall = min(min_year_overall, year_int), max(max_year_overall, year_int)
                        all_found_years_in_pdf.add(year_int)
                    else:
                        current_report_year_str = None # Invalidates current report if year not found
                
                if current_report_year_str: # Only add codes if we have a valid current year
                    codes_from_this_page = extract_funcao_codes_from_page(page, page_num, log_area)
                    if codes_from_this_page:
                        current_report_funcao_codes.update(codes_from_this_page)

            if current_report_year_str and current_report_funcao_codes: # Finalize last report
                yearly_funcoes[current_report_year_str].update(current_report_funcao_codes)

            if all_found_years_in_pdf:
                for year_num_iter in range(min_year_overall, max_year_overall + 1):
                    if str(year_num_iter) not in yearly_funcoes: yearly_funcoes[str(year_num_iter)] = set()
            else: # No years were successfully extracted from any page
                log_area.write("No 'Data Consulta' years found in the entire PDF.\n"); return {}
    except Exception as e:
        log_area.write(f"Error processing PDF {pdf_path}: {e}\n")
        import traceback
        log_area.write(traceback.format_exc() + "\n"); return {}
    return yearly_funcoes

# --- Tkinter GUI Application ---
class PdfAnalyzerApp:
    def __init__(self, master):
        self.master = master
        master.title("Funções MDL")
        
        window_width = 800 # Adjusted width
        window_height = 700 
        screen_width = master.winfo_screenwidth()
        screen_height = master.winfo_screenheight()
        center_x = int(screen_width/2 - window_width / 2)
        center_y = int(screen_height/2 - window_height / 2)
        master.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')

        self.selected_pdf_path = None
        self._results_modified_event_id = None 

        top_controls_frame = tk.Frame(master, pady=10)
        top_controls_frame.pack(fill=tk.X, padx=10)

        self.select_button = tk.Button(top_controls_frame, text="Selecione o PDF", command=self.select_pdf)
        self.select_button.pack(side=tk.LEFT)

        self.pdf_path_entry = tk.Entry(top_controls_frame, width=60, state='readonly') # Adjusted width
        self.pdf_path_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        self.analyze_button = tk.Button(top_controls_frame, text="Analisar PDF", command=self.start_analysis_thread, state=tk.DISABLED) # Shorter text
        self.analyze_button.pack(side=tk.LEFT, padx=5)

        # Consultar Função Frame ---
        consultar_funcao_frame = tk.LabelFrame(master, text="Consultar Função", padx=10, pady=10)
        consultar_funcao_frame.pack(fill=tk.X, padx=10, pady=(0, 5)) # pady=(0,5) for a little space below

        tk.Label(consultar_funcao_frame, text="Código:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.funcao_code_entry = tk.Entry(consultar_funcao_frame, width=10)
        self.funcao_code_entry.pack(side=tk.LEFT, padx=(0, 5))
        self.funcao_code_entry.bind("<Return>", self.consult_funcao_event)

        self.consultar_funcao_button = tk.Button(consultar_funcao_frame, text="Consultar", command=self.consult_funcao)
        self.consultar_funcao_button.pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(consultar_funcao_frame, text="Função:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.funcao_result_text = tk.StringVar() # StringVar to hold the result
        self.funcao_result_entry = tk.Entry(consultar_funcao_frame, textvariable=self.funcao_result_text, width=50, state='readonly', relief="sunken", borderwidth=1)
        self.funcao_result_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.funcao_result_text.set("") # Initial empty state

        # --- Progress Bar ---
        self.progress_bar = ttk.Progressbar(master, orient="horizontal", length=300, mode="determinate")
        self.progress_bar.pack(pady=(0,10), padx=10, fill=tk.X) # Added bottom padding

        display_frame = tk.Frame(master)
        display_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10)) # Added bottom padding
        
        self.paned_window = tk.PanedWindow(display_frame, orient=tk.VERTICAL, sashrelief=tk.RAISED, sashwidth=8)
        self.paned_window.pack(fill=tk.BOTH, expand=True)

        results_frame = tk.LabelFrame(self.paned_window, text="Resultados Agregados por Ano", padx=5, pady=5)
        self.results_area = scrolledtext.ScrolledText(results_frame, wrap=tk.WORD, state=tk.DISABLED) 
        self.results_area.pack(fill=tk.BOTH, expand=True)
        self.paned_window.add(results_frame) 
        self.results_area.bind("<<Modified>>", self._on_results_text_changed_debounced_setup)

        save_button_frame = tk.Frame(self.paned_window) 
        self.save_button = tk.Button(save_button_frame, text="Salvar Resultados", command=self.save_results, state=tk.DISABLED)
        self.save_button.pack(pady=5) 
        self.paned_window.add(save_button_frame, minsize=40, sticky="ew") # Allow horizontal stretch for centering

        log_frame = tk.LabelFrame(self.paned_window, text="Log de Processamento", padx=5, pady=5)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        self.paned_window.add(log_frame)
        
        self.master.after(150, self.set_initial_pane_sizes) # Increased delay slightly

        self.stdout_redirector = TextRedirector(self.log_area)
        self.stderr_redirector = TextRedirector(self.log_area)
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = self.stdout_redirector
        sys.stderr = self.stderr_redirector
        
        try:
            import logging
            logging.getLogger("pdfminer").setLevel(logging.ERROR)
            # self.log_area_write_direct("Set pdfminer log level to ERROR.\n")
        except ImportError:
            self.log_area_write_direct("Logging module not imported.\n")
            
    def set_initial_pane_sizes(self):
        self.master.update_idletasks() 
        try:
            total_height = self.paned_window.winfo_height()
            if total_height > 100:
                results_height = int(total_height * 0.70) 
                save_button_frame_height = self.save_button.winfo_reqheight() + 10 # Get required height + padding
                if save_button_frame_height < 40: save_button_frame_height = 40 # Ensure minsize

                self.paned_window.sash_place(0, 0, results_height)
                self.paned_window.sash_place(1, 0, results_height + save_button_frame_height)
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
            self.pdf_path_entry.config(state='normal'); self.pdf_path_entry.delete(0, tk.END); self.pdf_path_entry.config(state='readonly')
            # Analyze button should be disabled if no file path
            self.master.after_idle(lambda: self.analyze_button.config(state=tk.DISABLED))
            # Save button state should remain as is (reflecting current results_area)
            return

        self.selected_pdf_path = filepath
        self.pdf_path_entry.config(state='normal'); self.pdf_path_entry.delete(0, tk.END); self.pdf_path_entry.insert(0, filepath); self.pdf_path_entry.config(state='readonly')
        # Enable Analyze button now that a file is selected
        self.master.after_idle(lambda: self.analyze_button.config(state=tk.NORMAL))
        # Do NOT change save_button state here. It depends on the current results.

    def update_progress(self, value):
        self.progress_bar['value'] = value

    def consult_funcao(self):
        """Looks up the function code and updates the result label."""
        code_to_lookup = self.funcao_code_entry.get().strip()
        
        if not code_to_lookup:
            self.funcao_result_text.set("Por favor, insira um código.")
            return
        
        # Validation: Code must be exactly 3 digits
        if not code_to_lookup.isdigit() or len(code_to_lookup) != 3:
            self.funcao_result_text.set("Código inválido. Deve conter 3 dígitos.") # Updated message
            return

        # No need for .upper() if all keys in FUNCOES_DICT are purely numeric strings
        description = FUNCOES_DICT.get(code_to_lookup) 
        
        if description:
            self.funcao_result_text.set(description)
        else:
            self.funcao_result_text.set("Nenhuma função encontrada")

    def consult_funcao_event(self, event):
        """Handles the Enter key press in the funcao_code_entry."""
        self.consult_funcao()
        return "break" # Prevents the default Enter key behavior (like adding a newline)

    def _run_analysis(self):
        if not self.selected_pdf_path:
            self.master.after_idle(messagebox.showwarning, "Nenhum PDF", "Por favor, selecione um arquivo PDF primeiro.")
            return

        # Disable buttons during analysis
        self.master.after_idle(lambda: self.analyze_button.config(state=tk.DISABLED))
        self.master.after_idle(lambda: self.select_button.config(state=tk.DISABLED))
        self.master.after_idle(lambda: self.save_button.config(state=tk.DISABLED)) # Disable save during analysis
        self.master.after_idle(lambda: self.progress_bar.config(value=0, mode="determinate"))
        
        # Clear previous results
        self.master.after_idle(lambda: (
            self.results_area.config(state=tk.NORMAL),
            self.results_area.delete(1.0, tk.END),
            self.results_area.config(state=tk.DISABLED) # Keep disabled until results populate
        ))
        # Clear log area
        self.master.after_idle(lambda: self.log_area.config(state=tk.NORMAL))
        self.master.after_idle(lambda: self.log_area.delete(1.0, tk.END))

        self.master.after_idle(self.log_area_write_direct, f"Processing {self.selected_pdf_path}...\n" + "="*40 + "\n")

        try:
            yearly_data = aggregate_yearly_data_multi_report(self.selected_pdf_path, self.stdout_redirector, self.update_progress)
            
            def update_gui_post_analysis():
                self.results_area.config(state=tk.NORMAL) # Make editable

                if yearly_data:
                    sorted_years = sorted(yearly_data.keys(), key=lambda y: int(y))
                    for year in sorted_years:
                        self.results_area.insert(tk.END, f"Ano: {year}\n")
                        self.results_area.insert(tk.END, "Funções:\n")
                        codes = yearly_data[year]
                        if codes:
                            sorted_codes = sorted(list(codes))
                            for code in sorted_codes:
                                description = FUNCOES_DICT.get(code, f"DESCRIÇÃO NÃO ENCONTRADA PARA {code}")
                                self.results_area.insert(tk.END, f"  {code} - {description}\n")
                        else:
                            self.results_area.insert(tk.END, "  -\n")
                        self.results_area.insert(tk.END, "\n")
                else: # yearly_data is empty or None
                    self.results_area.insert(tk.END, "Não foi possível extrair dados anuais do PDF, ou nenhum ano foi encontrado.\n")
                    # Show appropriate messagebox
                    log_content_snapshot = self.log_area.get("1.0", tk.END) 
                    if "Error" not in log_content_snapshot and "traceback" not in log_content_snapshot:
                         messagebox.showinfo("Processamento Concluído", "Nenhum dado de 'Data Consulta' e 'Função' foi encontrado no formato esperado.")
                    else:
                         messagebox.showerror("Erro de Processamento", "Ocorreu um erro durante o processamento. Verifique o log para detalhes.")
                
                # After populating (or inserting error message), trigger the check for save button state
                self.results_area.edit_modified(True) # Mark as modified to trigger handler
                self._actual_handle_results_modified() # Call handler to update save button

            self.master.after_idle(update_gui_post_analysis)

        except Exception as e:
            self.master.after_idle(self.log_area_write_direct, f"Unhandled error during analysis thread execution: {e}\n")
            import traceback
            self.master.after_idle(self.log_area_write_direct, traceback.format_exc() + "\n")
            self.master.after_idle(messagebox.showerror, "Erro Crítico", f"Um erro crítico ocorreu: {e}")
            self.master.after_idle(lambda: self.results_area.config(state=tk.DISABLED))
            self.master.after_idle(lambda: self.save_button.config(state=tk.DISABLED))

        finally:
            self.master.after_idle(self.log_area_write_direct, "="*40 + "\nProcessing complete.\n")
            self.master.after_idle(lambda: self.analyze_button.config(state=tk.NORMAL))
            self.master.after_idle(lambda: self.select_button.config(state=tk.NORMAL))
            self.master.after_idle(lambda: self.progress_bar.config(value=0))

    def start_analysis_thread(self):
        analysis_thread = threading.Thread(target=self._run_analysis, daemon=True)
        analysis_thread.start()

    def save_results(self):
        results_content = self.results_area.get("1.0", "end-1c").strip() 

        if not results_content: # This check is a safeguard
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
            # Check the modified flag only if the widget is in a state where it can be modified
            if self.results_area['state'] == tk.NORMAL and self.results_area.edit_modified(): 
                current_results_text = self.results_area.get("1.0", "end-1c").strip()
                if current_results_text:
                    if self.save_button['state'] == tk.DISABLED:
                        self.save_button.config(state=tk.NORMAL)
                else: # Text area is empty
                    if self.save_button['state'] == tk.NORMAL:
                        self.save_button.config(state=tk.DISABLED)
            self.results_area.edit_modified(False) 
        except tk.TclError: # Can occur if widget is destroyed
            pass

def main():
    root = tk.Tk()
    app = PdfAnalyzerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()