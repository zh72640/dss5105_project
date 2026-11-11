"""Check repository language conventions and local Markdown links without network access."""
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
NON_ENGLISH_SCRIPT = re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]')
LINK = re.compile(r'!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+"[^"\n]*")?\)')


def check():
    names = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT
    ).decode('utf-8').split('\0')
    errors, checked = [], 0
    for name in sorted(set(filter(None, names))):
        path = ROOT / name
        if not path.is_file():
            continue  # An unstaged deletion is absent from the working tree.
        if NON_ENGLISH_SCRIPT.search(name) or re.search(r'_CN(?:_EN)?\.', name):
            errors.append(f'{name}: use an English filename')
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        checked += 1
        for number, line in enumerate(content.splitlines(), 1):
            if NON_ENGLISH_SCRIPT.search(line):
                errors.append(f'{name}:{number}: non-English source text; translate prose or escape compatibility inputs')
        if path.suffix.lower() != '.md':
            continue
        in_fence = False
        for number, line in enumerate(content.splitlines(), 1):
            if re.match(r'^\s*(?:```|~~~)', line):
                in_fence = not in_fence
            if in_fence:
                continue
            for match in LINK.finditer(line):
                target = match[1].strip('<>')
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve()
                if not resolved.is_relative_to(ROOT) or not resolved.exists():
                    errors.append(f'{name}:{number}: broken local link: {target}')
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'Checked {checked} text files: English source conventions and local Markdown links passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(check())
