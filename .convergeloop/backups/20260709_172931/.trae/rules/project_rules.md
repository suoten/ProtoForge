# Project Rules for ProtoForge

## Markdown Badge Syntax (CRITICAL)

When editing any `.md` file, **NEVER** modify or reformat markdown badge/image syntax.

The correct badge format is:
```
[![Alt Text](https://img.shields.io/badge/LABEL-VALUE-COLOR.svg)](https://link)
```

Common corruption patterns to AVOID:
- `! [alt](url)` - space between ! and [
- `![alt] (url)` - space between ] and (
- `! `url` null` - completely broken
- `![alt](url) null` - trailing null

When using SearchReplace on `.md` files containing badges, always use the EXACT original text as the search string. Do NOT let the badge syntax get split, reformatted, or corrupted.

## Markdown General Rules

- Preserve all `[![...](...)](...)` badge lines exactly as they are
- Do not add spaces inside markdown link syntax `[text](url)`
- Do not convert markdown image syntax to HTML `<img>` tags unless explicitly asked
- When editing around badge lines, match them character-by-character in search strings

## Testing

- Run tests with: `python -m pytest tests/ -v --tb=short -o "addopts="`
- All 77+ tests must pass before pushing

## Git Remotes

- GitHub: `git push ProtoForge-github master`
- Gitee: `git push ProtoForge-gitee master`
