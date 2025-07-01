import re

def create_funcoes_dict_file(input_list_file="Funções_LIST.txt", output_py_file="funcoes_map.py"):
    """
    Reads a list of function codes and descriptions from an input file
    and creates a Python file with a dictionary mapping these codes.
    """
    funcoes_entries = []
    try:
        with open(input_list_file, 'r', encoding='utf-8') as f_in:
            for line in f_in:
                line = line.strip()
                if not line:
                    continue

                # Handle HTML entities like  
                line = line.replace(' ', ' ')

                # Split at the first occurrence of " - "
                parts = line.split(" - ", 1)
                if len(parts) == 2:
                    code = parts[0].strip()
                    description = parts[1].strip()

                    # Escape double quotes within the description for the Python string
                    description_escaped = description.replace('"', '\\"')

                    funcoes_entries.append(f'    "{code}": "{description_escaped}",')
                else:
                    print(f"Warning: Could not parse line: {line}")

    except FileNotFoundError:
        print(f"Error: Input file '{input_list_file}' not found.")
        return
    except Exception as e:
        print(f"An error occurred while reading '{input_list_file}': {e}")
        return

    if not funcoes_entries:
        print("No valid entries found in the input file.")
        return

    try:
        with open(output_py_file, 'w', encoding='utf-8') as f_out:
            f_out.write("# funcoes_map.py\n")
            f_out.write("FUNCOES_DICT = {\n")
            for entry in funcoes_entries:
                f_out.write(entry + "\n")
            f_out.write("}\n")
        print(f"Successfully created '{output_py_file}' with {len(funcoes_entries)} entries.")
    except Exception as e:
        print(f"An error occurred while writing to '{output_py_file}': {e}")

if __name__ == "__main__":
    # --- START OF FILE Funções_LIST.txt --- (Simulated content for testing)
    # This part is just for demonstration. In reality, you'll have this file separately.
    simulated_content = """
146 - ACOMPANHAMENTO DE EGRESSOS
474 - ACOMPANHAMENTO DE OBRAS
717 - AFASTAMENTO PREVENTIVO
626 - ALFABETIZAÇÃO E FAMÍLIA
469 - ANALISTA
480 - APOIO DE  ENSINO A DISTÂNCIA
653 - ARQUIVAMENTO E CONTROLE DE COORRESPONDÊNCIAS
467 - CASA DE ARTE  DE APARECIDA DE GOIANIA
044 - PROFESSOR DE ATENDIMENTO EDUCACIONAL ESPECIALIZADO
141 - DUPLA PEDAGOGICA
036 - PROFESSOR DE 2ª FASE OU ENSINO MÉDIO
001 - GESTOR ESCOLAR
532 - INTÉRPRETE DE LÍNGUA INDÍGENA
    """ # Add a few more diverse examples
    # Create a dummy Funções_LIST.txt for testing if it doesn't exist
    try:
        with open("Funções_LIST.txt", "r") as f:
            pass # File exists
    except FileNotFoundError:
        with open("Funções_LIST.txt", "w", encoding="utf-8") as f:
            f.write(simulated_content)
        print("Created a sample 'Funções_LIST.txt' for testing.")
    # --- END OF FILE Funções_LIST.txt ---

    create_funcoes_dict_file()