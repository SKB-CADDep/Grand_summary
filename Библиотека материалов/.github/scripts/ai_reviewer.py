import os
import re
import time
import json
import requests
from github import Github, Auth
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════
OPENROUTER_MODELS = [
    os.environ.get("OPENROUTER_MODEL", "poolside/laguna-m.1:free"),
    "z-ai/glm-4.5-air:free",
    "openai/gpt-oss-120b:free",
    "openrouter/free",
]

# ⚠️ ВАЖНО: лимит для gpt-4o-mini через GitHub Models = 8000 токенов
# Промпт + системное сообщение ≈ 1500 токенов
# Оставляем ~6000 токенов на diff = ~24000 символов (с запасом)
MAX_DIFF_TOKENS = int(os.environ.get("MAX_DIFF_TOKENS", 6000))
TOKENS_PER_CHAR = 0.25  # 1 токен ≈ 4 символа для кода
MAX_DIFF_CHARS = int(MAX_DIFF_TOKENS / TOKENS_PER_CHAR)  # ≈ 24000 символов

MAX_RETRIES = 2
RETRY_STATUSES = {524, 529, 500, 502, 503}
FALLBACK_STATUSES = {429, 524, 529}
REASONING_ENABLED = os.environ.get("REASONING_ENABLED", "false").lower() == "true"
OPENROUTER_MODEL = OPENROUTER_MODELS[0]

# ═══════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════
def load_system_prompt() -> str:
    prompt_path = Path(__file__).parent.parent / "prompts" / "system_prompt.md"
    if prompt_path.exists():
        text = prompt_path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return _default_system_prompt()

def _default_system_prompt() -> str:
    return """
Ты — Senior Software Engineer с 15+ годами опыта. Проводишь код-ревью на русском языке.

## Твоя задача
Проанализируй предоставленный diff и дай структурированный отзыв.

## Структура ответа (строго соблюдай)

### 🔴 Критические проблемы
- Баги, уязвимости безопасности, утечки памяти, гонки данных.
- Если нет — напиши «Не обнаружено».

### 🟡 Улучшения
- Производительность, читаемость, нарушения принципов SOLID/DRY/KISS.
- Если нет — напиши «Не обнаружено».

### 🟢 Хорошие решения
- Что сделано хорошо — обязательно отметь.

### 💡 Рекомендации
- Конкретные предложения с примерами кода (если применимо).

### ✅ Итог
- Одна строка: можно мёрджить / нужны правки / блокирую мёрдж.

## Правила
- Будь конкретным: указывай файл и строку где возможно.
- Не придирайся к стилю если есть линтер (eslint/flake8/etc).
- Игнорируй изменения в lock-файлах.
- Если diff обрезан — фокусируйся на ключевых изменениях.
"""

def read_file_safe(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def estimate_tokens(text: str) -> int:
    """Грубая оценка количества токенов (1 токен ≈ 4 символа для кода)."""
    return int(len(text) * TOKENS_PER_CHAR)

# Паттерны бинарных файлов, которые бесполезны для ревью
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.ico',
    '.pdf', '.zip', '.tar', '.gz', '.rar', '.7z',
    '.exe', '.dll', '.so', '.bin', '.o', '.obj', '.class',
    '.woff', '.woff2', '.ttf', '.eot',
    '.pyc', '.pyo', '__pycache__',
    '.min.js', '.min.css', '.map',
}

def is_binary_file(filepath: str) -> bool:
    """Проверяет, является ли файл бинарным по расширению."""
    lower = filepath.lower()
    return any(lower.endswith(ext) for ext in BINARY_EXTENSIONS)

def parse_diff_into_files(diff: str) -> list:
    """Разбивает diff на блоки по файлам."""
    # Паттерн: diff --git a/... b/...
    parts = re.split(r'(?=^diff --git )', diff, flags=re.MULTILINE)
    files = []
    for part in parts:
        if not part.strip():
            continue
        # Извлекаем имя файла
        match = re.match(r'diff --git a/(.+?) b/(.+)', part)
        if match:
            filepath = match.group(2)
            files.append({
                'path': filepath,
                'content': part,
                'tokens': estimate_tokens(part),
            })
        else:
            files.append({
                'path': 'unknown',
                'content': part,
                'tokens': estimate_tokens(part),
            })
    return files

def truncate_file_block(file_block: dict, max_tokens: int) -> str:
    """Умно обрезает один блок diff, оставляя начало и конец."""
    content = file_block['content']
    if file_block['tokens'] <= max_tokens:
        return content
    
    # Оставляем ~40% начала и ~40% конца
    head_ratio = 0.4
    tail_ratio = 0.4
    total_chars = len(content)
    head_chars = int(total_chars * head_ratio)
    tail_chars = int(total_chars * tail_ratio)
    
    head = content[:head_chars]
    tail = content[-tail_chars:]
    
    return (
        head +
        f"\n\n... [СЕРДИНА ФАЙЛА ОБРЕЗАНА — {file_block['tokens'] - estimate_tokens(head) - estimate_tokens(tail)} токенов пропущено] ...\n\n" +
        tail
    )

def smart_truncate_diff(diff: str, max_tokens: int = MAX_DIFF_TOKENS) -> str:
    """
    Умная обрезка diff:
    1. Удаляет lock-файлы
    2. Удаляет бинарные файлы
    3. Если общий размер превышает лимит — умно обрезает большие файлы
    """
    files = parse_diff_into_files(diff)
    
    # Шаг 1: Фильтруем lock-файлы
    lock_pattern = re.compile(
        r'(package-lock\.json|poetry\.lock|yarn\.lock|Pipfile\.lock|composer\.lock|Gemfile\.lock|Cargo\.lock)$',
        re.IGNORECASE
    )
    files = [f for f in files if not lock_pattern.search(f['path'])]
    
    # Шаг 2: Фильтруем бинарные файлы
    files = [f for f in files if not is_binary_file(f['path'])]
    
    # Шаг 3: Считаем общий размер
    total_tokens = sum(f['tokens'] for f in files)
    print(f"  После фильтрации: {len(files)} файлов, ~{total_tokens} токенов")
    
    if total_tokens <= max_tokens:
        # Всё помещается — собираем обратно
        return '\n'.join(f['content'] for f in files)
    
    # Шаг 4: Нужно обрезать. Сначала удаляем самые большие файлы
    # Сортируем по размеру (большие в конце)
    files.sort(key=lambda f: f['tokens'])
    
    # Удаляем файлы с конца списка (самые большие), пока не уложимся
    while files and total_tokens > max_tokens:
        removed = files.pop()
        total_tokens -= removed['tokens']
        print(f"  Удалён файл целиком: {removed['path']} ({removed['tokens']} токенов)")
    
    # Если всё ещё много — обрезаем оставшиеся файлы
    if total_tokens > max_tokens:
        per_file_limit = max_tokens // len(files) if files else max_tokens
        truncated_files = []
        for f in files:
            if f['tokens'] > per_file_limit:
                truncated_files.append(truncate_file_block(f, per_file_limit))
            else:
                truncated_files.append(f['content'])
        result = '\n'.join(truncated_files)
    else:
        result = '\n'.join(f['content'] for f in files)
    
    # Добавляем предупреждение
    warning = (
        f"\n\n⚠️ **Внимание:** Diff был обрезан (лимит {max_tokens} токенов). "
        f"Ревью проведено по ключевым изменениям.\n"
    )
    return result + warning

def clean_thinking_tags(text: str) -> str:
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL)
    return text.strip()

# ═══════════════════════════════════════════════════════════════
# STREAMING-ВЫЗОВ OPENROUTER
# ═══════════════════════════════════════════════════════════════
def call_github_models(system_prompt: str, user_prompt: str) -> str:
    """Вызывает GitHub Models (бесплатно, без внешних ключей)"""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN не найден")
    
    model = "gpt-4o-mini"  # Бесплатная модель от GitHub
    print(f">>> Используем GitHub Model: {model}")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 4096
    }
    
    response = requests.post(
        "https://models.inference.ai.azure.com/chat/completions",
        headers=headers,
        json=payload,
        timeout=120
    )
    
    print(f"    HTTP статус: {response.status_code}")
    
    if response.status_code != 200:
        raise Exception(f"API Error {response.status_code}: {response.text[:500]}")
    
    result = response.json()
    return result["choices"][0]["message"]["content"]

def _parse_sse_stream(response: requests.Response) -> str:
    full_content = []
    last_finish_reason = None
    
    for raw_line in response.iter_lines(decode_unicode=False):
        if not raw_line:
            continue
        if raw_line.startswith(b":"):
            continue
        if raw_line.startswith(b"data: "):
            data_bytes = raw_line[6:].strip()
            if data_bytes == b"[DONE]":
                break
            data_str = data_bytes.decode("utf-8", errors="replace")
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            if "error" in chunk:
                err = chunk["error"]
                code = err.get("code", 0)
                msg = err.get("message", str(err))
                if code == 429:
                    raise FallbackError(f"Stream 429: {msg}")
                if code in RETRY_STATUSES:
                    raise RetryableError(f"Stream error {code}: {msg}")
                raise Exception(f"Stream API error {code}: {msg}")
            choices = chunk.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta", {})
            content_piece = delta.get("content")
            if content_piece:
                full_content.append(content_piece)
            finish_reason = choice.get("finish_reason")
            if finish_reason:
                last_finish_reason = finish_reason
    
    result = clean_thinking_tags("".join(full_content))
    if not result.strip():
        raise RetryableError("Пустой ответ от модели")
    
    print(f"    Стрим завершён. finish_reason={last_finish_reason}, символов={len(result)}")
    return result

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main() -> int:
    print("=" * 60)
    print("Starting AI Code Review")
    print(f"Model            : {OPENROUTER_MODEL}")
    print(f"Max diff tokens  : {MAX_DIFF_TOKENS}")
    print(f"Max diff chars   : {MAX_DIFF_CHARS}")
    print(f"Reasoning enabled: {REASONING_ENABLED}")
    print("=" * 60)
    
    github_token = os.environ.get("GITHUB_TOKEN")
    pr_number    = int(os.environ.get("PR_NUMBER", 0))
    repo_name    = os.environ.get("REPO_NAME", "")
    pr_title     = os.environ.get("PR_TITLE", "Untitled")
    pr_body      = os.environ.get("PR_BODY") or "No description"
    pr_author    = os.environ.get("PR_AUTHOR", "unknown")
    
    if not all([github_token, pr_number, repo_name]):
        print("❌ Отсутствуют обязательные env-переменные")
        return 1
    
    diff          = read_file_safe("pr_diff.txt")
    changed_files = read_file_safe("changed_files.txt")
    
    if not diff.strip():
        print("Diff пустой — пропускаем ревью.")
        return 0
    
    # ⭐ ИСПОЛЬЗУЕМ УМНУЮ ОБРЕЗКУ
    diff_for_review = smart_truncate_diff(diff, max_tokens=MAX_DIFF_TOKENS)
    print(f"Diff: {len(diff)} → {len(diff_for_review)} символов")
    print(f"Примерно токенов: {estimate_tokens(diff_for_review)}")
    
    system_prompt = load_system_prompt()
    user_prompt = (
        "## Pull Request для ревью\n\n"
        f"**Автор:** @{pr_author}\n"
        f"**Название:** {pr_title}\n\n"
        f"**Описание:**\n{pr_body}\n\n"
        "---\n\n"
        f"**Изменённые файлы:**\n```\n{changed_files}\n```\n\n"
        f"**Diff:**\n```diff\n{diff_for_review}\n```\n\n"
        "---\n\nПроведи код-ревью этого PR."
    )
    
    print("Вызываем модель...")
    try:
        review_text = call_github_models(system_prompt, user_prompt)
        print(f"✅ Ревью получено ({len(review_text)} символов)")
    except Exception as e:
        review_text = (
            f"**⚠️ Ошибка AI-ревьюера:** `{e}`\n\n"
            f"Попробуй перезапустить workflow или проверь логи."
        )
        print(f"❌ Ошибка: {e}")
    
    print("Постим комментарий в PR...")
    try:
        gh   = Github(auth=Auth.Token(github_token))
        repo = gh.get_repo(repo_name)
        pr   = repo.get_pull(pr_number)
        model_label = OPENROUTER_MODEL.split("/")[-1]
        comment = (
            "## AI Code Review\n\n"
            f"{review_text}\n\n"
            "---\n"
            f"<sub>Model: `{model_label}` via OpenRouter · "
            f"Diff: ~{estimate_tokens(diff_for_review)} tokens</sub>"
        )
        pr.create_issue_comment(comment)
        print("✅ Комментарий опубликован!")
    except Exception as e:
        print(f"❌ Не удалось опубликовать комментарий: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())