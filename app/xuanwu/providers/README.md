# Built-In Provider Root

This directory contains built-in provider templates shipped with XuanWu.

Runtime also supports user-managed provider roots (default: `./.xuanwu/providers`
in local config, `/app/workspace/providers` in container deployment).
This built-in directory is optional and can stay empty.

If you need provider templates, place each provider under this directory:

- `<provider>/PROVIDER.md`
- `<provider>/skills/`
- `<provider>/channels/` (optional)
- `<provider>/auth/` (optional)
