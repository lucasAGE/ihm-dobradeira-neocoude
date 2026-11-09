# Validação do roteiro de campo — revisão r1

09/11/2026, America/Sao_Paulo. Preparação solicitada para futura conexão à
`IHM_NEOCOUDE`. O backend e a tela 0.3.0 não foram alterados nesta etapa.
Não havia `AGENTS.md`/`AGENTS.override.md` aplicável, conforme a auditoria do projeto.

Entregas: [roteiro](ATUALIZACAO_EM_CAMPO.md), [ficha](FICHA_ATUALIZACAO.md),
`diagnostics/check_release.py`, `diagnostics/releases/feedback-0.3.0.json`,
`diagnostics/build_field_package.py` e [prompt para o notebook](PROMPT_NOTEBOOK.txt).
O comparador lê oito arquivos, não importa a IHM, não abre serial e não altera
serviços ou a aplicação. Seu manifesto fixa a base auditada e o candidato local.

| Comando/verificação executada | Resultado |
|---|---|
| `python -m unittest diagnostics.tests.test_release_check -v` | 7 aprovados; 1 teste de criação de symlink ignorado por falta de suporte/permissão no Windows |
| `wsl -d Ubuntu --cd /mnt/e/Dev/Neocoude -- python3 -m unittest diagnostics.tests.test_release_check -v` | 8 aprovados, incluindo symlink |
| `python -m unittest discover -s diagnostics/tests -v` | 44 encontrados: 43 aprovados, 1 symlink ignorado |
| `python -m unittest diagnostics.tests.test_field_package -v` | 2 aprovados: pastas exclusivas, checksums, exclusão de evidências privadas e recusa de versão divergente |
| `python diagnostics/build_field_package.py` | Pacote gerado e verificado localmente; nenhuma conexão ou implantação |
| Exportação dos arquivos preparados para commit com `git archive`, seguida de geração em pasta temporária | 46 arquivos, prompt incluído e hashes verificados; nenhum ZIP ou relatório local necessário |
| `python diagnostics/check_release.py --installed-root ihm_esp32 --expect candidate --output diagnostics/output/release-local-0.3.0-r1.json` | `source_state=candidate`, `matches_expected=true`; oito arquivos locais conferidos |
| `wsl -d Ubuntu --cd /mnt/e/Dev/Neocoude -- python3 diagnostics/tests/check_field_procedure.py` | 14 blocos Bash com sintaxe válida; troca/recuperação exercitadas em diretório temporário |
| Parser PowerShell nos sete blocos do roteiro | Sem erros de sintaxe; blocos remotos não executados |
| `ast.parse(..., feature_version=(3,9))` nos três novos scripts Python | Sintaxe aceita; não é teste de execução em Python 3.9/ARM |
| `Get-Command ssh,scp,curl.exe,python -ErrorAction Stop` | Quatro ferramentas presentes no notebook |
| `install --help` e `systemctl --help` no WSL | Opções usadas pelo roteiro conferidas localmente |
| `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check` | Sem erros, considerando o CRLF previamente versionado |

O ensaio usa a função `neo_copy_three` extraída literalmente do roteiro. Substitui
`systemctl` e `sudo` por funções de teste: nenhuma unidade é parada/iniciada.
O `install` real copia somente arquivos temporários. São verificados:

- recusa quando o serviço simulado está ativo;
- backup e extração com verificação dos hashes;
- atualização conjunta dos três arquivos e comparação com o candidato;
- detecção de arquivo ausente após uma interrupção simulada;
- recuperação dos bytes, dono, grupo e modo a partir do backup e metadados reais
  do fixture, inclusive modo original 0640 após staging restrito a 0600.

A primeira conferência do manifesto recusou arquivos de contexto que diferiam
apenas em CRLF/LF entre Git e checkout Windows. O comparador foi corrigido para
permitir exclusivamente essa normalização, e ganhou teste de regressão. Uma
asserção de teste inicialmente colocada no método errado também foi corrigida;
todas as execuções finais acima passaram. Nenhuma diferença de código foi ignorada.

Os testes de navegador/JavaScript e backend da entrega anterior permanecem
registrados em [CORRECAO_FEEDBACK.md](CORRECAO_FEEDBACK.md). Não foi repetido o
teste de navegador porque os arquivos de frontend não mudaram nesta etapa.

O pacote `neocoude-campo-feedback-0.3.0-r1.zip` reúne ferramentas, documentos e
oito referências da aplicação. Os cinco arquivos de contexto servem para
comparação; a instalação prevista copia somente os três arquivos corrigidos.
`SHA256SUMS-campo-0.3.0-r1.txt` acompanha o pacote e os três scripts necessários
para verificar/extrair antes de acessar as ferramentas internas.
O gerador recria esse conjunto após o `git pull`, em uma pasta nova, sem depender
dos ZIPs locais ignorados pelo Git. Os oito arquivos de referência precisam
corresponder ao candidato antes da geração; relatórios de `diagnostics/output`
não são incluídos.

**Não realizado:** conexão SSH/SCP à máquina, parada/reinício real de serviço,
instalação no Raspberry, mudança de configuração ou teste físico de sensores,
encoder, parada e proteções. A identificação e os ensaios no equipamento ficam
para a execução do roteiro no local.
