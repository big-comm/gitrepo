# PLANNING-ISO.md — Auditoria e Melhorias: build-iso

> **Status**: Auditoria completa. Todos os itens críticos e moderados resolvidos.
> Ruff: 0 erros (antes e depois da auditoria).

---

## Resumo da Auditoria

| Arquivo         | Linhas | Status          |
|-----------------|-------:|-----------------|
| `build_iso.py`  |   756  | ✅ Corrigido     |
| `local_builder.py` | 674 | ✅ Corrigido     |
| `config.py`     |   172  | ✅ Corrigido     |
| `github_api.py` |   156  | ✅ Corrigido     |
| `local_config.py` |  94  | ✅ Corrigido     |
| `git_utils.py`  |    93  | ✅ OK            |
| `logger.py`     |   143  | ✅ OK            |
| `menu_system.py`|   133  | ✅ OK            |
| `main.py`       |    36  | ✅ OK            |
| `translation_utils.py` | 11 | ✅ OK         |
| **Total**       | **2268** |               |

---

## Itens Concluídos

### ✅ SEG-05 — requests sem timeout (Segurança)

**Prioridade**: Alta  
**Risco**: Bloqueio indefinido de UI/processo em caso de rede lenta ou indisponível

**Problema**: 4 chamadas HTTP sem `timeout`:
- `build_iso.py:~269` — `requests.get(api_url)` em `get_build_list()`
- `build_iso.py:~339` — `requests.get(...)` em `get_edition()` (GitHub)
- `build_iso.py:~347` — `requests.get(...)` em `get_edition()` (GitLab)
- `github_api.py:~118` — `requests.post(workflow_url, ...)` em `trigger_workflow()`

**Correção**: Adicionado `timeout=30` em todas as chamadas.

---

### ✅ QC-01 — Duplicação de constantes em local_config.py

**Prioridade**: Moderada  
**Risco**: `~/.config/build-iso` e `config.json` definidos em dois lugares; mudança em um não reflete no outro.

**Problema**: `local_config.py` definia:
```python
CONFIG_DIR = os.path.expanduser("~/.config/build-iso")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
```
Que são idênticos a `LOCAL_CONFIG_DIR` e `LOCAL_CONFIG_FILE` já definidos em `config.py`.

**Correção**: `local_config.py` agora importa de `config.py`:
```python
from config import LOCAL_CONFIG_DIR, LOCAL_CONFIG_FILE
...
CONFIG_DIR = LOCAL_CONFIG_DIR
CONFIG_FILE = LOCAL_CONFIG_FILE
```

---

### ✅ QC-02 — Duplicação de constantes de container em local_builder.py

**Prioridade**: Moderada  
**Risco**: Imagem Docker e URL do repo build-iso hardcodadas em dois lugares; atualizar apenas `config.py` não propagaria a mudança.

**Problema**: `local_builder.py.__init__` hardcodava:
```python
self.container_image = "talesam/community-build:latest"
self.build_iso_repo = "https://github.com/talesam/build-iso.git"
```
Idênticos a `CONTAINER_IMAGE` e `BUILD_ISO_REPO` em `config.py`.

**Correção**: `local_builder.py` agora importa:
```python
from config import CONTAINER_IMAGE, BUILD_ISO_REPO
...
self.container_image = CONTAINER_IMAGE
self.build_iso_repo = BUILD_ISO_REPO
```

---

### ✅ BUG-01 — DEFAULT_ORGANIZATION fora de VALID_ORGANIZATIONS

**Prioridade**: Alta  
**Risco**: Com `DEFAULT_ORGANIZATION = "big-comm"` e `VALID_ORGANIZATIONS = ["talesam", "bigbruno"]`, nenhuma configuração padrão funcionaria ao chamar `biso` sem flags, pois `ORG_DEFAULT_CONFIGS.get("big-comm")` retornaria um org sem build ativo.

**Correção**: `config.py` atualizado para `DEFAULT_ORGANIZATION = "talesam"` (primeiro elemento válido).

---

## Itens Verificados (sem problema)

| Item                         | Análise                                                     |
|------------------------------|-------------------------------------------------------------|
| `shell=True` / `os.system`   | Nenhuma ocorrência. `subprocess.run` sempre com listas.     |
| `open()` sem `with`          | Todos os `open()` usam context manager `with`.              |
| Bare `except:`               | Nenhum. Todos usam `except Exception` (aceitável aqui).     |
| Bloqueio de UI               | CLI-only — não se aplica (`menu_system.py` roda em thread principal). |
| Token nos logs               | Nenhum vazamento via `logger.log()`.                        |
| Permissões de arquivo        | `local_config.py` cria dirs com `os.makedirs(exist_ok=True)`. |
| `subprocess.run` sem timeout | Build container: não tem timeout (correto — build pode demorar horas). |
| Arquitetura geral             | Bem estruturado: config / api / builder / menu separados.   |

---

## Observações para o Futuro (Low Priority)

- **DT-02 equivalente**: `menu_system.py` poderia ser renomeado para `iso_menu.py` para consistência com `build-package` (que fez `menu_system.py → cli_menu.py`). Impacto: 1 import em `build_iso.py`. Baixo valor.
- **DEFAULT_ISO_PROFILES**: Inclui `"big-comm"` como chave, mas `VALID_ORGANIZATIONS` não inclui `"big-comm"`. Se reativar "big-comm", adicionar lá também.
- **ARQ**: `build_iso.py` (756L) é grande mas bem organizado em métodos coesos. Não é candidato a refatoração no momento.

---

*Auditoria realizada em 2025. Ruff: 0 erros pré e pós.*
