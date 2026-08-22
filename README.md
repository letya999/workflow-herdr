# Workflow Herdr

YAML-конфигурируемый workflow для координации задач разработки между человеком и AI-агентами в Herdr.

Проект задаёт роли, порядок работы, правила для worktree и состояния задач. Логика вынесена в небольшие Python-скрипты без внешних зависимостей.

## Что внутри

- три режима работы: `small`, `medium` и `large`;
- роли `Brain`, `Orchestrator`, `Dispatcher` и `Worker`;
- YAML-конфигурация CLI, моделей, ролей и layout рабочих артефактов;
- проверки preflight до создания topology;
- валидация состояния задач и соответствия workstream/run.json;
- поддержка средних workflow в текущем workspace и больших workflow в отдельных worktree;
- минимальный YAML-парсер, чтобы запускать служебные скрипты без установки пакетов.

## Быстрый старт

### Требования

- Python 3.10 или новее;
- Git;
- установленный Herdr;
- CLI, указанные в `workflow.yaml` для выбранных ролей: Codex и Grok.

### Установка skill

После публикации склонируйте репозиторий в каталог skills Codex:

```powershell
git clone https://github.com/letya999/workflow-herdr.git "$env:USERPROFILE\.codex\skills\workflow-herdr"
```

Для локальной проверки можно запускать команды прямо из клона.

### Проверка проекта

Из корня целевого проекта выполните preflight для нужного режима:

```powershell
python scripts/workflow_guard.py preflight --project "C:\path\to\project" --volume small
```

Результат — JSON с полем `ok`. Для `medium` и `large` preflight также проверяет ограничения workspace, worktree и наличие необходимых CLI.

### Запуск workflow

Для короткой задачи достаточно передать intent worker-агенту в текущем Herdr workspace. Для задач с планом создайте change:

```powershell
python scripts/workflow_guard.py preflight --project "C:\path\to\project" --volume medium
python scripts/init_work.py --project "C:\path\to\project" --change add-login --volume medium
python scripts/load_config.py --project "C:\path\to\project" --change add-login --paths
```

Состояние workflow можно посмотреть так:

```powershell
python scripts/task_state.py --project "C:\path\to\project" --change add-login --dump
```

Для большого workflow используйте `--volume large`: он требует минимум два независимых workstream с непересекающимися границами файлов.

## Конфигурация

Основная конфигурация находится в [`workflow.yaml`](workflow.yaml). Локальный manifest проекта — `.herdr/workflow.yaml`. Он глубоко объединяется с глобальной конфигурацией: словари дополняются, а локальные списки и скаляры заменяют глобальные. Через manifest можно переопределить роли, CLI, модели, volumes, guards, task states и layout только для конкретного проекта.

Минимальный manifest конкретного проекта:

```yaml
roles:
  worker:
    model: project-specific-model
guards:
  large_min_runnable_tasks: 3
```

Шаблон manifest находится в [`assets/workflow.example.yaml`](assets/workflow.example.yaml). Layout определяет локальные `.herdr/runs`, state, run и receipts. Файл `.herdr/project.md` кратко описывает фактический workflow проекта; его формат задан в [`references/project-workflow.md`](references/project-workflow.md).

Основные переходы состояния:

```text
pending → ready → assigned → running → in_review → accepted → closed
```

Состояние `blocked` используется для остановки задачи до получения внешнего решения или недостающего факта.

## Проверка

Запустите тесты из корня репозитория:

```powershell
python -m unittest discover -s scripts -p "test_*.py" -v
```

## Структура проекта

```text
workflow.yaml                 # роли, CLI, режимы и правила workflow
SKILL.md                      # описание skill для Codex
README.md                     # quickstart и конфигурация
CONTRIBUTING.md               # branch flow и проверки
SECURITY.md                   # приватное сообщение об уязвимостях
LICENSE                       # MIT
scripts/                      # служебные команды и тесты
assets/                       # шаблоны состояния и project manifest
references/run.md             # краткая инструкция запуска
```

## Безопасность

Не добавляйте в репозиторий `.env`, ключи, токены, service-account JSON и другие секреты. Порядок приватного сообщения об уязвимости описан в [`SECURITY.md`](SECURITY.md).

## Участие в разработке

Изменения проходят по цепочке `feature branch → dev → main`. Команды проверки и правила оформления находятся в [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Лицензия

Проект распространяется по лицензии [MIT](LICENSE).
