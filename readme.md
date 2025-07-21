# Analisador de Funções (MDL + MAINFRAME)

Uma aplicação de desktop desenvolvida em Python para automatizar a coleta e consolidação de históricos de funções de servidores. O programa extrai dados de relatórios PDF (MDL) e de um dashboard Power BI (MAINFRAME), mesclando as informações para criar um relatório cronológico completo e sem duplicatas.

O objetivo é resolver o problema de dados históricos ausentes nos relatórios PDF mais recentes, complementando-os com informações extraídas via web scraping do sistema MAINFRAME.

## Funcionalidades Principais

- **Interface Gráfica Intuitiva:** Criada com Tkinter para um fluxo de trabalho simples: selecionar arquivo, inserir credenciais e analisar.
- **Dupla Fonte de Dados:**
    - **Análise de PDF (MDL):** Processa de forma inteligente múltiplos relatórios contidos em um único arquivo PDF.
    - **Web Scraping (MAINFRAME):** Utiliza Selenium em modo headless para fazer login no portal da Intranet, navegar até o dashboard Power BI de Aposentadoria e extrair o histórico de funções.
- **Fusão Inteligente de Dados:**
    - **Priorização:** Dados extraídos do PDF (MDL) têm prioridade sobre os do MAINFRAME.
    - **De-duplicação:** O relatório final exibe apenas uma entrada por código de função em um mesmo ano, evitando redundância.
- **Ordenação Cronológica:** Os resultados de cada ano são ordenados pela data exata da ocorrência, combinando as fontes de forma cronológica.
- **Normalização de Dados:** Códigos de função do MAINFRAME (ex: `36`) são automaticamente formatados para o padrão de 3 dígitos (ex: `036`) para consistência.
- **Gerenciamento Automático do ChromeDriver:** A biblioteca `webdriver-manager` cuida da instalação e atualização do driver do navegador, simplificando a execução.
- **Processamento Assíncrono:** A análise e o scraping são executados em uma thread separada para manter a interface gráfica responsiva, com uma barra de progresso para feedback visual.
- **Log Detalhado:** Exibe um log em tempo real do processo, essencial para depuração e para acompanhar o status da automação.
- **Consulta Rápida de Funções:** Permite consultar a descrição de qualquer código de função diretamente na interface.
- **Exportação de Resultados:** O relatório final consolidado pode ser editado e salvo como um arquivo de texto (`.txt`).

## Pré-requisitos

- Python 3.8+
- As bibliotecas listadas no arquivo `requirements.txt`.

## Instalação

1.  Clone este repositório para sua máquina local.
2.  Navegue até o diretório do projeto.
3.  É altamente recomendável criar e ativar um ambiente virtual:
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```
4.  Instale as dependências:
    ```bash
    pip install -r requirements.txt
    ```

## Como Usar

1.  Execute o script principal:
    ```bash
    python pdf_parser.py
    ```
2.  Na janela da aplicação, clique em **"Selecione o PDF"** para escolher o arquivo de modulações.
3.  Nos campos **"MAINFRAME Login"**, insira seu usuário e senha de acesso à Intranet.
4.  O botão **"PROCURAR FUNÇÕES"** será habilitado. Clique nele para iniciar o processo.
5.  Aguarde a conclusão. A barra de progresso e o log indicarão o andamento das duas etapas (Scraping e Análise de PDF).
6.  Ao final, os resultados consolidados aparecerão no painel superior. Este campo é editável caso precise fazer ajustes manuais.
7.  Clique em **"SALVAR RESULTADOS"** para exportar o relatório para um arquivo `.txt`.

## Estrutura do Projeto

```
/
├── pdf_parser.py       # Script principal da aplicação com a lógica e a GUI
├── funcoes_map.py      # Dicionário de mapeamento dos códigos para descrições
├── requirements.txt    # Lista de dependências Python para o projeto
└── README.md           # Este arquivo
```

## Licença

Este projeto está licenciado sob a Licença MIT. Veja o arquivo [LICENSE] para mais detalhes.