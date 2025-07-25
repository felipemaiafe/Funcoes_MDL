# Analisador de Funções (MDL + MAINFRAME)

Uma aplicação de desktop desenvolvida em Python para automatizar a coleta e consolidação de históricos de funções de servidores. O programa extrai dados de relatórios PDF (MDL) e de um dashboard Power BI (MAINFRAME), mesclando as informações para criar um relatório cronológico completo, limpo e com anotações inteligentes.

O objetivo é resolver o problema de dados históricos ausentes nos relatórios PDF, complementando-os com informações do sistema MAINFRAME e aplicando uma série de regras de negócio para gerar um documento final pronto para análise.

## Funcionalidades Principais

- **Interface Gráfica Intuitiva:** Criada com Tkinter para um fluxo de trabalho simples: selecionar arquivo, inserir credenciais e analisar. A janela inicia maximizada para melhor visualização dos resultados.
- **Dupla Fonte de Dados:**
    - **Análise de PDF (MDL):** Processa de forma inteligente múltiplos relatórios contidos em um único arquivo PDF, lidando com diferentes layouts e extraindo corretamente funções de tabelas variadas, inclusive em múltiplas páginas.
    - **Web Scraping (MAINFRAME):** Utiliza Selenium para fazer login, navegar até o dashboard Power BI e extrair o histórico de funções, incluindo os intervalos de datas de cada registro.
- **Relatório Inteligente e Consolidado:**
    - **Consolidação de Períodos:** Agrupa múltiplas entradas idênticas dentro de um mesmo ano em uma única linha, combinando seus intervalos de datas para exibir o período completo (da data mais antiga à mais recente).
    - **Linha do Tempo Contínua:** Garante que todos os anos entre o primeiro e o último registro sejam exibidos, inserindo linhas de placeholder (-------) para anos sem dados.
    - **Harmonização de Lotação:** Padroniza os nomes das lotações. Compara os nomes do MAINFRAME com a base de dados para encontrar o código MDL correspondente. Durante o ano de transição (2014), prioriza o código MDL quando os nomes de lotação são idênticos.
    - **Filtro por Data de Início:** Ignora automaticamente todos os registros de anos anteriores à data de início do cargo do servidor, limpando o relatório de dados irrelevantes.
    - **Alertas Visuais:** Adiciona uma anotação <- Pedir Frequência ao lado de registros que exigem atenção, como:
        - Anos sem nenhum registro (placeholder).

        - Funções do tipo Administrativo.

        - Funções de Magistério (fonte MDL) com duração inferior a 244 dias.
    - **Notas de Rodapé Dinâmicas:** Identifica "Funções Especiais" (ex: 109, 140) e adiciona um rodapé ao relatório listando todas que foram encontradas.
- **Segurança e Configuração:**
    - **Gerenciamento de Credenciais:** As credenciais do banco de dados são lidas de um arquivo config.ini local, que é ignorado pelo Git (.gitignore), garantindo que nenhuma informação sensível seja enviada para o repositório.
- **Recursos Adicionais:**
    - **Processamento Assíncrono:** A análise e o scraping rodam em uma thread separada para manter a interface responsiva.
    - **Log Detalhado:** Exibe um log em tempo real do processo para depuração e acompanhamento.
    - **Consulta Rápida de Funções:** Permite consultar a descrição de qualquer código de função diretamente na interface.
    - **Exportação de Resultados:** O relatório final pode ser editado na própria aplicação e salvo como um arquivo de texto (.txt).

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
5.  **Crie o arquivo de configuração:**
    - Faça uma cópia do arquivo config.ini.example e renomeie-a para config.ini.
    - Abra o config.ini e preencha com suas credenciais reais de acesso ao banco de dados. Este arquivo não será monitorado pelo Git.

## Como Usar

1.  Execute o script principal:
    ```bash
    python pdf_parser.py
    ```
2.  Na janela da aplicação, clique em **"Selecione o PDF"** para escolher o arquivo de modulações.
3.  Nos campos **"MAINFRAME Login"**, insira seu usuário e senha de acesso à Intranet.
4.  O botão **"PROCURAR FUNÇÕES"** será habilitado. Clique nele para iniciar o processo.
5.  Aguarde a conclusão. A barra de progresso e o log indicarão o andamento das duas etapas.
6.  Ao final, os resultados consolidados aparecerão no painel superior. Este campo é editável caso precise fazer ajustes manuais.
7.  Clique em **"SALVAR RESULTADOS"** para exportar o relatório para um arquivo `.txt`.

## Estrutura do Projeto

```
/
├── pdf_parser.py           # Script principal da aplicação com a lógica e a GUI
├── db_utils.py             # Funções para interagir com o banco de dados
├── config.ini              # (Local) Arquivo com as credenciais do banco de dados. Ignorado pelo Git.
├── config.ini.example      # Arquivo de exemplo para a configuração
├── requirements.txt        # Lista de dependências Python para o projeto
├── .gitignore              # Arquivo que especifica o que o Git deve ignorar
└── README.md               # Este arquivo
```

## Licença

Este projeto está licenciado sob a Licença MIT. Veja o arquivo [LICENSE] para mais detalhes.