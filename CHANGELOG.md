# Changelog — Discography Analyzer

## [25.10.2026] — Portable .exe (PyInstaller onefile + UPX)

**Что сделано:**

- `build_exe.spec`: one-file portable-сборка `Discography_Analyzer_1.7.0.exe` (tkinter-GUI, `console=False`, без внешних зависимостей).
  Команда: `python -m PyInstaller --clean --noconfirm --upx-dir tools/upx/upx-4.2.4-win64 build_exe.spec`
- `hiddenimports`: `collect_submodules('mutagen')` (его `File` — динамическая фабрика форматов), `collect_submodules('discography_analyzer')`, `collect_submodules('openpyxl')`.
- `tools/upx/` (UPX 4.2.4 portable) добавлен в `.gitignore`.
- Итог: `dist/Discography_Analyzer_1.7.0.exe`, **20 МБ**, 0 отсутствующих импортов в логе, UPX активен (279 строк лога).

**Ошибка/решение:**

- В спецификациях Qt-проектов `tkinter` принято исключать — здесь он фреймворк GUI, исключение сломало бы окно; в `excludes` добавлены только numpy/pandas/matplotlib/PyQt и пр.
- Смоук-тест «как на ПК без Python»: запуск с PATH, из которого вычищены Python-пути → окно **«Discography Analyzer»** реально поднялось (ctls-проб EnumWindows), процесс завершился чисто (rc=0). PATH полностью обнулять нельзя — иначе теряются пути VC++ runtime (ложный отказ).

## [25.10.2026] — Влитие ветки аудита `arena/3512578b-discography-analyzer` в main

Аудит проведён сторонним агентом (arena), перепроверен независимо перед вливанием.

**Что сделано (12 коммитов, `c8b91dd..e82cf03`):**

- `perf(exporter)`: экспорт XLSX линеен по строкам вместо O(n²) — убран `sheet[row]` (пересчёт `max_column` на каждую строку), общие неизменяемые объекты стилей.
- `perf(metadata)`: `if not tags` на EasyID3 заменён на `tags is None` — `bool(EasyID3)` перечислял все easy-ключи (~25 раз на каждый MP3).
- `fix(metadata_writer)`: «безопасное исправление» больше не переписывает ID3v2.3 как ID3v2.4 (mutagen по умолчанию пишет v2.4; передаётся `v2_version=3`).
- `fix(metadata)`: комментарий MP3 (`COMM:<desc>:<lang>`) теперь попадает в поле «Комментарий»; технические кадры (`iTunNORM` и т.п.) не трогаются.
- `fix(metadata)`: любая ошибка Pillow (в т.ч. `SyntaxError`, `DecompressionBombError`) — это `cover_error`, а не «ошибка метаданных» всего файла.
- `refactor(metadata)`: один путь извлечения обложки `_embedded_cover()` для аудита и предпросмотра (раньше могли показываться разные картинки FLAC).
- `perf(metadata)`: FLAC/APE парсятся один раз вместо двух (easy-обёртки у них нет).
- `refactor(ui)`: единый `_clear_results()` для start/stop/failure; после ошибки анализа очищаются инфо-панель и обложка.
- `fix(ui)`: диалог экспорта фиксирует снапшот результата при открытии.
- `chore`: `[tool.ruff]` (пройден чисто), CI-воркфлоу GitHub Actions, `python -m discography_analyzer`, AUDIT.md с деталями и предложениями (п. 4.1–4.10 — требуют решения автора).

**Ошибка/решение (по итогам независимой проверки):**

- Утверждения аудита о поведении библиотек подтверждены эмпирически (mutagen 1.48.1, openpyxl 3.1.5, Pillow 12.3.0): `bool(EasyID3)` действительно вызывает `keys()`; ключи комментариев — `COMM:<desc>:<lang>`, `EasyID3.get("comment")` → `None`; сохранение v2.3 по умолчанию поднимает до v2.4, `v2_version=3` сохраняет; `DecompressionBombError` не наследует OSError/ValueError; `sheet[row]` триггерит полный скан `max_column`.
- Golden-сравнение анализа на синтетике (480 треков, MP3+FLAC: дубли/вариации/конфликты/v2.3/v2.4/COMM/bomb-обложки): расхождения только целевые — 200 файлов с новым полем комментария и 10 bomb-файлов (`metadata_errors` → `cover_error`, аудит-ишьюс «отсутствует» → «повреждена»). Остальные поля всех треков идентичны. XLSX: значения и стили идентичны на всех листах, кроме листа аудита (−10 строк ишьюсов, согласовано).
- Замер на 480 треках: анализ 0.48 с → 0.28 с (1.7×), экспорт 1.13 с → 0.29 с (3.9×).
- `noqa: SIM118` в `metadata.py` обоснован и обязателен: Vorbis-словари (`VCFLACDict`) итерируются как пары `(key, value)` — механическая правка ruff сломала бы FLAC.
- Тесты: 64 → 71, все зелёные; `ruff check .` чистый.

Ветка `arena/3512578b-discography-analyzer` удалена после вливания.