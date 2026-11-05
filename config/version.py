# Single source of truth for the app version (user sidebar, admin sidebar, feedback rows).
APP_VERSION = "v6.6.1"

# "Novidades da versão" banner shown once per version per user (users.last_seen_version).
# PT-BR, user-facing. Entries marked DRAFT must be reviewed before deploy.
RELEASE_NOTES = {
    "v6.6.1": {
        "status": "DRAFT — review before deploy",
        "novidades": [
            "Caso pequeno no ANATEM: se você ainda não tem um .SAV e um .STB, o guia mostra como "
            "começar pelo caso de exemplo de 9 barras (9BARRAS.PWF) da instalação do ANAREDE.",
            "Equipamentos opcionais no ANATEM: escolha “Estudo convencional” para seguir sem "
            "BESS/STATCOM/HVDC, ou “Incluir BESS/STATCOM/HVDC”.",
            "Passo 5 (edição do .stb): instruções corrigidas — o .SAV e o DMAQ são trocados no "
            "cartão DARQ.",
            "Passo 8: como executar a simulação (menu Simulação > Executar ou a tecla F5).",
            "Eventos (DEVT): menu com curto-circuito, perda de linha, desligamento de unidade "
            "geradora e rejeição de carga.",
        ],
        "o_que_testar": [
            "Caso pequeno: responda “Não tenho / quero um caso de exemplo” e siga a orientação.",
            "Estudo convencional, sem equipamentos, até o fim do fluxo.",
            "O texto do passo 5 (cartão DARQ).",
            "O passo 8 (Simulação > Executar / F5).",
            "O menu de eventos: escolha pelo botão, pelo número e pelo nome.",
        ],
    },
    "v6.6.0": {
        "status": "DRAFT — review before deploy",
        "novidades": [
            "Novo fluxo guiado para o ANATEM (estabilidade eletromecânica): ANAT0, DMAQ, .stb, "
            "simulação sem eventos, erros de CDU, verificação no PLOTCEPEL e eventos (DEVT). "
            "O guia indica o que fazer; ele não gera arquivos do ANATEM.",
            "Dois botões na barra lateral: “⚡ Iniciar simulação ANAREDE” e “🌀 Iniciar simulação "
            "ANATEM”. Com uma simulação em andamento, o app pede confirmação antes de encerrá-la.",
            "Quando você pede uma simulação sem dizer o programa, o app pergunta: ANAREDE ou ANATEM?",
            "Ao final de um estudo no ANAREDE (BESS, STATCOM ou rede própria), o botão "
            "“🌀 Continuar para o ANATEM” leva o estudo para o ANATEM, mantendo a base escolhida.",
        ],
        "o_que_testar": [
            "Fluxo ANATEM com a base ONS, do começo ao fim.",
            "Caminho do caso pequeno / rede própria (opção 3, sem ANAT0).",
            "Erro de CDU: o ramo do regulador de velocidade (GOV) e o do regulador de tensão (AVR).",
            "Handoff: termine um estudo de BESS e clique em “🌀 Continuar para o ANATEM”.",
            "Os botões da barra lateral com uma simulação ativa (e com uma pausada).",
        ],
    },
    "v6.5.1": {
        "status": "DRAFT — review before deploy",
        "novidades": [
            "Arquivos .pwf: nenhum valor numérico passa de 4 casas decimais nem da largura "
            "do campo; a linha de acoplamento da BESS usa a menor reatância diferente de "
            "zero que cabe nesse limite.",
            "Na rede montada do zero, a conversão e a tabela de revisão mostram os valores "
            "exatamente como serão gravados no DLIN.",
            "Pedidos como “quero modelar uma BESS” ou “modelar bess” iniciam a simulação guiada.",
            "Perguntas livres no meio da simulação são respondidas sobre o passo atual "
            "(inclusive depois de pausar e retomar).",
            "Sugestões clicáveis com valores usados com frequência (ex: base 100 MVA, "
            "tensões do SIN, circuito 1): o clique só preenche o campo, que continua editável. "
            "Ocultas no modo especialista.",
            "Várias BESS no mesmo estudo (até 10): depois da nova barra, escolha "
            "“Adicionar outra BESS” ou “Gerar arquivo agora”; um único .pwf com todas.",
        ],
        "o_que_testar": [
            "Gere o .pwf de uma BESS e carregue no ANAREDE: o DLIN deve ser aceito sem erro.",
            "Monte uma rede do zero com a linha de 230 kV / 180 km e compare a tabela com o arquivo.",
            "Digite “quero modelar uma bess” e “como modelar uma BESS no ANAREDE?” e compare.",
            "No passo de carregar o SAV, pergunte “não acho essa opção, como encontrar?”.",
            "Na rede do zero, use as sugestões (sugestão) e altere um valor antes de enviar.",
            "Insira 2 ou 3 BESS (inclusive duas na mesma barra), use ✏️ em uma delas, "
            "pause, saia, entre de novo e gere o arquivo.",
        ],
    },
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
