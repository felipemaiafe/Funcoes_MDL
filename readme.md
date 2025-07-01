# Analisador de Funções MDL de PDF

Uma aplicação de desktop desenvolvida em Python com Tkinter para analisar arquivos PDF que contêm relatórios de consulta, extraindo e agregando "Funções" (cargos ou papéis) por ano.

O programa foi projetado para processar um único arquivo PDF que pode conter múltiplos relatórios individuais concatenados. Ele identifica o início de cada novo relatório, extrai o ano da "Data Consulta" e coleta todos os códigos de função de 3 dígitos associados a esse relatório. No final, apresenta um resumo consolidado de todas as funções encontradas, organizadas por ano.

## Funcionalidades Principais

- **Interface Gráfica Simples:** Interface intuitiva criada com Tkinter para facilitar a seleção e análise dos arquivos.
- **Processamento de Múltiplos Relatórios:** Identifica e processa de forma inteligente múltiplos relatórios que foram juntados em um único arquivo PDF.
- **Agregação por Ano:** Extrai o ano de cada relatório e agrupa os códigos de função encontrados, evitando duplicatas para cada ano.
- **Mapeamento de Códigos:** Utiliza um dicionário (`funcoes_map.py`) para traduzir os códigos numéricos de 3 dígitos para suas descrições completas.
- **Consulta Rápida:** Permite ao usuário consultar a descrição de um código de função específico diretamente na interface.
- **Processamento Assíncrono:** A análise do PDF é executada em uma thread separada para não travar a interface gráfica, com uma barra de progresso para feedback visual.
- **Log Detalhado:** Exibe um log em tempo real do processo de extração, útil para depuração e para entender como o arquivo está sendo lido.
- **Exportação de Resultados:** Permite salvar o resultado agregado em um arquivo de texto (`.txt`).

## Pré-requisitos

- Python 3.x
- A biblioteca `pdfplumber`

## Instalação

1.  Clone este repositório para sua máquina local:
    ```bash
    git clone https://github.com/seu-usuario/seu-repositorio.git
    ```
2.  Navegue até o diretório do projeto:
    ```bash
    cd seu-repositorio
    ```
3.  Instale a dependência necessária:
    ```bash
    pip install pdfplumber
    ```
4.  Certifique-se de que o arquivo `funcoes_map.py` está no mesmo diretório que `pdf_parser.py`.

## Como Usar

1.  Execute o script principal:
    ```bash
    python pdf_parser.py
    ```
2.  Na janela que se abrir, clique em **"Selecione o PDF"** para escolher o arquivo que deseja analisar.
3.  O caminho do arquivo aparecerá no campo de texto. Clique em **"Analisar PDF"**.
4.  Aguarde o processamento. A barra de progresso indicará o andamento e o log mostrará detalhes da extração.
5.  Ao final, os resultados serão exibidos no painel superior, agregados por ano.
6.  (Opcional) Para salvar os resultados, clique no botão **"Salvar Resultados"**.
7.  (Opcional) Para consultar um código, digite-o no campo "Código" e clique em "Consultar" ou pressione Enter.

## Estrutura do Projeto

```
/
├── pdf_parser.py       # Script principal da aplicação com a lógica e a GUI
├── funcoes_map.py      # Dicionário de mapeamento dos códigos para descrições
├── LICENSE             # Arquivo de licença do projeto
└── README.md           # Este arquivo
```

## Licença

Este projeto está licenciado sob a Licença MIT. Veja o arquivo [LICENSE] para mais detalhes.