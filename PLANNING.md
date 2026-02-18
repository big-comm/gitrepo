# PLANNING.md — Auditoria e Roadmap do GitRepo (build-package)

> Gerado em: 2025 | Ferramenta: ruff, análise AST, revisão manual  
> Escopo: `usr/share/build-package/` — 38 arquivos Python (~17.000 linhas)  
> **Última atualização:** Sprints 1–4 + UX/SEG/DT CONCLUÍDAS. Erros ruff: 123 → **0**. `build_package.py`: 2832 → **1250** linhas (−56%). `settings_dialog.py` removido (−279L). `show_error_dialog` via `Adw.AlertDialog`.

---

## Status de Implementação

| Item | Status |
|---|---|
| BUG-01: `import os` em `main_window.py` | ✅ CONCLUÍDO |
| BUG-02: `ours_file_abs`/`theirs_file_abs` em `conflict_resolver.py` | ✅ CONCLUÍDO |
| BUG-03: `run_async_operation` assíncrono real | ✅ CONCLUÍDO |
| SEG-03: `os.system('clear')` → `subprocess.run(['clear'])` | ✅ VERIFICADO/CORRETO |
| SEG-04: Token exposto em logs | ✅ AUDITADO/SEGURO |
| SEG-05: `timeout=30` em todas as requisições HTTP | ✅ CONCLUÍDO |
| SEG-06: Remoção do token legado `~/.GITHUB_TOKEN` | ✅ CONCLUÍDO |
| SEC-02: `chmod 600` no arquivo de token | ✅ JÁ CORRETO |
| ARQ-04: `pyproject.toml` com `per-file-ignores` para E402 | ✅ CONCLUÍDO |
| QC-01: 18+ bare excepts → exceções específicas | ✅ CONCLUÍDO |
| QC-02: f-strings sem placeholders corrigidas | ✅ CONCLUÍDO |
| QC-03: imports não utilizados removidos | ✅ CONCLUÍDO |
| QC-04: variável `l` ambígua renomeada | ✅ CONCLUÍDO |
| QC-05: variáveis `success`/`e` não usadas removidas | ✅ CONCLUÍDO |
| QC-06: loop var `_` shadow → `_dirs` em `git_utils.py` | ✅ CONCLUÍDO |
| A11Y-01: label acessível no botão de excluir token | ✅ CONCLUÍDO |
| A11Y-02: tooltips em botões icon-only | ✅ JÁ CORRETO |
| A11Y-04: AT-SPI para status dinâmico | ✅ CONCLUÍDO |
| A11Y-06: Navegação por teclado na sidebar | ✅ VERIFICADO/CORRETO |
| UX-02: `Adw.AlertDialog` para erros críticos | ✅ CONCLUÍDO |
| UX-03: CSS class `"error"` no toast de erro | ✅ CONCLUÍDO |
| UX-04: `SettingsDialog` consolidado na `PreferencesDialog` | ✅ CONCLUÍDO (−279L) |
| UX-05: Welcome Dialog mostrado apenas uma vez | ✅ VERIFICADO/CORRETO |
| DT-01: `operation_preview.py` — ainda usado | ✅ VERIFICADO (manter) |
| DT-03: TODO implícito em `run_async_operation` | ✅ RESOLVIDO (threading real) |
| ARQ-01: Refatorar `BuildPackage` god class | ✅ CONCLUÍDO (2832 → 1250L, −56%) |
| ARQ-02: Refatorar `MainWindow` monolítico | ✅ CONCLUÍDO (1484L, máx. 104L/método) |
| ARQ-05: Extrair `TokenStore` | ✅ CONCLUÍDO |
| ARQ-03: Funções soltas → classes | ⏳ BAIXA PRIORIDADE (diferido) |
| DT-02: Rename `cli/menu_system.py` | ✅ CONCLUÍDO (`cli/cli_menu.py`) |
| DT-04: `local_builder.py` / `local_config.py` em `build-iso/` | ⏳ FORA DE ESCOPO |



## Índice

1. [Resumo Executivo](#1-resumo-executivo)
2. [Métricas de Qualidade Atual](#2-métricas-de-qualidade-atual)
3. [Bugs Críticos — Correção Imediata](#3-bugs-críticos--correção-imediata)
4. [Segurança](#4-segurança)
5. [Arquitetura](#5-arquitetura)
6. [Qualidade de Código](#6-qualidade-de-código)
7. [UX e GTK4/Adwaita](#7-ux-e-gtk4adwaita)
8. [Acessibilidade (Orca / AT-SPI)](#8-acessibilidade-orca--at-spi)
9. [Dívida Técnica](#9-dívida-técnica)
10. [Roadmap de Refatoração](#10-roadmap-de-refatoração)

---

## 1. Resumo Executivo

O projeto tem uma arquitetura dual (CLI + GUI) bem separada, com lógica de negócio no `core/`. A GUI usa GTK4 + libadwaita corretamente para a maioria dos padrões. No entanto, existem **2 bugs de nome indefinido** que causam `NameError` em runtime, **18 bare excepts** que engolem erros silenciosamente, e a classe `BuildPackage` (2.832 linhas, 46 métodos) constitui uma **god class** que viola SRP.

**Prioridade máxima:** corrigir os bugs F821 (NameError em produção) antes de qualquer outra mudança.

---

## 2. Métricas de Qualidade Atual

| Métrica | Valor |
|---|---|
| Total de arquivos Python | 38 |
| Total de linhas | ~17.061 |
| Erros ruff | 123 |
| Erros auto-corrigíveis | 22 |
| Bugs F821 (NameError em runtime) | 3 |
| Bare excepts (E722) | 18 |
| Funções > 80 linhas | 27 |
| Funções > 300 linhas | 4 |
| Imports não usados (F401) | 9 |
| f-strings sem placeholders (F541) | 9 |

---

## 3. Bugs Críticos — Correção Imediata

### BUG-01: `NameError: os` em `main_window.py` — ✅ CONCLUÍDO

**Arquivo:** [gui/main_window.py](usr/share/build-package/gui/main_window.py#L1813)  
**Erro ruff:** `F821 Undefined name 'os'` (linhas 1813 e 1813)

O módulo `os` é usado mas não importado em `main_window.py`. Qualquer usuário que abrir o diálogo de configuração de URL remota receberá um `NameError` que encerra o fluxo silenciosamente ou causa crash.

**Correção:** Adicionar `import os` na seção de imports padrão no topo do arquivo.

```python
# Linha ~8 de main_window.py, após "import gi"
import os
```

---

### BUG-02: `NameError: ours_file / theirs_file` em `conflict_resolver.py` — ✅ CONCLUÍDO

**Arquivo:** [core/conflict_resolver.py](usr/share/build-package/core/conflict_resolver.py#L907)  
**Erro ruff:** `F821 Undefined name 'ours_file'` (L907) e `F821 Undefined name 'theirs_file'` (L908)

No método `_keep_both_versions()`, as variáveis `ours_file` e `theirs_file` são referenciadas nas mensagens de log mas nunca foram definidas. As variáveis definidas são `ours_file_abs` e `theirs_file_abs`. Isso causa `NameError` sempre que o usuário escolhe "keep both versions" na resolução de conflitos.

**Correção:**
```python
# Antes (linhas ~907-908):
self.logger.log("cyan", f"  - {ours_file} (our version)")
self.logger.log("cyan", f"  - {theirs_file} (remote version)")

# Depois:
self.logger.log("cyan", f"  - {ours_file_abs} (our version)")
self.logger.log("cyan", f"  - {theirs_file_abs} (remote version)")
```

---

### BUG-03: `run_async_operation` é síncrono — ✅ CONCLUÍDO

**Arquivo:** [gui/main_window.py](usr/share/build-package/gui/main_window.py#L2210)

O método `run_async_operation()` tem comentário `# For now, run synchronously` e executa operações longas (pull, push) **na UI thread**, congelando a janela. O `ProgressDialog` usa threading corretamente, mas nem todas as operações passam por ele.

**Impacto:** UI trava durante operações git de longa duração.

---

## 4. Segurança

### SEG-01: Arquivo de token com permissões corretas ✅

O arquivo `~/.config/gitrepo/github_token` é criado com `chmod 600` em `preferences_dialog.py`. Correto.

### SEG-02: Subprocess sem `shell=True` ✅

Nenhuma chamada `subprocess` usa `shell=True` (verificado). Todos os comandos passam listas. Não há risco de injeção de comando.

### SEG-03: `os.system('clear')` com string literal — ✅ VERIFICADO/CORRETO

**Verificação:** `cli/menu_system.py` já usa `subprocess.run(["clear" if os.name == "posix" else "cls"], check=False)`. Nenhuma chamada `os.system` encontrada. Item já resolvido.

### SEG-04: Token exposto em logs — ✅ VERIFICADO/SEGURO

**Auditoria:** Nenhum valor de token aparece em mensagens de log. Logs de token são apenas de orientação ("Token saved to {path}", "GitHub token not configured"). A mascaragem na UI (`tok[:8] + "·····"`) está correta em `preferences_dialog.py`. Nenhum `str(exc)` loga token values.

### SEG-05: Requisições HTTP sem timeout explícito — ✅ CONCLUÍDO

**Arquivo:** [core/github_api.py](usr/share/build-package/core/github_api.py)

Chamadas `requests.get()` / `requests.post()` não definem `timeout=`. Isso pode causar hang indefinido se a API do GitHub não responder. Recomendado adicionar `timeout=30` em todas as chamadas.

### SEG-06: Token file legado não é removido após migração — ✅ CONCLUÍDO

**Arquivo:** [core/github_api.py](usr/share/build-package/core/github_api.py)

A migração copia `~/.GITHUB_TOKEN` para o novo local mas não remove o arquivo original. O token continua exposto no local antigo (fora do diretório de configuração protegido).

**Correção sugerida:** Após cópia bem-sucedida para o novo local, remover o arquivo legado (com aviso ao usuário).

---

## 5. Arquitetura

### ARQ-01: God Class `BuildPackage` — ✅ CONCLUÍDO

**Arquivo:** [core/build_package.py](usr/share/build-package/core/build_package.py)  
**Tamanho:** 2.832 linhas, 1 classe, 46 métodos

A classe `BuildPackage` acumula responsabilidades de:
- Parsing de argumentos CLI
- Lógica de commit
- Lógica de pull/push
- Build de pacotes
- Gerenciamento de branches
- Menus interativos CLI
- Exibição de summaries

Módulos de operações já foram extraídos (`pull_operations.py`, `commit_operations.py`, `package_operations.py`), mas `BuildPackage` ainda contém versões duplicadas/antigas dessas operações.

**Recomendação:** Completar a extração. Os métodos `commit_and_push()` (319 linhas), `commit_and_generate_package()` (336 linhas), e `pull_latest_code_menu()` (232 linhas) devem ser movidos para seus módulos correspondentes.

---

### ARQ-02: `MainWindow` como controlador monolítico — ✅ CONCLUÍDO

**Arquivo:** [gui/main_window.py](usr/share/build-package/gui/main_window.py)  
**Tamanho:** 2.452 linhas, 80 métodos

`MainWindow` conecta sinais de todos os widgets e contém lógica de negócio inline (ex.: `_execute_commit()` com 172 linhas, `_switch_then_commit()` com 302 linhas). Isso viola o padrão MVC/MVP adequado para GTK4.

**Recomendação:** Extrair a lógica de operação para um `Presenter` ou `Controller` dedicado. `MainWindow` deve apenas conectar sinais e delegar.

---

### ARQ-03: Módulos `pull_operations.py`, `commit_operations.py`, `package_operations.py` são funções soltas — BAIXA PRIORIDADE (pendente)

**Arquivos:** [core/pull_operations.py](usr/share/build-package/core/pull_operations.py), [core/commit_operations.py](usr/share/build-package/core/commit_operations.py), [core/package_operations.py](usr/share/build-package/core/package_operations.py)

**Avaliação (2025):** Os módulos recebem `bp` (BuildPackage) como primeiro argumento — são métodos disfarçados de funções. O padrão atual funciona e passou pelos testes de Sprint 4. Convertê-los para classes `CommitOperations(bp)`, `PullOperations(bp)`, `PackageOperations(bp)` traria benefício de organização mas com alto risco de regressão. Diferir para refatoração futura sob cobertura de testes.

---

### ARQ-04: Imports E402 são estruturais — ✅ ACEITO/CONFIGURADO

**Arquivos:** Todos os arquivos GUI (31 ocorrências)

Os imports E402 (module level import not at top) ocorrem porque os arquivos fazem `gi.require_version()` antes dos imports de `gi.repository`. Isso é o padrão correto para GTK/GI e não deve ser tratado como erro. Recomendado adicionar `# noqa: E402` nos comentários ou configurar ruff para ignorar E402 nesses paths.

```toml
# pyproject.toml ou ruff.toml
[tool.ruff.lint.per-file-ignores]
"usr/share/build-package/gui/**/*.py" = ["E402"]
"usr/share/build-package/cli/**/*.py" = ["E402"]
```

---

### ARQ-05: Duplicação de lógica de token — ✅ CONCLUÍDO

A leitura/escrita do arquivo de token existe em:
- `core/github_api.py` — `get_github_token_optional()`
- `gui/dialogs/preferences_dialog.py` — `_read_token_file()`, `_write_token_file()`

São implementações independentes do mesmo parsing `org=token`. Deveria existir uma única classe `TokenStore` no `core/`.

---

## 6. Qualidade de Código

### QC-01: 18 Bare Excepts — ✅ CONCLUÍDO

Distribuição por arquivo:
- `build_package.py`: 7 bare excepts
- `pull_operations.py`: 5 bare excepts
- `conflict_resolver.py`: 5 bare excepts
- `github_api.py`: 1 bare except

**Problema:** Bare excepts capturam `SystemExit`, `KeyboardInterrupt` e erros de programação, tornando depuração impossível e mascarando bugs reais.

**Padrão correto:**
```python
# Antes
try:
    ...
except:
    pass

# Depois — especificar a exceção esperada
try:
    ...
except (subprocess.CalledProcessError, OSError) as e:
    logger.warning(f"Operation failed: {e}")
```

---

### QC-02: 9 f-strings sem placeholders (F541) — ✅ CONCLUÍDO

f-strings sem `{}` são strings literais desnecessariamente prefixadas. Impacto de performance mínimo mas indica imprecisão.

```python
# Exemplo de ocorrência:
message = f"Operation completed"  # deveria ser "Operation completed"
```

---

### QC-03: Imports não utilizados — ✅ CONCLUÍDO

| Arquivo | Import não usado |
|---|---|
| `core/build_package.py` | `OperationPlan`, `QuickPlan` |
| `core/package_operations.py` | `OperationPlan`, `QuickPlan` |
| `gui/dialogs/conflict_dialog.py` | `os` |
| `gui/dialogs/progress_dialog.py` | `time` |
| `gui/dialogs/settings_dialog.py` | `core.settings.Settings` |
| `gui/gtk_logger.py` | `APP_DESC`, `Gtk` |

---

### QC-04: Variável ambígua `l` — ✅ CONCLUÍDO

**Arquivo:** [gui/main_window.py](usr/share/build-package/gui/main_window.py#L2413)

Variável de loop chamada `l` (E741). Renomear para nome descritivo.

---

### QC-05: Variável `success` atribuída mas nunca usada — ✅ CONCLUÍDO

**Arquivo:** [core/conflict_resolver.py](usr/share/build-package/core/conflict_resolver.py#L869)

```python
success = some_operation()  # valor nunca lido
```

---

## 7. UX e GTK4/Adwaita

### UX-01: `run_async_operation` é stub síncrono — ✅ CONCLUÍDO (= BUG-03)

Rever **BUG-03**. Operações demoradas (pull de repositório grande, trigger de workflow, busca de branches remotas) executam na UI thread usando `run_async_operation()` que na prática é síncrono. O correto é usar `ProgressDialog` com `threading.Thread` + `GLib.idle_add` para todas essas operações.

---

### UX-02: `AdwToast` para feedback de erro — ✅ CONCLUÍDO

**O que foi feito:**
- Adicionado método `show_error_dialog(message)` em `main_window.py` usando `Adw.AlertDialog`
- Corrigido bug: linha 860 usava `show_error_toast` para mensagem de **sucesso** ("✓ Token saved successfully") → trocado por `show_toast`
- `run_async_operation`: erros de operação e exceções não tratadas agora usam `show_error_dialog`
- `init_build_package`: falha de inicialização agora usa `show_error_dialog`
- `_save_token_callback`: erro de token salvo agora usa `show_error_dialog`
- `progress_dialog.py`: `_on_operation_error` agora usa `parent.show_error_dialog` com fallback gracioso
- `show_error_toast` mantido para validações menores (campos inválidos, URL vazia, etc.)

---

### UX-03: Linha comentada de CSS no toast de erro — ✅ CONCLUÍDO

**Arquivo:** [gui/main_window.py](usr/share/build-package/gui/main_window.py#L2236)

```python
# toast.add_css_class("error")
```

A classe CSS `error` em Adw.Toast não existe na API oficial. Remover comentário ou implementar via `Adw.Toast.set_action_name()` com ícone de aviso.

---

### UX-04: `SettingsDialog` separado da `PreferencesDialog` — ✅ CONCLUÍDO

**O que foi feito:**
- Conteúdo único do `SettingsDialog` migrado para `PreferencesDialog._create_behavior_page()`:
  - `operation_mode` ComboRow (safe/quick/expert)
  - `conflict_strategy` ComboRow (interactive/auto-ours/auto-theirs/manual)
  - `auto_pull` SwitchRow
  - `auto_version_bump` SwitchRow
- `_on_closed` agora sincroniza `conflict_strategy` ao `conflict_resolver` ativo
- `_refresh_ui` atualizado para incluir `mode_row` e `strategy_row`
- `main_gui.py`: `on_preferences_activated` reescrito para abrir `PreferencesDialog` diretamente
- `gui/dialogs/__init__.py`: removida exportação de `SettingsDialog`
- `settings_dialog.py` deletado (279L a menos)

---

### UX-05: Welcome Dialog deve ser mostrado uma única vez — ✅ VERIFICADO/CORRETO

**Verificação:** `should_show_welcome(settings)` retorna `settings.get("show_welcome", True)`. O default `True` garante exibição na primeira execução. Ao clicar "Get Started", o diálogo salva `settings.set("show_welcome", show_again)` onde `show_again = not dont_show_check.get_active()`. `_check_show_welcome()` em `main_window.__init__` só exibe se `should_show_welcome()` retornar `True`. Comportamento já correto, sem mudanças necessárias.

---

## 8. Acessibilidade (Orca / AT-SPI)

### A11Y-01: Botão de exclusão de token sem label acessível — ✅ CONCLUÍDO

**Arquivo:** [gui/dialogs/preferences_dialog.py](usr/share/build-package/gui/dialogs/preferences_dialog.py#L142)

```python
del_btn.set_icon_name("edit-delete-symbolic")
# sem set_accessible_name() ou label de texto
```

Para o Orca, este botão será anunciado apenas como "button" sem contexto. O usuário de screen reader não saberá qual token será excluído.

**Correção:**
```python
del_btn.set_icon_name("edit-delete-symbolic")
del_btn.update_property(
    [Gtk.AccessibleProperty.LABEL],
    [_("Delete token for {0}").format(org)]
)
```

---

### A11Y-02: Cobertura geral de tooltips — BOA ✅

17 chamadas a `set_tooltip_text()` identificadas em widgets de ação. Botões com apenas ícones (refresh, welcome, cleanup de branches) têm tooltips. Boa cobertura.

---

### A11Y-03: PasswordEntryRow para tokens — CORRETO ✅

O uso de `Adw.PasswordEntryRow` para entrada de tokens é correto: o Orca anuncia corretamente como "campo de senha", informando ao usuário que o conteúdo está mascarado.

---

### A11Y-04: Labels de status dinâmico sem notificação AT-SPI — ✅ CONCLUÍDO

**Arquivo:** [gui/widgets/overview_widget.py](usr/share/build-package/gui/widgets/overview_widget.py)

Quando o status do repositório é atualizado (ex.: "3 commits ahead"), o label muda mas o Orca não é notificado automaticamente. Para leitores de tela, mudanças dinâmicas de status devem usar `Gtk.AccessibleRole.STATUS` ou emitir `notify` via AT-SPI.

**Correção:**
```python
status_label.set_accessible_role(Gtk.AccessibleRole.STATUS)
```

---

### A11Y-05: Grupos de preferências com cabeçalhos — CORRETO ✅

Uso correto de `Adw.PreferencesGroup.set_title()` e `set_description()` em todos os grupos da `PreferencesDialog`. O Orca vai agrupar os controles corretamente.

---

### A11Y-06: Navegação por teclado na sidebar — ✅ VERIFICADO/CORRETO

A sidebar usa `Gtk.ListBox` (seleção SINGLE) com `Adw.ActionRow` (`.set_activatable(True)`). No GTK4+Adwaita os `Gtk.ListBoxRow` são focusáveis e navegáveis por teclado por padrão (Tab para entrar, setas para navegar, Enter/Space para ativar). A classe CSS `navigation-sidebar` garante o anel de foco via tema Adwaita. Nenhum `set_can_focus(False)` ou bloqueio de foco encontrado.

---

## 9. Dívida Técnica

### DT-01: `operation_preview.py` — ✅ VERIFICADO (ainda usado, manter)

**Arquivo:** [core/operation_preview.py](usr/share/build-package/core/operation_preview.py)

`OperationPlan` e `QuickPlan` são importados em `build_package.py` e `package_operations.py` mas marcados como não usados pelo ruff. Verificar se esse módulo ainda tem propósito ou se pode ser removido.

---

### DT-02: `gtk_menu.py` e `menu_system.py` — Sobreposição de responsabilidade — ✅ CONCLUÍDO

`cli/menu_system.py` renomeado para `cli/cli_menu.py`. Import em `cli/main_cli.py` atualizado. Header do arquivo atualizado. ruff: 0 erros.

---

### DT-03: Comentário de TODO implícito em `run_async_operation` — ✅ RESOLVIDO

BUG-03 (Sprint 1) implementou threading real. O comentário antigo (`# For now, run synchronously`) não existe mais. O método atual usa `threading.Thread` com `GLib.idle_add` para retornar ao main loop.

---

### DT-04: `local_builder.py` e `local_config.py` em `build-iso/`

Esses arquivos estão fora do escopo desta auditoria (build-package), mas merecem auditoria separada dado o padrão similar.

---

## 10. Roadmap de Refatoração

### Sprint 1 — Bugs e Segurança (imediato)

| ID | Tarefa | Arquivo | Esforço |
|---|---|---|---|
| BUG-01 | Adicionar `import os` em `main_window.py` | `gui/main_window.py` | 5 min |
| BUG-02 | Corrigir `ours_file` → `ours_file_abs` em `conflict_resolver.py` | `core/conflict_resolver.py` | 5 min |
| SEG-06 | Remover arquivo de token legado após migração | `core/github_api.py` | 30 min |
| SEG-05 | Adicionar `timeout=30` em todos os `requests.get/post` | `core/github_api.py`, `core/git_utils.py` | 1h |
| A11Y-01 | `update_property(LABEL)` no botão de delete de token | `gui/dialogs/preferences_dialog.py` | 15 min |

### Sprint 2 — Qualidade de Código

| ID | Tarefa | Esforço |
|---|---|---|
| QC-01 | Substituir bare excepts por exceções específicas (18 ocorrências) | 3h |
| QC-02 | Remover f-strings sem placeholders (9 ocorrências) | 30 min |
| QC-03 | Remover imports não usados (9 ocorrências) | 30 min |
| ARQ-04 | Configurar `ruff.toml` com `per-file-ignores` para E402 | 15 min |
| DT-01 | Auditar `operation_preview.py` — remover ou integrar | 1h |

### Sprint 3 — Arquitetura

| ID | Tarefa | Esforço |
|---|---|---|
| ARQ-05 | Criar classe `TokenStore` no `core/` | 2h |
| BUG-03 | Implementar `run_async_operation` real com threading | 3h |
| UX-02 | Substituir toast de erro crítico por `Adw.AlertDialog` | 2h |
| A11Y-04 | Roles AT-SPI para labels de status dinâmico | 1h |

### Sprint 4 — Refatoração Maior (planejamento futuro)

| ID | Tarefa | Notas |
|---|---|---|
| ARQ-01 | Extrair métodos de `BuildPackage` para módulos dedicados | Alta complexidade, risco de regressão |
| ARQ-02 | Introduzir padrão Presenter para `MainWindow` | Refatoração incremental por widget |
| ARQ-03 | Converter funções soltas em classes | Dependente de ARQ-01 |

---

## Apêndice — Configuração Ruff Recomendada

Criar `pyproject.toml` na raiz do projeto:

```toml
[tool.ruff]
target-version = "py39"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "B", "I"]
ignore = ["E501"]  # line too long - handled by formatter

[tool.ruff.lint.per-file-ignores]
"usr/share/build-package/gui/**/*.py" = ["E402"]
"usr/share/build-package/cli/**/*.py" = ["E402"]
"usr/share/build-package/core/build_package.py" = ["E402"]
```

---

*Auditoria realizada com: ruff 0.x, análise AST (Python 3), revisão manual de padrões GTK4/libadwaita e GNOME HIG.*
