# Workflow Herdr

YAML-граф для координации человека и AI-агентов **внутри Herdr**.

Рантайм — сессии, вкладки, pane id и живые имена агентов. Python-скрипты
пишут файлы, проверяют инварианты и стартуют seat. Отдельного runner, демона
и шины событий нет.

## Что внутри

- графы `small`, `medium`, `large` (и любые overlay-графы из узлов YAML);
- узлы `Brain`, `Orchestrator`, `Dispatcher`, `Worker`;
- слои стейта: продукт Herdr, глобальный индекс, overlay проекта, run
  (`identity`, `run.json`, `orchestration`, `artifacts`, `tasks`);
- preflight CLI / kind / model / effort / usage до любой topology;
- `doctor` и `status` (mapped / orphan);
- focus-or-start с retry `agent_pane_busy` / `agent_prompt_stalled` и rollback;
- medium в текущем workspace (rename tab/pane), large — labeled worktree;
- цикл BODW: Dispatcher крутит Worker через `prompt --wait`, Brain не ждёт.

## Быстрый старт

### Требования

- Python 3.10 или новее;
- Git;
- установленный Herdr;
- CLI из `workflow.yaml`: Codex (Orchestrator) и Devin (Dispatcher/Worker).

### Установка skill

```powershell
git clone https://github.com/letya999/workflow-herdr.git "$env:USERPROFILE\.codex\skills\workflow-herdr"
```

Скопируйте тот же каталог в `$env:USERPROFILE\.agents\skills\workflow-herdr` и
`$env:USERPROFILE\.grok\skills\workflow-herdr`, если этими харнессами пользуетесь.

### Проверка проекта

```powershell
python scripts/bootstrap.py --project "C:\path\to\project"
```

Результат — JSON с полем `ok`.

### Запуск workflow

Короткая задача: Brain отдаёт intent одному Worker в текущем tab, без
`--wait` на стороне Brain.

Для задачи с планом:

```powershell
python scripts/bootstrap.py --project "C:\path\to\project"
python scripts/init_work.py --project "C:\path\to\project" --change add-login --volume medium
python scripts/layout_graph.py --project "C:\path\to\project" --change add-login --volume medium
python scripts/prompt_seat.py --project "C:\path\to\project" --change add-login --seat orchestrator --from brain --text "intent"
python scripts/orchestrate.py --project "C:\path\to\project" --change add-login --from brain --on goal_created
python scripts/task_state.py --project "C:\path\to\project" --change add-login --dump
```

`large` требует минимум два независимых workstream с непересекающимися
файлами и по labeled worktree на поток.

## Конфигурация

Канон — [`workflow.yaml`](workflow.yaml): `harnesses`, `nodes`, `graphs`.
Аргументы запуска вынесены в [`mappings/`](mappings/): по одному YAML/JSON
на harness, с необязательными переопределениями по модели.
Локальный manifest `.herdr/workflow.yaml` глубоко мержится: словари
дополняются, списки и скаляры заменяются. Старые ключи `roles` / `volumes` /
`clis` по-прежнему принимаются и нормализуются.

Минимальный overlay:

```yaml
nodes:
  worker:
    harness: grok
    model: grok-4.6
    effort: high
guards:
  large_min_runnable_tasks: 3
```

Шаблон: [`assets/workflow.example.yaml`](assets/workflow.example.yaml).
Формат аргументов: [`mappings/README.md`](mappings/README.md).
Профиль проекта: [`references/project-workflow.md`](references/project-workflow.md).
Как гонять цикл: [`references/run.md`](references/run.md).

Основные переходы задачи:

```text
pending → ready → assigned → running → in_review → accepted → closed
```

`blocked` — стоп до факта или решения человека.

## Проверка

```powershell
python -m unittest discover -s scripts -p "test_*.py" -v
```

## Структура

```text
workflow.yaml                 # harnesses, nodes, graphs, guards
SKILL.md                      # skill для харнесса
README.md                     # quickstart
scripts/                      # file helpers, start_seat, tests
assets/                       # шаблоны run-файлов
references/run.md             # контракт запуска и BODW-цикла
```

## Безопасность

Не добавляйте в репозиторий `.env`, ключи, токены, service-account JSON.
Порядок сообщения об уязвимости: [`SECURITY.md`](SECURITY.md).

## Участие

`feature branch → dev → main`. Подробности в [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Лицензия

[MIT](LICENSE).
