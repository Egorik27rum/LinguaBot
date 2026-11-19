'''
LinguaBot: экспорт проекта в JSON для передачи другой LLM.

Использование:
  python export_project.py                    # выгрузка в project_export.json
  python export_project.py -o out.json        # другое имя файла
  python export_project.py --max-size 100000  # лимит на один файл в байтах

Стандартная библиотека only. Секреты (.env, bots.json с токенами) не выгружаются.
'''
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTEXT_FILE = ROOT / 'project_context.json'
DEFAULT_OUTPUT = ROOT / 'project_export.json'
DEFAULT_MAX_SIZE = 200_000  # байт на файл

SKIP_DIRS = {
    '.venv', 'venv', 'env', '__pycache__', '.git', '.idea', '.vscode',
    'logs', 'backups', 'tools', 'node_modules', '.pytest_cache', '.mypy_cache',
}

# Файлы, которые содержат секреты: их содержимое не выгружается
SECRET_FILES = {'.env', 'bots.json', 'bots.broken'}
SECRET_PATTERNS = (re.compile(r'^bots\..*\.json$'),)

# Расширения текстовых файлов. Всё остальное пропускается
TEXT_EXTENSIONS = {
    '.py', '.bat', '.cmd', '.ps1', '.sh', '.txt', '.md', '.json', '.toml',
    '.yaml', '.yml', '.ini', '.cfg', '.sql', '.html', '.css', '.js', '.ts',
}
TEXT_NAMES = {'requirements.txt', '.gitignore', 'Dockerfile', 'Makefile'}

# Файлы, которые мы сами создаём: их не нужно выгружать
SELF_FILES = {'export_project.py', DEFAULT_OUTPUT.name}


def is_secret(path: Path) -> bool:
    name = path.name
    if name in SECRET_FILES or name.startswith('.env'):
        return True
    return any(p.match(name) for p in SECRET_PATTERNS)


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in TEXT_NAMES


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith('.')


def iter_project_files(root: Path):
    '''Рекурсивно обходит проект, не заходя в служебные папки. Сортирует для стабильного вывода.'''
    for path in sorted(root.rglob('*')):
        rel_parts = path.relative_to(root).parts
        if any(should_skip_dir(part) for part in rel_parts[:-1]):
            continue
        if path.is_file():
            yield path


def read_text_safely(path: Path, max_size: int) -> tuple[str, bool, bool]:
    '''Возвращает (текст, обрезан_ли, прочитан_ли). Пробует UTF-8, затем CP1251 для старых файлов Windows.'''
    raw = path.read_bytes()
    truncated = len(raw) > max_size
    if truncated:
        raw = raw[:max_size]
    for encoding in ('utf-8-sig', 'cp1251'):
        try:
            return raw.decode(encoding), truncated, True
        except UnicodeDecodeError:
            continue
    return '', truncated, False


def build_file_entry(path: Path, max_size: int) -> dict:
    rel = path.relative_to(ROOT).as_posix()
    size = path.stat().st_size

    if is_secret(path):
        return {
            'name': path.name,
            'path': rel,
            'extension': path.suffix,
            'size_bytes': size,
            'skipped': 'секреты: содержимое не выгружается',
            'code': None,
        }

    if not is_text_file(path):
        return {
            'name': path.name,
            'path': rel,
            'extension': path.suffix,
            'size_bytes': size,
            'skipped': 'бинарный или неподдерживаемый формат',
            'code': None,
        }

    code, truncated, ok = read_text_safely(path, max_size)
    entry = {
        'name': path.name,
        'path': rel,
        'extension': path.suffix,
        'size_bytes': size,
        'code': code if ok else None,
    }
    if truncated:
        entry['truncated'] = f'обрезано до {max_size} байт'
    if not ok:
        entry['skipped'] = 'не удалось определить кодировку'
    return entry


def load_context() -> dict:
    if not CONTEXT_FILE.exists():
        print(f'Внимание: {CONTEXT_FILE.name} не найден, контекст будет пустым.', file=sys.stderr)
        return {}
    return json.loads(CONTEXT_FILE.read_text(encoding='utf-8'))


def build_export(root: Path, max_size: int) -> dict:
    files = []
    skipped_self = 0
    for path in iter_project_files(root):
        if path.name in SELF_FILES and path.parent == root:
            skipped_self += 1
            continue
        files.append(build_file_entry(path, max_size))

    return {
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'project_root': root.name,
        'context': load_context(),
        'stats': {
            'files_total': len(files),
            'files_with_code': sum(1 for f in files if f['code'] is not None),
            'files_skipped': sum(1 for f in files if f['code'] is None),
            'self_files_excluded': skipped_self,
        },
        'files': files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Экспорт проекта LinguaBot в JSON для LLM.')
    parser.add_argument('-o', '--output', type=Path, default=DEFAULT_OUTPUT, help='путь к выходному JSON')
    parser.add_argument('--max-size', type=int, default=DEFAULT_MAX_SIZE, help='лимит на файл, байт')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export = build_export(ROOT, args.max_size)

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding='utf-8')

    stats = export['stats']
    print(f'Экспорт готов: {output}')
    print(f"  файлов: {stats['files_total']}, с кодом: {stats['files_with_code']}, пропущено: {stats['files_skipped']}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Отменено пользователем.', file=sys.stderr)
        sys.exit(1)
