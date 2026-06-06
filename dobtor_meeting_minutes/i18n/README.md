# Translations for dobtor_meeting_minutes

## Generating the .pot template

Run from the Odoo server (requires the module to be installed):

```bash
./odoo-bin -d <db-name> \
    --i18n-export=addons/dobtor_meeting_minutes/i18n/dobtor_meeting_minutes.pot \
    --modules=dobtor_meeting_minutes \
    --stop-after-init
```

## Adding a new language (e.g. zh_TW)

```bash
./odoo-bin -d <db-name> \
    --i18n-export=addons/dobtor_meeting_minutes/i18n/zh_TW.po \
    --modules=dobtor_meeting_minutes \
    --language=zh_TW \
    --stop-after-init
```

Then translate msgids in the generated .po file.

## Translatable content in this module

- All `_()`-wrapped strings in Python (91 occurrences across 7 files)
- All field `string=` and `help=` attributes (auto-translated by Odoo)
- All Selection option labels (auto-translated)
- View labels and button strings (auto-translated)
- `note.summary.template` records — `name`, `description`, `prompt` fields are `translate=True`

## Non-translatable content

- Python comments and docstrings (internal)
- Module code identifiers (variable names, etc.)
- `ir.config_parameter` keys (technical identifiers)
- `XMLID` references

## Adding translatable fields

When adding new fields that store user-visible text, mark them `translate=True`:

```python
description = fields.Char(string='Description', translate=True)
```
