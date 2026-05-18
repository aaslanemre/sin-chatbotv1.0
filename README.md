# Assistente RAG — Sistema Interligado Nacional (SIN)

Chatbot conversacional especializado em estudos de planejamento e operação
do SIN, com RAG sobre documentos técnicos (ONS, EPE, CEPEL).

## Requisitos

- Python 3.10+
- Docker + Docker Compose (para o Qdrant e n8n)
- Ollama instalado localmente

## Setup

### 1. Iniciar o Qdrant
```bash
docker-compose up -d
```

### 2. Instalar dependências Python
```bash
pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente
```bash
cp .env.example .env
# edite .env com seus modelos Ollama preferidos
```

### 4. Baixar modelos no Ollama
```bash
ollama pull llama3
ollama pull nomic-embed-text
```

### 5. Adicionar documentos PDF
Coloque os PDFs na pasta `docs/`:
- Relatórios PAR/PEL do ONS
- PDE da EPE
- Manuais ANAREDE e ANATEM
- Relatórios técnicos internos

### 6. Indexar os documentos
```bash
python -m rag.ingestor
```

### 7. Iniciar o chatbot
```bash
streamlit run app.py
```

## Uso

- **Chat**: Digite perguntas técnicas sobre o SIN na caixa de texto
- **Upload PWF**: Use a barra lateral para carregar arquivos de cenário `.pwf`
- **Fontes**: Cada resposta mostra os documentos consultados
- **Limpar conversa**: Botão na barra lateral reinicia o histórico

## Adicionar novos documentos

1. Coloque o novo PDF em `docs/`
2. Execute novamente: `python -m rag.ingestor`
3. Os novos documentos são adicionados à coleção existente

---

## Instâncias n8n

| Instância       | URL                         | Descrição                                    |
|-----------------|-----------------------------|----------------------------------------------|
| Existente (RAG) | http://localhost:5678        | Instância principal — **não modificar**      |
| SIN Chatbot     | http://localhost:5679        | Instância isolada para este projeto          |

### Gerenciar n8n do SIN Chatbot

```bash
# Iniciar
docker-compose -f docker-compose.n8n.yml up -d

# Parar (somente esta instância)
docker-compose -f docker-compose.n8n.yml down

# Logs
docker logs n8n_sin_chatbot
```

> **Atenção**: nunca execute `docker-compose down` sem a flag `-f docker-compose.n8n.yml`,
> pois isso pode afetar outros serviços.

---

## Estrutura futura (próximas versões)
- [ ] Integração com flowcharts de decisão para guiar estudos
- [ ] Troca de Ollama por Claude API (Anthropic)
- [ ] Parser de arquivos .pwf para extração de dados de cenário
- [ ] Exportação de relatório de estudo em PDF
