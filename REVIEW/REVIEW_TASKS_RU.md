# ANPR-System-v0.8_web — Независимые задачи на реализацию

**Дата:** 2026-03-18

Каждая задача самодостаточна, имеет четкую цель и не зависит от остальных.
Задачи отсортированы по влиянию (сначала самые важные).

---

## TASK-01 — Исправить утечку памяти: неограниченный рост track-словарей в пайплайне распознавания

**Проблема:**
`TrackAggregator.track_texts`, `last_emitted` и `TrackDirectionEstimator._history` — все структуры, индексируемые по `track_id` (`int`) — растут бесконечно. `track_id` никогда не удаляются. Через несколько дней работы словари уже содержат тысячи устаревших записей, что приводит к заметному росту RSS.

**Что изменить:**
1. В `TrackAggregator.__init__` заменить `self.track_texts: Dict[int, List[...]]` на `Dict[int, deque]`, где каждый `deque` имеет `maxlen=best_shots`. Удалить ручной `pop(0)` на строке 39.
2. Добавить `_track_last_seen: Dict[int, float]`, где хранится `time.monotonic()` для каждого трека, и обновлять это значение в каждом вызове `add_result`. В `add_result`, перед `return`, удалять записи, у которых `now - last_seen > STALE_TTL` (рекомендация: `max(30.0, best_shots * 2.0)` секунд).
3. В `TrackDirectionEstimator` добавить `_track_last_seen: Dict[int, float]`, обновляемый в `update()`. Перед возвратом результата удалять записи из `_history`, если они старше `history_size * 2` секунд (или использовать настраиваемый TTL).

**Затронутые файлы/модули:**
- `anpr/pipeline/anpr_pipeline.py` (`TrackAggregator`, `TrackDirectionEstimator`)

**Ожидаемый результат:**
Потребление памяти пайплайном распознавания стабилизируется после прогрева. При длительной работе больше не будет неограниченного роста словарей.

**Уровень риска:** Низкий — поведение для активных треков не меняется; удаляются только устаревшие записи.

---

## TASK-02 — Исправить утечку памяти: неограниченный рост cooldown-словаря в `ANPRPipeline`

**Проблема:**
`ANPRPipeline._last_seen: Dict[str, float]` накапливает по одной записи на каждый уникальный распознанный номер. Эти записи никогда не очищаются. За месяцы работы там могут накопиться тысячи уникальных номеров.

**Что изменить:**
В `ANPRPipeline._on_cooldown()` или `_touch_plate()` после обновления `_last_seen[plate]` проходить по словарю и удалять записи, где `now - ts > cooldown_seconds * 2`. Чтобы не делать O(n)-проход по словарю на каждом номере, запускать очистку только если `len(_last_seen) > threshold` (например, 500) либо по таймеру (например, раз в 60 секунд, используя `_last_pruned`).

**Затронутые файлы/модули:**
- `anpr/pipeline/anpr_pipeline.py` (`ANPRPipeline._on_cooldown`, `_touch_plate`)

**Ожидаемый результат:**
`_last_seen` будет ограничен примерно количеством номеров, активных в недавнем окне времени. Использование памяти стабилизируется.

**Уровень риска:** Низкий — удаляются только записи вне окна cooldown, то есть те, которые и так уже не влияют на логику cooldown.

---

## TASK-03 — Устранить двойной расчет ROI-полигона на каждый кадр

**Проблема:**
`_get_roi_polygon` (разбирает dict канала, переводит единицы измерения, строит `np.ndarray`) вызывается два раза на каждый обрабатываемый кадр:
1. Внутри `_apply_roi_mask` в `channel_runtime.py:275`
2. Внутри `_filter_detections_by_roi` в `channel_runtime.py:326`

**Что изменить:**
1. Удалить вызов `_apply_roi_mask` на строке 494. Это уберет и full-frame mask allocation, и первый расчет полигона.
2. В цикле `_run_channel` вычислять ROI-полигон один раз до вызова детектора: `roi_polygon = self._get_roi_polygon(frame.shape, channel)`.
3. Передавать `roi_polygon` напрямую в `_filter_detections_by_roi`, убрав внутренний вызов `_get_roi_polygon`.
4. Обновить сигнатуру `_filter_detections_by_roi`, чтобы она принимала опциональный заранее рассчитанный `roi_polygon: Optional[np.ndarray]`.

**Затронутые файлы/модули:**
- `runtime/channel_runtime.py` (`_run_channel`, `_apply_roi_mask`, `_filter_detections_by_roi`)

**Ожидаемый результат:**
Один расчет полигона на обрабатываемый кадр вместо двух. Не будет full-frame mask allocation. При 6 каналах × 25 fps это экономит около 150 построений полигона в секунду и убирает цепочку аллокаций примерно на ~8 МБ/кадр при включенном ROI.

**Уровень риска:** Низкий — функционально поведение не меняется, ROI-фильтрация по-прежнему выполняется через `_filter_detections_by_roi`.

---

## TASK-04 — Исправить `PlatePreprocessor`: перенести переиспользуемые объекты в `__init__`

**Проблема:**
`cv2.createCLAHE(...)` и `cv2.getStructuringElement(MORPH_RECT, (3,3))` вызываются при каждом `preprocess()`. Эти объекты статичны и каждый раз создаются одинаковыми.

**Что изменить:**
В `PlatePreprocessor.__init__` создать:
```python
self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
self._kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
```
А внутри метода заменить создание новых объектов на использование `self._clahe` и `self._kernel`.

**Затронутые файлы/модули:**
- `anpr/preprocessing/plate_preprocessor.py` (`PlatePreprocessor.__init__`, `preprocess`)

**Ожидаемый результат:**
Аллокация C++-объектов перестанет происходить на каждое распознавание. В сценариях с большим числом детекций это даст небольшой, но стабильный выигрыш по CPU.

**Уровень риска:** Очень низкий — CLAHE и kernel не имеют состояния, зависящего от конкретного вызова.

---

## TASK-05 — Векторизовать `CRNNRecognizer._decode_batch` (CTC greedy decoder)

**Проблема:**
CTC greedy decoder использует Python-цикл `for t in range(time_steps)`. Внутри цикла `torch.argmax` и `torch.exp(torch.max(...))` вызываются отдельно для каждого timestep-тензора, из-за чего происходит примерно `time_steps` device-to-host копирований на один элемент batch.

**Что изменить:**
Заменить поэтапный цикл на векторизованные операции:
```python
def _decode_batch(self, log_probs: torch.Tensor) -> List[Tuple[str, float]]:
    batch_probs = log_probs.permute(1, 0, 2)          # [batch, time, classes]
    char_indices = batch_probs.argmax(dim=-1)         # [batch, time]
    char_confs = batch_probs.exp().max(dim=-1).values # [batch, time]
    # Переносим в numpy для CTC-collapse (Python-цикл только по batch, не по time)
    indices_np = char_indices.cpu().numpy()           # [batch, time]
    confs_np = char_confs.cpu().numpy()               # [batch, time]
    results = []
    for b in range(indices_np.shape[0]):
        chars, confidences = [], []
        prev = 0
        for t, idx in enumerate(indices_np[b]):
            if idx != 0 and idx != prev:
                chars.append(self.int_to_char.get(int(idx), ""))
                confidences.append(float(confs_np[b, t]))
            prev = idx
        text = "".join(chars)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        results.append((text, avg_conf))
    return results
```
Ключевая идея: посчитать `argmax` и `exp(max)` в один векторизованный проход, сделать только один `.cpu().numpy()` на batch, а затем уже пройтись по `batch × time` в numpy — это существенно быстрее, чем дергать `.item()` на каждом шаге.

**Затронутые файлы/модули:**
- `anpr/recognition/crnn_recognizer.py` (`_decode_batch`)

**Ожидаемый результат:**
Меньше переходов между Python и C. Снижение времени декодирования, особенно при batch size > 1. Поведение алгоритма не меняется (это все тот же CTC greedy decode).

**Уровень риска:** Низкий — меняется только путь исполнения, алгоритм остается тем же. После правки нужно прогнать существующие тесты.

---

## TASK-06 — Заменить `list.pop(0)` на `deque` в `TrackAggregator`

**Проблема:**
`TrackAggregator.track_texts` хранит список результатов по каждому треку. Ограничение длины реализовано через `list.pop(0)`, а это O(n). Код находится в горячем пути распознавания.

**Что изменить:**
Сменить тип значения в `track_texts` с `List[tuple[str, float]]` на `deque[tuple[str, float]]` с `maxlen=self.best_shots`. Удалить ручную проверку длины и вызов `pop(0)`. Эта задача тесно связана с TASK-01 (можно делать вместе, но и отдельно она тоже полезна).

**Затронутые файлы/модули:**
- `anpr/pipeline/anpr_pipeline.py` (`TrackAggregator.__init__`, `add_result`)

**Ожидаемый результат:**
O(1) append и автоматическое вытеснение самой старой записи. Поведение не меняется.

**Уровень риска:** Очень низкий.

---

## TASK-07 — Увести DB-запрос plate-list у контроллера из потока канала

**Проблема:**
`ControllerAutomationService.dispatch_event` вызывается синхронно из потока канала (через `publish_event_sync` в `container.py:131`). Внутри `dispatch_event` функции `plate_in_list_type(plate, "black")` и `plate_in_list_type(plate, "white")` выполняют запросы к PostgreSQL. Эти запросы блокируют поток канала на 1–10 мс на каждое событие.

**Что изменить:**
В `AppContainer.publish_event_sync` планировать `dispatch_event` асинхронно, а не вызывать напрямую:
```python
def publish_event_sync(self, event: Dict[str, Any]) -> None:
    if self.main_loop and self.main_loop.is_running():
        self.main_loop.call_soon_threadsafe(asyncio.create_task, self.event_bus.publish(event))
        self.main_loop.call_soon_threadsafe(
            asyncio.create_task,
            asyncio.to_thread(self.controller_automation.dispatch_event, event)
        )
```
Так DB-запрос уйдет в thread pool и перестанет блокировать поток канала.

**Затронутые файлы/модули:**
- `app/api/container.py` (`publish_event_sync`)

**Ожидаемый результат:**
Поток канала возвращается из `publish_event_sync` сразу после планирования задач, не ожидая DB-запрос. Обработка кадров продолжается без лишней задержки.

**Уровень риска:** Низкий — relay-команда по-прежнему будет отправлена, просто с небольшой отсрочкой (на цикл event loop). Порядок обработки событий для relay сохраняется.

---

## TASK-08 — Исправить сохранение настроек: не перезапускать каналы при изменениях только в UI

**Проблема:**
`PUT /api/settings` всегда вызывает `restart_processor_for_settings()`, а это уничтожает и пересобирает весь `ChannelProcessor`, включая повторную загрузку YOLO и CRNN-моделей (~2–5 секунд). Из-за этого при сохранении UI-настроек вроде `grid` или `theme` все видеопотоки обрываются.

**Что изменить:**
1. В `put_global_settings` (`routers/settings.py`) сравнивать входящий payload с текущими настройками и определять, какие подсистемы действительно затронуты.
2. Явно определить, какие изменения требуют "pipeline restart required": `storage.postgres_dsn`, `plates`, любая конфигурация каналов, `reconnect`, настройки detector/OCR.
3. Изменения в `grid`, `theme`, `logging.level`, `time`, `debug` **не должны** вызывать `restart_processor_for_settings()`. Они должны применяться на месте.
4. При изменении `storage.postgres_dsn` вызывать только `refresh_storage_clients()`, а не пересобирать processor.
5. Изменения в `reconnect` должны вызывать только `processor.update_reconnect_settings()`.

**Затронутые файлы/модули:**
- `app/api/routers/settings.py` (`put_global_settings`)
- `app/api/container.py` (`restart_processor_for_settings`, `refresh_storage_clients`)

**Ожидаемый результат:**
Сохранение UI-настроек (grid, theme, log level) применяется мгновенно и не прерывает видеопотоки. Полный рестарт происходит только тогда, когда это действительно необходимо.

**Уровень риска:** Средний — нужно аккуратно определить, какие категории настроек требуют перезапуска. После правки важно протестировать каждую группу настроек.

---

## TASK-09 — Удалить мертвый код: `CRNNRecognizer.recognize` и `TrackAggregator.clear_last`

**Проблема:**
`CRNNRecognizer.recognize()` (строка 78) и `TrackAggregator.clear_last()` (строка 65) нигде в кодовой базе не вызываются. Это мертвый код.

**Что изменить:**
1. Удалить метод `CRNNRecognizer.recognize` (`crnn_recognizer.py:78-82`).
2. Удалить метод `TrackAggregator.clear_last` (`anpr_pipeline.py:65-66`).
3. Прогнать тесты и убедиться, что ничего не сломалось.

**Затронутые файлы/модули:**
- `anpr/recognition/crnn_recognizer.py`
- `anpr/pipeline/anpr_pipeline.py`

**Ожидаемый результат:**
Кодовая база станет чуть меньше и чище, исчезнет двусмысленность по поводу того, какой метод использовать для OCR одного изображения.

**Уровень риска:** Очень низкий — неиспользование подтверждено. Перед удалением все же полезно выполнить `grep -r "clear_last\|\.recognize(" .`.

---

## TASK-10 — Добавить минимальную проверку размера crop в `PlatePreprocessor.preprocess`

**Проблема:**
`PlatePreprocessor.preprocess` проверяет только `plate_image.size == 0`. Для очень маленьких crop (например, 30×8 пикселей у далекой машины) он все равно запускает полный пайплайн preprocessing-а (CLAHE, threshold, поиск контуров, Hough transform), хотя результат бессмысленный и только тратит CPU.

**Что изменить:**
В начале `preprocess()` добавить:
```python
if plate_image.size == 0:
    return plate_image
h, w = plate_image.shape[:2]
if w < 20 or h < 8:
    return plate_image   # Слишком маленький crop для preprocessing; resize пусть делает CRNN
```

**Затронутые файлы/модули:**
- `anpr/preprocessing/plate_preprocessor.py` (`preprocess`)

**Ожидаемый результат:**
Очень маленькие crop будут пропускать дорогой preprocessing. Встроенный resize внутри CRNN с ними и так справится. Это слегка уменьшит CPU-нагрузку на дальних/мелких детекциях.

**Уровень риска:** Очень низкий — CRNN и так умеет работать с входами любого размера. Crop ниже этого порога все равно дает плохой OCR.

---

## TASK-11 — Выровнять `detection_mode` defaults между schema и runtime

**Проблема:**
`ChannelConfigPayload.detection_mode` по умолчанию имеет `"motion"` (schema default). В `channel_runtime.py` на строке 366 используется fallback `"always"`, если поле отсутствует в dict канала. Новый канал (через `POST /api/channels`) создается без сохраненного `detection_mode`, поэтому runtime берет `"always"`, но после сохранения формы настроек туда записывается `"motion"`. Это скрытая несогласованность.

**Что изменить:**
Вариант A (рекомендуется): поменять default `ChannelConfigPayload.detection_mode` с `"motion"` на `"always"`, чтобы он совпадал с runtime default.  
Вариант B: поменять runtime fallback в `channel_runtime.py:366` с `"always"` на `"motion"`.

Нужно выбрать один вариант и применить его последовательно во всей системе. Дополнительно: после `POST /api/channels` заполнять все конфигурационные поля значениями по умолчанию (из `ChannelConfigPayload`), чтобы сохраняемый dict был полным.

**Затронутые файлы/модули:**
- `app/api/schemas.py` (`ChannelConfigPayload.detection_mode`)
- `runtime/channel_runtime.py` (строка 366, fallback value)

**Ожидаемый результат:**
Новые каналы всегда ведут себя одинаково — независимо от того, были ли поля явно сохранены или используются defaults.

**Уровень риска:** Низкий — это только выравнивание значений по умолчанию. Существующие каналы, где `detection_mode` уже явно задан, не пострадают.

---

## TASK-12 — Не кодировать JPEG-превью, когда никто не смотрит поток

**Проблема:**
`cv2.imencode('.jpg', frame, ...)` выполняется на каждом кадре для каждого канала, даже если к MJPEG-потоку не подключен ни один браузер. Для 4 каналов при 25 fps и 1080p это дает существенную нагрузку на CPU (5–15 мс на одно кодирование).

**Что изменить:**
1. Добавить `active_preview_clients: int = 0` в `ChannelContext`.
2. В генераторе `channel_preview_stream`: увеличивать `active_preview_clients` при подключении и уменьшать в `finally` при отключении клиента.
3. В `_run_channel` на строке 575 проверять `if ctx.active_preview_clients > 0` перед кодированием. Условие с `disable_video_output` можно упростить — кодировать только если есть хотя бы один активный viewer.
4. Обновить `get_preview_frame`, чтобы он возвращал `None`, если `active_preview_clients == 0` (snapshot endpoint при этом можно кодировать по требованию отдельно).

Примечание: `channel_snapshot` (разовый JPEG по запросу) может кодировать изображение отдельно и независимо от MJPEG-потока.

**Затронутые файлы/модули:**
- `runtime/channel_runtime.py` (`ChannelContext`, `_run_channel`)
- `app/api/routers/channels.py` (`channel_preview_stream`)

**Ожидаемый результат:**
Если никто не смотрит превью, затраты CPU на JPEG encoding становятся нулевыми. Как только клиент подключается, кодирование сразу возобновляется.

**Уровень риска:** Средний — потребуется синхронизировать API-поток (счетчик клиентов) и поток канала (решение о кодировании). Используйте атомарный счетчик или lock-protected counter внутри `ChannelContext`.

---

## TASK-13 — Заменить polling в `DebugLogBus` на async subscriber queue

**Проблема:**
`stream_debug_logs` использует `asyncio.to_thread(debug_log_bus.wait_for_entries, cursor, 15.0)`, из-за чего один поток из thread pool может блокироваться до 15 секунд на каждого подключенного SSE-клиента. При нескольких клиентах debug panel такие потоки будут висеть постоянно.

**Что изменить:**
Добавить в `DebugLogBus` асинхронный механизм подписки, аналогичный `EventBus`:
1. Добавить методы `subscribe() -> asyncio.Queue` и `unsubscribe(queue)`.
2. В `publish()` помимо ring buffer отправлять записи во все subscriber queues.
3. В `stream_debug_logs` использовать `await queue.get()` с timeout (как в SSE-потоке `EventBus`).
4. Удалить `wait_for_entries` либо оставить его только для не-SSE сценариев, например для snapshot.

**Затронутые файлы/модули:**
- `runtime/debug.py` (`DebugLogBus`)
- `app/api/routers/debug.py` (`stream_debug_logs`)

**Ожидаемый результат:**
Thread pool перестанет удерживать заблокированные потоки на каждого SSE-клиента debug-лога. Использование ресурсов станет заметно эффективнее.

**Уровень риска:** Средний — меняется модель взаимодействия `DebugLogBus` с клиентами. Нужно убедиться, что существующие вызовы `snapshot()` и `wait_for_entries` (если они еще используются) не ломаются.

---

## TASK-14 — Объединить `dispatch_event` / `handle_event` в `ControllerAutomationService`

**Проблема:**
`dispatch_event` — это однострочная обертка над `handle_event`, которая добавляет только логирование исключений. Такая прослойка не дает смысловой пользы и создает путаницу, какой метод считать основным.

**Что изменить:**
Перенести тело `handle_event` прямо в `dispatch_event`. Удалить `handle_event` как отдельный метод. Убедиться, что `try/except`, который сейчас находится в `dispatch_event`, охватывает все бывшее тело `handle_event`.

**Затронутые файлы/модули:**
- `controllers/service.py` (`ControllerAutomationService`)

**Ожидаемый результат:**
Останется один, однозначно названный метод `dispatch_event`, внутри которого будет вся логика.

**Уровень риска:** Очень низкий — это чисто структурное изменение без изменения поведения.

---

## TASK-15 — Разделить `app/api/routers/settings.py` на `settings.py` и `data.py`

**Проблема:**
Роутер `settings.py` содержит маршруты для двух разных областей ответственности:  
(1) глобальные настройки приложения (`/api/settings`) и  
(2) управление жизненным циклом данных (`/api/data/policy`, `/api/data/retention/run`, `/api/data/export/*`).  
Из-за этого имя файла вводит в заблуждение.

**Что изменить:**
1. Создать `app/api/routers/data.py`, куда перенести:
   - `GET/PUT /api/data/policy`
   - `POST /api/data/retention/run`
   - `GET /api/data/export/events.csv`
   - `POST /api/data/export/bundle`
2. Оставить в `app/api/routers/settings.py` только `GET/PUT /api/settings`.
3. Импортировать и подключить `data_router` в `app/api/main.py`.

**Затронутые файлы/модули:**
- `app/api/routers/settings.py` (сократить)
- `app/api/routers/data.py` (создать)
- `app/api/main.py` (добавить импорт)

**Ожидаемый результат:**
Более чистая организация роутеров. Экспорт и retention станет проще находить по структуре проекта.

**Уровень риска:** Очень низкий — URL-пути не меняются, меняется только организация файлов.
