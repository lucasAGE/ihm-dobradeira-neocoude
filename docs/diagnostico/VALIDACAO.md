# Validação do kit de diagnóstico

Este documento registra a entrega inicial 0.1.0. Para a ampliação 0.2.0, com
26 testes Python, 8 de feedback e monitor de recepção, veja
[FEEDBACK.md](FEEDBACK.md#validação-desta-ampliação).

Data: 09/11/2026. Ambiente: Windows com Python 3.14.7 e Windows PowerShell 5.1;
Ubuntu/WSL x86_64 com Python 3.14.4; Chromium headless instalado.
Não houve instalação/atualização de dependências. Raspberry/ARM, CLP, barramento
físico, fonte DC-DC, SD real e comportamento de parada **não foram testados**.

## Verificações executadas

| Comando / procedimento | Resultado |
|---|---|
| `python -m unittest discover -s diagnostics/tests -v` | 18 testes aprovados no Windows |
| `wsl -d Ubuntu --cd /mnt/e/Dev/Neocoude -- python3 -m unittest discover -s diagnostics/tests -v` | 18 descobertos: 17 aprovados, 1 explicitamente ignorado por exigir Windows PowerShell |
| `node --check diagnostics/panel/panel.js` | Sintaxe JavaScript válida |
| `Management.Automation.Language.Parser::ParseFile` sobre `diagnostics/Test-Neocoude.ps1` | Sem erros de parsing; execução real em PowerShell 5.1 coberta pela integração |
| `ast.parse(..., feature_version=(3,9))` para os 8 arquivos Python do kit | Sintaxe compatível com 3.9; não substitui teste de execução em cada versão/ARM |
| `node diagnostics/tests/check_panel.cjs <Chromium instalado> diagnostics/output` | Arquivo local, importação/merge/exportação, desconhecidos, conteúdo malicioso inerte, JSON não suportado, desktop 1360px e mobile 390px aprovados; sem requisições HTTP/WS externas ou exceções JavaScript |
| Inspeção da captura de tela do painel | Layout desktop legível; teste de overflow também passou em desktop/mobile |
| `python3 diagnostics/collect_linux.py --app-root /mnt/e/Dev/Neocoude/ihm_esp32 --output ...` no WSL | JSON gerado; `is_raspberry_pi=false`, modelo/temperatura/flags indisponíveis permanecem desconhecidos; ferramentas Linux ausentes não causaram falha global |
| `python diagnostics/artifacts.py inventory --root ihm_esp32 --label repo-0c720f5 --output ...` | Manifesto de seis camadas criado, sem inventar OS/Ladder/imagem instalados |
| Mesmo inventário com `--snapshot diagnostics/output/linux-wsl-validation.json` | Comparação encontrou os sete arquivos selecionados com bytes idênticos; é o mesmo checkout via WSL, não comparação com a máquina |
| `python diagnostics/analyze_modbus.py diagnostics/examples/capture-synthetic.jsonl --output ...` | 2 transações sintéticas: 1 válida e 1 timeout; latência 25 ms da fixture; taxa de sucesso desconhecida por haver uma única leitura válida |
| `git diff --check` e `git diff --no-index --check -- NUL <cada arquivo novo>` | Sem problemas de whitespace nos arquivos avaliados |
| Revisão do diff e das chamadas de I/O | Alteração em arquivo existente restrita ao aviso/link no README; kit e documentação adicionados; runtime, Ladder, dependências e serviços preservados |

O teste de navegador usa perfil temporário separado, sem tocar o navegador do
usuário. Capturas e relatórios locais ficam ignorados em `diagnostics/output`.
As telas de teste indicam **SIMULAÇÃO** e não devem ser apresentadas como coleta
da dobradeira. O painel entregue inicia sem dados e sem conexão.

## Cobertura relevante

- Limites de saída e timeout de processos, ferramenta ausente, redação básica de
  segredos, recusa de sobrescrever evidência, CPU sem dupla contagem de guest e
  atividade passiva de disco em setores de 512 bytes.
- Flags atuais versus históricas de throttling/subtensão.
- CRC conhecido, corrupção de resposta, slave/função divergentes, tamanho,
  exceção Modbus, timeout e timestamp invertido; taxa separa resposta válida de
  falha; entrada que não seja arquivo regular é rejeitada.
- Backup/verify/restore em diretório temporário, conteúdo idêntico, destino
  existente preservado, corrupção/travessia de caminho rejeitadas antes de extrair.
- Windows com HTTP e WS reais **em loopback**, mensagens fragmentadas e delta,
  JSON inválido, porta fechada e duração limitada. Servidor simulado confirmou
  zero payload de aplicação enviado pelo coletor.
- Quatro reproduções de defeitos/limitações do runtime: mudança perdida no delta,
  mudança no conjunto de clientes, contador avançando com leitura falha, e eco de
  registrador interpretado como confirmação de ângulo. Métodos extraídos por AST
  usam dependências simuladas; nenhuma inicialização do runtime foi executada.

## Falhas encontradas durante a implementação e resolvidas

A primeira execução (16 testes) teve uma falha na fixture de auditoria porque
prints Unicode do código legado não cabiam no stdout CP1252 do Windows; o teste
passou a capturar/suprimir esses prints, sem alterar o runtime. Uma execução
posterior (17 testes) encontrou timeout antes da recusa TCP em loopback; a janela
da fixture foi ajustada para 4 s, preservando a distinção timeout/refused do kit.
O teste específico Windows então detectou que o retorno `VoidTaskResult` da
conexão WS poluía a saída da função PowerShell; a implementação agora descarta
explicitamente esse retorno. O teste Windows foi repetido e aprovado, seguido
pela suíte completa e execução Linux acima.

Essas falhas foram de fixture/implementação do kit, não medições da máquina.
Não se executou `pytest`/descoberta global: scripts históricos podem escrever no
CLP. Não houve benchmark, stress, fsck, abertura da serial, alteração de Ladder,
restart de serviços, deploy, geração de imagem, commit ou push.
