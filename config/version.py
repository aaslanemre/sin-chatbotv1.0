# Single source of truth for the app version (user sidebar, admin sidebar, feedback rows).
APP_VERSION = "v6.5.0"

# "Novidades da versão" banner shown once per version per user (users.last_seen_version).
# PT-BR, user-facing. Entries marked DRAFT must be reviewed before deploy.
RELEASE_NOTES = {
    "v6.5.0": {
        "status": "DRAFT — review before deploy",
        "novidades": [
            "As respostas às perguntas livres agora aparecem enquanto são escritas.",
            "O selo de confiança está em português: 🟢 Baseado nos documentos, "
            "🟡 Parcialmente baseado nos documentos ou 🔴 Conhecimento geral.",
            "Em “Fontes consultadas”, cada documento aparece uma vez, com a melhor "
            "relevância, o número de trechos e os trechos usados.",
            "Os blocos gerados (BESS, STATCOM, contingências e rede completa) podem "
            "ser baixados como arquivo .pwf pronto para o ANAREDE.",
            "Avaliação com um clique: 👍 ou 👎 em cada resposta; depois do 👎 você "
            "pode contar o que deu errado.",
            "Mensagens do guia mais curtas: explicações extras ficam em “Detalhes”.",
            "Nas etapas de escolha, basta clicar na opção; nas etapas numéricas, "
            "um formulário com unidades e validação. Digitar continua funcionando.",
            "Painel “Estudo atual” na barra lateral: progresso, parâmetros escolhidos "
            "e ✏️ para corrigir um valor sem recomeçar.",
            "“Minhas conversas”: reveja suas conversas anteriores, inclusive no celular.",
            "Modo iniciante / especialista e um 📖 Glossário com os termos do ANAREDE.",
        ],
        "o_que_testar": [
            "Faça uma pergunta livre e confira o selo, as fontes e o texto completo.",
            "Rode uma simulação BESS usando só os botões e formulários.",
            "Baixe o .pwf gerado e carregue no ANAREDE.",
            "No meio do fluxo, use ✏️ para trocar a barra ou a base de dados.",
            "Abra “Minhas conversas” no celular.",
            "Alterne entre modo iniciante e especialista e compare as mensagens.",
        ],
    },
}
