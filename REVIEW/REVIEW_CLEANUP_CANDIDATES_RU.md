# ANPR-System-v0.8_web — Кандидаты на очистку

**Дата:** 2026-03-18

---

## Таблица 1: Можно безопасно удалить уже сейчас

Эти элементы подтвержденно являются мертвым кодом с высокой степенью уверенности. Их удаление не несет функционального риска.

| Элемент | Файл | Строки | Доказательство | Примечание |
|--------|------|--------|----------------|-----------|
| `CRNNRecognizer.recognize()` | `anpr/recognition/crnn_recognizer.py` | 78–82 | Не вызывается ни в одном `.py` файле; все вызовы используют `recognize_batch()` | Тонкая обертка над `recognize_batch([img])[0]` |
| `TrackAggregator.clear_last()` | `anpr/pipeline/anpr_pipeline.py` | 65–66 | Не вызывается ни в одном `.py` файле | Частичный reset, который фактически заменен `reset()` |
| Второй `mkdir` в `_save_jpeg` | `runtime/channel_runtime.py` | 253 | Директория уже создается в `_build_event_media_paths` на строке 243 | Лишний системный вызов при каждом событии |
| Лишний вызов `cleanup_stale` | `runtime/channel_runtime.py` | 498 | Такой же вызов уже выполняется внутри `update_from_detections` (строка 520), который вызывается сразу после этого | Двойная очистка на каждый обработанный кадр |
| Копия `list(plate_images)` | `anpr/recognition/crnn_recognizer.py` | 69 | Вызывающий код и так всегда передает `List` | Можно удалить; тип параметра лучше сменить на `List[np.ndarray]` |

---

## Таблица 2: Требует проверки перед удалением

Эти элементы выглядят неиспользуемыми, но перед удалением их нужно вручную проверить (grep вне Python, шаблоны, JS-привязки).

| Элемент | Файл | Строки | Что проверить | Почему есть неопределенность |
|--------|------|--------|---------------|-------------------------------|
| `log_perf_stage` | `common/logging.py` | 277–288 | Выполнить `grep -r "log_perf_stage"` по всему проекту | В просмотренных `.py` файлах не используется, но может быть оставлен как публичный API |
| `CONTROLLER_TYPES` dict | `controllers/service.py` | 14–16 | Проверить, не обращается ли к `CONTROLLER_TYPES` фронтенд (`app/web/app.js`) или шаблоны | Экспортируется через `__all__`; возможно используется не в Python |
| `RELAY_MODES` dict | `controllers/service.py` | 20–23 | Аналогично: проверить использование в UI или во внешних скриптах | Хранит русские отображаемые названия режимов реле; может читаться интерфейсом |
| `TrackAggregator.reset()` | `anpr/pipeline/anpr_pipeline.py` | 68–71 | Вызывается в `anpr_pipeline.py:260`; убедиться, что тесты не завязаны на различие между `reset` и `clear_last` | Оставлен в списке только для полноты; удалять не рекомендуется |

---

## Таблица 3: Нужно рефакторить, а не удалять

Эти элементы реально проблемные, но их простое удаление сломает поведение системы. Им нужна замена или переработка.

| Элемент | Файл | Строки | Проблема | Рекомендуемый рефакторинг |
|--------|------|--------|----------|----------------------------|
| `TrackAggregator.track_texts` и `last_emitted` | `anpr/pipeline/anpr_pipeline.py` | 30–31, 37–63 | Неограниченный рост памяти (утечка) | Добавить TTL-эвикцию; заменить список значений на `deque(maxlen=best_shots)` |
| `TrackDirectionEstimator._history` | `anpr/pipeline/anpr_pipeline.py` | 96, 149 | Неограниченный рост памяти (утечка) | Добавить TTL-эвикцию с `time.monotonic()` по каждому треку |
| `ANPRPipeline._last_seen` | `anpr/pipeline/anpr_pipeline.py` | 193, 198–201 | Неограниченный рост памяти | Очищать записи, где `now - ts > cooldown_seconds * 2`, в `_on_cooldown` |
| `_apply_roi_mask` full-frame masking | `runtime/channel_runtime.py` | 274–281, 494 | На каждый кадр выделяет 2+ МБ mask; полигон считается дважды | Удалить masking; оставить только `_filter_detections_by_roi`; полигон считать один раз |
| `PlatePreprocessor.preprocess` | `anpr/preprocessing/plate_preprocessor.py` | 149, 155 | CLAHE и морфологическое ядро создаются заново на каждом вызове | Перенести в `__init__` как атрибуты экземпляра |
| `CRNNRecognizer._decode_batch` | `anpr/recognition/crnn_recognizer.py` | 84–114 | Python-цикл по каждому CTC timestep; отдельные вызовы `argmax` и `max` на одном и том же тензоре | Векторизовать: `argmax` и `exp(max)` по всему batch × time; Python-цикл оставить только по batch |
| `put_global_settings` restart logic | `app/api/routers/settings.py` | 67 | При каждом сохранении настроек перезапускает все каналы и перезагружает модели | Определять, какие поля реально изменились; рестартить processor только при изменениях, влияющих на ANPR |
| `dispatch_event` + `handle_event` split | `controllers/service.py` | 165–220 | Лишний уровень косвенности | Объединить в один `dispatch_event` с `try/except` внутри |
| `DebugLogBus.wait_for_entries` в `asyncio.to_thread` | `runtime/debug.py:375`, `routers/debug.py:67` | Блокирует поток thread pool на срок до 15 секунд на одного SSE-клиента | Заменить на подписку через `asyncio.Queue`, как в `EventBus` |
| `settings.py` router file | `app/api/routers/settings.py` | весь файл | Файл называется `settings`, но содержит и retention/export маршруты | Разделить на `settings.py` (UI-настройки) и `data.py` (lifecycle, export) |
| `ChannelFilterPayload` plate size types | `app/api/schemas.py` | 71–72 | Использует сырые `Dict[str,int]` вместо `PlateSizePayload` | Заменить на `PlateSizePayload` для единообразия и валидации |
| `ChannelConfigPayload.detection_mode` default | `app/api/schemas.py` | 36 | Значение по умолчанию `"motion"` конфликтует с runtime default `"always"` | Выровнять по `"always"` либо поменять runtime fallback на `"motion"` |
| Кодирование JPEG на каждом кадре | `runtime/channel_runtime.py` | 576 | Выполняется всегда, даже когда никто не смотрит поток | Отслеживать число активных MJPEG-клиентов по каналу и не кодировать JPEG при `count = 0` |
| Чтение `reconnect_config` под lock на каждом кадре | `runtime/channel_runtime.py` | 417 | Берет `RLock` на каждой итерации цикла | Кэшировать локально; перечитывать только при необходимости, например после `_reopen_capture` |

---

## Сводка по количеству

| Категория | Количество |
|----------|------------|
| Можно безопасно удалить | 5 |
| Требует проверки | 4 |
| Нужен рефакторинг (а не удаление) | 14 |
