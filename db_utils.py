import pyodbc
from tkinter import messagebox
import configparser
import os
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def load_unidades_from_db(conn):
    """
    Loads unit/location data from the SGDP_UNIDADES table using a provided connection.
    Returns a dictionary mapping INEP and MDL codes to a standard format.
    """
    unidades_data = {}
    cursor = conn.cursor()
    cursor.execute("SELECT mdl, inep, nome_folha FROM dbo.SGDP_UNIDADES")
    
    for row in cursor.fetchall():
        mdl_code = str(row.mdl).strip() if row.mdl else None
        inep_code = str(row.inep).strip() if row.inep else None
        nome_folha = row.nome_folha

        if not nome_folha:
            continue

        # Format the final string we want to display
        lotacao_display_string = f"{mdl_code} - {nome_folha.strip()}" if mdl_code else nome_folha.strip()

        unit_info = {
            'mdl': mdl_code,
            'inep': inep_code,
            'nome_folha': nome_folha.strip(),
            'display_string': lotacao_display_string
        }
        
        if mdl_code:
            unidades_data[mdl_code] = unit_info
        if inep_code:
            unidades_data[inep_code] = unit_info

    return unidades_data

def load_funcoes_from_db(conn):
    """
    Loads function codes, descriptions, and classifications using a provided connection.
    """
    funcoes_data = {}
    cursor = conn.cursor()
    cursor.execute("SELECT id, descricao, classificacao FROM dbo.SGDP_FUNCOES")
    
    for row in cursor.fetchall():
        code = str(row.id).zfill(3)
        original_classificacao = row.classificacao
        
        if original_classificacao and original_classificacao.startswith("Regência"):
            simplified_classificacao = "Magistério"
        else:
            simplified_classificacao = original_classificacao
        
        funcoes_data[code] = {
            'descricao': row.descricao,
            'classificacao': simplified_classificacao
        }
        
    return funcoes_data

def load_all_initial_data():
    """Connects to the DB once by reading credentials from config.ini."""
    all_data = {'funcoes': None, 'unidades': None}
    conn = None
    
    config = configparser.ConfigParser()
    config_file = resource_path('config.ini')

    if not os.path.exists(config_file):
        messagebox.showerror(
            "Erro de Configuração",
            f"O arquivo de configuração '{config_file}' não foi encontrado.\n\n"
            "Por favor, crie o arquivo com as suas credenciais de banco de dados."
        )
        return None
        
    config.read(config_file)
    
    try:
        db_config = config['database']
        connection_string = (
            f"DRIVER={db_config['driver']};"
            f"SERVER={db_config['server']};"
            f"DATABASE={db_config['database']};"
            f"UID={db_config['uid']};"
            f"PWD={db_config['pwd']};"
            "TrustServerCertificate=yes;"
        )
        conn = pyodbc.connect(connection_string, timeout=5)
        
        print("INFO: Loading Funções from DB...")
        all_data['funcoes'] = load_funcoes_from_db(conn)
        print(f"SUCCESS: Loaded {len(all_data['funcoes'])} Funções.")

        print("INFO: Loading Unidades (Lotações) from DB...")
        all_data['unidades'] = load_unidades_from_db(conn)
        print(f"SUCCESS: Loaded {len(all_data['unidades'])} Unidades.")
        
        return all_data
    
    except KeyError as e:
        messagebox.showerror(
            "Erro de Configuração",
            f"A chave '{e}' está faltando na seção [database] do arquivo {config_file}."
        )
        return None
    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        print(f"DATABASE ERROR: {sqlstate} - {ex}")
        messagebox.showerror(
            "Erro de Conexão com o Banco de Dados",
            f"Não foi possível conectar ao banco de dados.\n\nVerifique as credenciais no arquivo {config_file} e a conexão de rede.\n\nDetalhes: {ex}"
        )
        return None
    except Exception as e:
        print(f"UNEXPECTED ERROR during DB load: {e}")
        messagebox.showerror("Erro Inesperado", f"Ocorreu um erro inesperado ao carregar os dados das funções:\n{e}")
        return None
    finally:
        if conn:
            conn.close()