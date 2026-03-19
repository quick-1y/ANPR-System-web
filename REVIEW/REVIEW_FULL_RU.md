# ANPR-System-v0.8_web — Полное архитектурное и эксплуатационное ревью

**Дата:** 2026-03-18  
**Охват:** Полный обзор кодовой базы — архитектура, нейминг, неиспользуемый/легаси-код, утечки памяти, производительность CPU, пайплайн распознавания.

---

## 1. Краткое резюме

### Качество общей архитектуры

Проект хорошо организован под свои задачи. Разделение зон ответственности понятное: ANPR-пайплайн, runtime каналов, API-слой, база данных и конфигурация вынесены в отдельные модули с ясными интерфейсами. Основной архитектурный подход — один блокирующий поток на канал, асинхронный SSE для событий, единый YAML-конфиг и PostgreSQL как единственное хранилище — выглядит здраво и подходит для локального развертывания.

Кодовая база не выглядит захламленной: не найдено легаси-хлама, мертвых импортов или закомментированных блоков. Нейминг в целом хороший. Пайплайн `YOLO → preprocessor → batch OCR через CRNN → aggregator → validator → cooldown → event` построен логично.

**Но** в пайплайне распознавания есть три подтвержденные утечки памяти, из-за которых процесс будет расти бесконечно при непрерывной работе. Кроме того, в per-frame hot path есть несколько CPU-неэффективностей, которые суммарно начинают сильно влиять на нагрузку при нескольких каналах и нормальном FPS.

### Основные риски

| Риск | Локация | Влияние |
|------|---------|---------|
| Утечка памяти — неограниченный рост track-словарей | `anpr_pipeline.py` | Процесс бесконечно растет |
| Утечка памяти — неограниченная history для direction estimator | `anpr_pipeline.py:149` | Процесс бесконечно растет |
| Утечка памяти — неограниченный cooldown dict | `anpr_pipeline.py:193` | Медленный рост памяти в течение дней |
| ROI-полигон вычисляется дважды на каждый кадр | `channel_runtime.py:275, 326` | Постоянно тратит CPU |
| На каждый кадр создается full-frame mask | `channel_runtime.py:274-281` | Лишние аллокации + `bitwise AND` |
| `list.pop(0)` в hot path aggregation | `anpr_pipeline.py:39` | Производительность падает при больших `best_shots` |
| CRNN decode: Python-цикл по каждому timestep | `crnn_recognizer.py:95-104` | Не дает распараллеливанию PyTorch нормально раскрыться |
| DB-запрос блокирует поток канала на каждом событии | `container.py:131`, `service.py:150` | Тормозит обработку кадров |
| Lock contention на каждом кадре | `channel_runtime.py:417, 579` | Лишняя сериализация потоков |

### Наиболее приоритетные действия

1. Исправить три неограниченно растущих словаря в `ANPRPipeline` — это подтвержденные утечки памяти.
2. Убрать двойной расчет ROI-полигона и избыточный full-frame masking.
3. Заменить `list.pop(0)` на `deque(maxlen=N)` в `TrackAggregator`.
4. Векторизовать `_decode_batch` в `CRNNRecognizer`.
5. Увести DB-проверку plate-list у контроллера из потока канала.

---

## 2. Полный отчет

---

### 2.1 Архитектурные слабые места

---

#### AW-1 — Неограниченно растущие dict-структуры в `ANPRPipeline` и `TrackAggregator`

**Серьезность:** Критично  
**Уверенность:** Высокая  
**Доказательства:**

```python
# anpr_pipeline.py:30-31
self.track_texts: Dict[int, List[tuple[str, float]]] = {}
self.last_emitted: Dict[int, str] = {}

# anpr_pipeline.py:149
history = self._history.setdefault(track_id, deque(maxlen=self.history_size))

# anpr_pipeline.py:193
self._last_seen: Dict[str, float] = {}
```

`TrackAggregator.track_texts` и `last_emitted` индексируются по `track_id` (целочисленный идентификатор, выдаваемый YOLO ByteTrack). Эти ключи никогда не удаляются. Каждый новый автомобиль оставляет в словаре постоянную запись. Через несколько дней работы там уже могут быть тысячи устаревших track-id.

`TrackDirectionEstimator._history` также индексируется по `track_id`, и проблема аналогичная: каждый новый трек создает новый `deque`, который затем никогда не удаляется.

`ANPRPipeline._last_seen` индексируется по строке распознанного номера. Каждый уникальный номер оставляет новую запись. Логика cooldown обращается к этому словарю, но ничего из него не удаляет. Со временем таких записей становится очень много.

`TrackAggregator.reset(track_id)` и `clear_last(track_id)` существуют, но не вызываются в момент исчезновения трека. `reset` используется только при неуспешной plate-validation (`anpr_pipeline.py:260`). `clear_last` вообще нигде не вызывается.

**Почему это проблема:**
В рабочей установке, где в день проходит много автомобилей, словари будут расти непрерывно. Через 30 дней `_last_seen` может содержать 10 000+ записей; `track_texts` и `_history` — еще больше, особенно если после reconnect YOLO/ByteTrack заново переиспользует счетчик ID. RSS процесса будет расти заметно и без верхней границы.

**Рекомендуемое исправление:**
- Заменить значения `track_texts` с `List[...]` на `deque(maxlen=best_shots)`.
- Добавить TTL-эвикцию или LRU-эвикцию для `track_texts`, `last_emitted` и `_history` через `time.monotonic()`.
- Для `_last_seen` удалять записи старше `cooldown_seconds * 2` внутри `_on_cooldown`.

---

#### AW-2 — ROI-полигон вычисляется дважды на каждый кадр

**Серьезность:** Высокая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# channel_runtime.py:494
detector_frame = self._apply_roi_mask(frame, channel)

# channel_runtime.py:275-281 (_apply_roi_mask)
def _apply_roi_mask(self, frame, channel):
    roi_polygon = self._get_roi_polygon(frame.shape, channel)  # ← parse + compute #1
    ...

# channel_runtime.py:518
detections = self._filter_detections_by_roi(detections, frame.shape, channel)

# channel_runtime.py:326 (_filter_detections_by_roi)
def _filter_detections_by_roi(self, detections, frame_shape, channel):
    roi_polygon = self._get_roi_polygon(frame_shape, channel)  # ← parse + compute #2
    ...
```

`_get_roi_polygon` разбирает dict канала, читает `roi_enabled`, `region`, `points`, переводит проценты в пиксели и строит `np.array`. Сейчас этот расчет выполняется дважды на одном и том же кадре.

**Почему это проблема:**
Это чисто лишнее вычисление на каждом кадре. На системе с 6 каналами и 25 fps, при `detector_frame_stride=1`, это около 150 лишних построений полигона в секунду.

**Рекомендуемое исправление:**
Посчитать `roi_polygon` один раз и передавать его в оба места использования. Либо кэшировать полигон по каналу и инвалидировать кэш при изменении конфигурации канала.

---

#### AW-3 — Для ROI на каждом кадре создается full-frame mask

**Серьезность:** Высокая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# channel_runtime.py:279-281
mask = np.zeros(frame.shape[:2], dtype=np.uint8)
cv2.fillPoly(mask, [roi_polygon], 255)
return cv2.bitwise_and(frame, frame, mask=mask)
```

При включенном ROI код создает полноразмерный grayscale-mask массив, заливает в нем полигон и выполняет `bitwise_and` по всему BGR-кадру. Для 1080p кадра это уже заметная память и заметный объем работы на каждый кадр.

Этот masking изначально, вероятно, задумывался как ограничение области для YOLO. Но ниже все равно используется `_filter_detections_by_roi`, который отбрасывает детекции по центру bbox внутри полигона. Если цель только в фильтрации детекций, full-frame mask здесь избыточен.

**Почему это проблема:**
На 4 каналах при 25 fps это означает сотни мегабайт в секунду лишней memory bandwidth и лишнюю работу CPU без явного выигрыша в поведении системы.

**Рекомендуемое исправление:**
Убрать `_apply_roi_mask` из hot path и оставить только `_filter_detections_by_roi`. Если masking нужен именно ради влияния на поведение YOLO/NMS, это нужно явно задокументировать и отдельно обосновать.

---

#### AW-4 — Проверка plate-list у контроллера блокирует поток канала на каждом событии

**Серьезность:** Высокая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# container.py:128-131
def publish_event_sync(self, event) -> None:
    if self.main_loop and self.main_loop.is_running():
        self.main_loop.call_soon_threadsafe(asyncio.create_task, self.event_bus.publish(event))
    self.controller_automation.dispatch_event(event)  # ← synchronous DB call

# service.py:150
def _resolve_channel_controller_action(self, channel, plate):
    if self._plate_in_list_type(plate, "black"):   # ← psycopg query
        return False, "blacklisted"
    ...
    if self._plate_in_list_type(plate, "white"):   # ← psycopg query
```

`dispatch_event` вызывается синхронно из `publish_event_sync`, который сам является `event_callback` для `ChannelProcessor`. То есть этот код выполняется прямо в потоке канала. Внутри `_plate_in_list_type` выполняется прямой PostgreSQL-запрос.

**Почему это проблема:**
Даже 1–10 мс на DB-запрос уже тормозит чтение следующего кадра в потоке канала. Под нагрузкой или при вынесенной БД это начнет вызывать задержки, просадки FPS и потенциальные frame drops.

**Рекомендуемое исправление:**
Увести `dispatch_event` в background thread или async task. Самый простой вариант — запускать его через event loop, как уже делается для `event_bus.publish`, а сам DB-код отправлять в `asyncio.to_thread`.

---

#### AW-5 — `reconnect_config` читается под lock на каждой итерации цикла кадра

**Серьезность:** Средняя  
**Уверенность:** Высокая  
**Доказательства:**

```python
# channel_runtime.py:417
while not stop_event.is_set():
    reconnect_config = self.get_reconnect_config()  # acquires RLock on every frame
```

```python
# channel_runtime.py:102-104
def get_reconnect_config(self) -> ReconnectConfig:
    with self._lock:
        return self._reconnect_config
```

Настройки reconnect меняются только при явном сохранении пользователем. Но сейчас они перечитываются под lock на каждой итерации цикла кадра — потенциально 25–30 раз в секунду на канал.

**Почему это проблема:**
Одна операция lock дешевая, но их много. На многоканальной системе это создает бессмысленную конкуренцию за `_lock` между API-потоками и потоками каналов.

**Рекомендуемое исправление:**
Хранить `reconnect_config` локально в цикле и перечитывать его только после reconnect-событий или при других действительно нужных точках синхронизации.

---

#### AW-6 — `_run_channel` берет `_lock` при каждой записи JPEG

**Серьезность:** Средняя  
**Уверенность:** Высокая  
**Доказательства:**

```python
# channel_runtime.py:579-583
with self._lock:
    channel_ctx = self._contexts.get(channel_id)
    if channel_ctx:
        channel_ctx.latest_jpeg = preview_buf.tobytes()
        channel_ctx.latest_frame_ts = now_ts
```

Один и тот же `_lock` используется сразу для нескольких задач: для управления contexts, для чтения reconnect-настроек и для записи превью JPEG. Все потоки каналов и API-потоки, которые читают превью, конкурируют за один глобальный lock.

**Рекомендуемое исправление:**
Использовать отдельный `Lock` на канал для операций с JPEG-буфером либо выделить отдельный lock именно для `ChannelContext`. Это заметно сократит cross-channel contention.

---

#### AW-7 — `dispatch_event` и `handle_event`: лишний уровень косвенности

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# service.py:216-220
def dispatch_event(self, event):
    try:
        self.handle_event(event)
    except Exception as exc:
        logger.error("controller binding processing failed: %s", exc)
```

`dispatch_event` — это тонкая обертка, которая добавляет только `try/except` и логирование. По сути это лишний уровень вызова без самостоятельной смысловой ценности.

**Рекомендуемое исправление:**
Оставить один `dispatch_event`, а логику из `handle_event` встроить прямо внутрь него.

---

### 2.2 Проблемы структуры директорий

---

#### DS-1 — `app/api/routers/settings.py` смешивает настройки и маршруты жизненного цикла данных

**Серьезность:** Средняя  
**Уверенность:** Высокая  

`app/api/routers/settings.py` содержит:
- `GET /api/settings`, `PUT /api/settings` — глобальные настройки
- `GET /api/data/policy`, `PUT /api/data/policy` — retention policy
- `POST /api/data/retention/run` — ручной запуск retention
- `GET /api/data/export/events.csv` — экспорт событий
- `POST /api/data/export/bundle` — экспорт bundle

Имя файла — `settings.py`, но большая часть маршрутов относится не к настройкам, а к жизненному циклу данных и экспорту. Это ухудшает навигацию по проекту.

**Рекомендуемое исправление:**
Разделить это на `settings.py` (только `/api/settings`) и `data.py` (retention + export), а затем подключить оба router в `main.py`.

---

#### DS-2 — В `app/shared/` лежит только один файл

**Серьезность:** Низкая  
**Уверенность:** Высокая  

В `app/shared/` фактически находятся только `__init__.py` и `data_lifecycle.py`. Название `shared` намекает на набор общих утилит, но по факту там только один модуль.

**Рекомендуемое исправление:**
Либо перенести `data_lifecycle.py` уровнем выше, либо переименовать папку во что-то более предметное, например `app/lifecycle/`. Это не срочно, но для чистоты структуры полезно.

---

### 2.3 Проблемы нейминга

---

#### NI-1 — `ChannelConfigPayload.detection_mode` default не совпадает с runtime default

**Серьезность:** Средняя  
**Уверенность:** Высокая  
**Доказательства:**

```python
# schemas.py:36
detection_mode: str = Field(default="motion", pattern="^(always|motion)$")

# channel_runtime.py:366
detection_mode_raw = str(channel.get("detection_mode", "always")).strip().lower()
```

Схема API по умолчанию использует `"motion"`, а runtime при отсутствии поля использует `"always"`. Новый канал, созданный через `POST /api/channels`, этого поля вообще не имеет, поэтому runtime будет работать как `"always"`. Но после сохранения формы настроек канал уже получает `"motion"`.

**Рекомендуемое исправление:**
Выровнять оба defaults к одному значению. Практичнее оставить `"always"` как более безопасное runtime-поведение и под него поправить schema default.

---

#### NI-2 — `ChannelFilterPayload` использует сырой `Dict[str, int]` для размеров номера

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# schemas.py:71-72
min_plate_size: Dict[str, int] = {"width": 80, "height": 20}
max_plate_size: Dict[str, int] = {"width": 600, "height": 240}
```

В `ChannelConfigPayload` для тех же данных используется `PlateSizePayload` — нормальная Pydantic-модель с валидацией. В `ChannelFilterPayload` — обычный словарь.

**Рекомендуемое исправление:**
Использовать `PlateSizePayload` и здесь, чтобы типы и валидация были единообразными.

---

#### NI-3 — Имена методов `handle_event` / `dispatch_event` в `ControllerAutomationService`

**Серьезность:** Низкая  
**Уверенность:** Высокая  

`handle_event` содержит реальную логику, а `dispatch_event` — только тонкую обертку с логированием. Внешний код вызывает `dispatch_event`, но смыслового выигрыша от разделения нет.

---

#### NI-4 — `TrackAggregator.clear_last` — неудачное название и при этом неиспользуемый метод

**Серьезность:** Низкая  
**Уверенность:** Высокая  

`clear_last` очищает только `last_emitted`, но не трогает `track_texts`. Это частичный reset с неочевидным названием. При этом метод вообще нигде не вызывается.

**Рекомендуемое исправление:**
Удалить `clear_last`. Для полного сброса уже есть `reset`.

---

### 2.4 Неиспользуемые модули / файлы / код

---

#### UN-1 — `CRNNRecognizer.recognize` (single-image method) — мертвый код

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# crnn_recognizer.py:78-82
@torch.no_grad()
def recognize(self, plate_image) -> Tuple[str, float]:
    batch_result = self.recognize_batch([plate_image])
    if not batch_result:
        return "", 0.0
    return batch_result[0]
```

Основной код использует `recognize_batch`, а single-image `recognize` нигде не вызывается. Это просто обертка над `recognize_batch([img])[0]`.

**Рекомендуемое исправление:**
Удалить `recognize`. Если когда-то снова понадобится single-image OCR, его легко получить через `recognize_batch([img])[0]`.

---

#### UN-2 — `TrackAggregator.clear_last` — мертвый код

**Серьезность:** Низкая  
**Уверенность:** Высокая  

Метод определен, но не вызывается нигде в кодовой базе.

---

#### UN-3 — `log_perf_stage` в `common/logging.py` — вероятно не используется

**Серьезность:** Низкая  
**Уверенность:** Средняя  
**Доказательства:**

```python
# common/logging.py:277-288
def log_perf_stage(logger, channel, stage, duration_ms, level=logging.DEBUG, **extra):
    ...
```

Функция определена, но в просмотренном коде не нашлось ее вызовов. При этом timing уже учитывается через `DebugRegistry.update_stage_timings`.

**Рекомендуемое исправление:**
Сначала проверить через `grep` по всему проекту, и только после этого удалять.

---

#### UN-4 — Словарь `CONTROLLER_TYPES` в `controllers/service.py`

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# service.py:14-16
CONTROLLER_TYPES = OrderedDict([
    ("DTWONDER2CH", "DTWONDER2CH"),
])
SUPPORTED_CONTROLLER_TYPES = tuple(CONTROLLER_TYPES.keys())
```

Этот словарь содержит всего одну запись, причем ключ и значение совпадают. По сути он нужен только ради `SUPPORTED_CONTROLLER_TYPES`. Но список поддерживаемых адаптеров уже есть в `controllers/registry.py`.

**Рекомендуемое исправление:**
Получать `SUPPORTED_CONTROLLER_TYPES` напрямую из `CONTROLLER_ADAPTERS.keys()` и убрать лишнюю параллельную структуру.

---

### 2.5 Легаси-код

Легаси-код не обнаружен. В проекте нет закомментированных исторических блоков, deprecated compatibility shims или подобных следов старых итераций. Миграция настроек выглядит минимальной и оправданной.

---

### 2.6 Риски производительности и памяти

---

#### PM-1 — `TrackAggregator` использует `list.pop(0)` — O(n) в hot path

**Серьезность:** Высокая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# anpr_pipeline.py:37-40
bucket = self.track_texts.setdefault(track_id, [])
bucket.append((text, max(0.0, float(confidence))))
if len(bucket) > self.best_shots:
    bucket.pop(0)   # ← O(n) list shift
```

`list.pop(0)` у Python — операция O(n), потому что все оставшиеся элементы приходится сдвигать. При `best_shots=3` это еще терпимо, но при больших значениях и высокой частоте OCR-вызовов лишняя работа становится заметной.

**Рекомендуемое исправление:**
Заменить список на `deque(maxlen=self.best_shots)`, чтобы и добавление, и вытеснение были O(1).

---

#### PM-2 — `PlatePreprocessor` создает CLAHE и kernel на каждом вызове

**Серьезность:** Средняя  
**Уверенность:** Высокая  
**Доказательства:**

```python
# plate_preprocessor.py:149-156 (called on every detection)
clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
enhanced = clahe.apply(gray)
blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
thresh = cv2.adaptiveThreshold(...)
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=1)
```

`cv2.createCLAHE` создает C++-объект OpenCV, а `cv2.getStructuringElement` — новый numpy-массив. Оба объекта всегда одинаковы, но пересоздаются на каждом `preprocess()`.

**Рекомендуемое исправление:**
Создавать `_clahe` и `_kernel` один раз в `__init__` и переиспользовать их.

---

#### PM-3 — `CRNNRecognizer._decode_batch` — Python-цикл на каждый timestep

**Серьезность:** Высокая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# crnn_recognizer.py:95-104
for t in range(time_steps):
    timestep_log_probs = probs[t]
    char_idx = int(torch.argmax(timestep_log_probs).item())
    char_conf = float(torch.exp(torch.max(timestep_log_probs)).item())
    if char_idx != 0 and char_idx != last_char_idx:
        decoded_chars.append(self.int_to_char.get(char_idx, ""))
        char_confidences.append(char_conf)
    last_char_idx = char_idx
```

На каждом timestep вызывается `.item()`, что вынуждает перенос значений с device на host. Плюс `argmax` и `max` вычисляются отдельно по одному и тому же тензору. В результате Python-часть забирает слишком много времени и ухудшает эффект от batch-обработки.

**Рекомендуемое исправление:**
Векторизовать greedy decoder:
```python
# Vectorized equivalent (pseudo-code):
indices = probs.argmax(dim=-1)  # shape: [batch, time]
max_probs = probs.exp().max(dim=-1).values  # shape: [batch, time]
# Then iterate over batch dimension only, using numpy on .cpu().numpy()
```

---

#### PM-4 — `recognize_batch` принудительно материализует list только ради empty-check

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# crnn_recognizer.py:69-71
plate_images = list(plate_images)
if not plate_images:
    return []
```

На текущем callsite в `anpr_pipeline.py` туда и так всегда передается `List[np.ndarray]`. То есть `list(plate_images)` — фактически лишняя копия списка.

**Рекомендуемое исправление:**
Либо сменить сигнатуру на `List[np.ndarray]` и убрать `list()`, либо работать с `Iterable` честно, без безусловной полной материализации.

---

#### PM-5 — `cleanup_stale` вызывается избыточно на каждом кадре

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# channel_runtime.py:456 — on failed read
self._debug_registry.cleanup_stale(channel_id)

# channel_runtime.py:491 — on empty frame
self._debug_registry.cleanup_stale(channel_id)

# channel_runtime.py:498 — on every good frame (unconditional)
self._debug_registry.cleanup_stale(channel_id)

# channel_runtime.py:520 — inside update_from_detections (also calls _cleanup_stale_locked)
self._debug_registry.update_from_detections(...)  # calls _cleanup_stale_locked internally
```

На успешно обработанном кадре `cleanup_stale` вызывается явно один раз, а затем почти сразу еще раз внутри `update_from_detections`.

**Рекомендуемое исправление:**
Убрать явный вызов на строке 498 в тех ветках, где затем все равно вызывается `update_from_detections`.

---

#### PM-6 — Двойной вызов `mkdir` на каждое событие

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# channel_runtime.py:242-247 (_build_event_media_paths)
day_dir = self._screenshots_dir / event_ts.strftime("%Y-%m-%d") / f"channel_{channel_id}"
day_dir.mkdir(parents=True, exist_ok=True)    # ← mkdir #1
...

# channel_runtime.py:252-253 (_save_jpeg)
def _save_jpeg(self, path, image):
    ...
    path.parent.mkdir(parents=True, exist_ok=True)  # ← mkdir #2 (same dir)
```

Директория создается в `_build_event_media_paths`, а затем еще раз создается в `_save_jpeg`, хотя это уже та же самая папка.

**Рекомендуемое исправление:**
Оставить `mkdir` только в одном месте.

---

#### PM-7 — `ControllerService.send_command` создает новый thread на каждую команду

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# service.py:111-113
thread = threading.Thread(target=_dispatch, name=f"controller-{controller_name}", daemon=True)
thread.start()
return url
```

Каждая relay-команда порождает новый `Thread`. Стоимость создания потока невелика, но при серии событий это все равно лишняя работа и отсутствие верхней границы по числу создаваемых потоков.

**Рекомендуемое исправление:**
Использовать один daemon-thread с очередью на контроллер либо `ThreadPoolExecutor` с маленьким фиксированным pool size.

---

#### PM-8 — `HourlyFileHandler._open_stream` вызывается на каждую запись в лог

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# common/logging.py:81-88 (emit)
def emit(self, record):
    try:
        message = self.format(record)
        with self._lock:
            self._open_stream(datetime.now().astimezone())   # ← called every record
```

Внутри `_open_stream` есть early return, если период не изменился, поэтому это не критичная проблема. Но `datetime.now().astimezone()` и захват lock все равно происходят на каждом лог-сообщении.

**Рекомендуемое исправление:**
Кэшировать ближайшее время ротации и вызывать `_open_stream` только при его достижении.

---

#### PM-9 — `DebugLogBus.wait_for_entries` удерживает thread pool thread до 15 секунд

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# debug.py:375-379
def wait_for_entries(self, last_id, timeout=15.0):
    with self._condition:
        if self._seq <= last_id:
            self._condition.wait(timeout=timeout)    # ← blocks for up to 15s

# app/api/routers/debug.py:67
items = await asyncio.to_thread(container.debug_log_bus.wait_for_entries, cursor, 15.0)
```

На каждого SSE-клиента debug-лога может удерживаться отдельный поток thread pool, который просто спит в ожидании данных.

**Рекомендуемое исправление:**
Перейти на `asyncio.Queue` для подписчиков, как уже сделано в `EventBus`.

---

### 2.7 Возможности CPU-оптимизации

---

#### CO-1 — JPEG кодируется на каждом кадре, независимо от числа зрителей

**Серьезность:** Средняя  
**Уверенность:** Высокая  
**Доказательства:**

```python
# channel_runtime.py:576
ok_enc, preview_buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
```

JPEG-encoding выполняется даже тогда, когда никакой браузер не открыт и никто не смотрит поток. Флаг `disable_video_output` помогает только вручную, но автоматической привязки к реальному числу viewers нет.

**Рекомендуемое исправление:**
Вести счетчик `active_preview_clients` на канал и не кодировать JPEG, когда счетчик равен нулю.

---

#### CO-2 — YOLO работает на каждом кадре при `detector_frame_stride=1`

**Серьезность:** Средняя  
**Уверенность:** Высокая  
**Доказательства:**

```python
# channel_runtime.py:511
if detector_input_frames % detector_frame_stride != 0:
    metrics.detector_skipped_frames += 1
    should_process = False
```

Если `detector_frame_stride=1`, детектор запускается на каждом кадре. На CPU это может быть очень дорого. При этом schema default для `detector_frame_stride` — `2`, а runtime fallback в одном из путей ведет себя как `1`, что создает лишнюю нагрузку на каналы по умолчанию.

**Рекомендуемое исправление:**
Выровнять runtime default с schema default и использовать `2` как безопасное значение по умолчанию.

---

#### CO-3 — Motion detector обрабатывает каждый кадр при `motion_frame_stride=1`

**Серьезность:** Средняя  
**Уверенность:** Средняя  

При `detection_mode="motion"` motion detector вызывается очень часто, и сам по себе он не бесплатен: grayscale, GaussianBlur, frame diff, threshold. Здесь нужен дополнительный просмотр того, насколько хорошо уже работает внутренний `frame_stride` внутри `MotionDetector.update()`.

**Примечание:**
Это скорее наблюдение, чем подтвержденный баг. Стоит отдельно проверить, насколько эффективно уже используется `motion_frame_stride` в реальной реализации.

---

#### CO-4 — Нет раннего выхода из `process_frame`, когда список detections пуст

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# anpr_pipeline.py:207-230
def process_frame(self, frame, detections):
    plate_inputs = []
    detection_indices = []
    for idx, detection in enumerate(detections):
        ...
    batch_results = self.recognizer.recognize_batch(plate_inputs)
```

Когда `detections` пуст, функция все равно подготавливает списки и вызывает `recognize_batch([])`, который затем быстро возвращает `[]`.

**Рекомендуемое исправление:**
Добавить `if not detections: return []` в самом начале `process_frame`.

---

### 2.8 Наблюдения по пайплайну распознавания

---

#### RP-1 — Полный путь обработки, по шагам

```text
Чтение кадра (cv2.VideoCapture.read)
  │
  ├─ FAIL/EMPTY → логика reconnect, кадр пропускается
  │
  ├─ ROI masking (_apply_roi_mask) [если roi_enabled]
  │    └─ считает полигон #1, выделяет mask, выполняет bitwise_and
  │
  ├─ Motion detection (MotionDetector.update) [если detection_mode="motion"]
  │    └─ grayscale, GaussianBlur, frame diff, threshold
  │         → motion_active = True/False
  │
  ├─ Пропуск по frame stride [detector_input_frames % detector_frame_stride != 0]
  │
  ├─ YOLO detection/tracking (YOLODetector.track)
  │    └─ model.track(frame) → ByteTrack IDs + bboxes
  │    └─ _filter_by_size → детекции после size-фильтра
  │    └─ _expand_detections → bbox с padding
  │
  ├─ ROI filtering по детекциям (_filter_detections_by_roi)
  │    └─ считает полигон #2 (ДУБЛЬ расчета полигона)
  │    └─ фильтрует детекции по попаданию центра bbox внутрь полигона
  │
  ├─ Обновление debug registry (update_from_detections)
  │    └─ cleanup_stale (ДУБЛЬ очистки — еще один вызов есть выше)
  │
  ├─ ANPRPipeline.process_frame
  │    ├─ Для каждой детекции:
  │    │    ├─ TrackDirectionEstimator.update (история bbox → APPROACHING/RECEDING)
  │    │    ├─ crop из кадра (frame[y1:y2, x1:x2])
  │    │    └─ PlatePreprocessor.preprocess (создает CLAHE+kernel КАЖДЫЙ раз)
  │    │         ├─ grayscale, CLAHE, GaussianBlur, adaptiveThreshold, morphology
  │    │         ├─ _detect_plate_quadrilateral → perspective transform
  │    │         └─ ИЛИ _estimate_skew_angle → Canny, HoughLinesP, rotation
  │    │
  │    ├─ CRNNRecognizer.recognize_batch (batch из preprocessed crop-ов)
  │    │    ├─ transform каждого изображения (PIL → grayscale → resize → normalize)
  │    │    ├─ torch.stack → batch tensor
  │    │    ├─ model(batch) → log-softmax output
  │    │    └─ _decode_batch (Python-цикл на каждый timestep — не векторизован)
  │    │
  │    ├─ Для каждого результата decode:
  │    │    ├─ проверка confidence threshold (< min_confidence → "Нечитаемо")
  │    │    ├─ TrackAggregator.add_result (quorum/consensus)
  │    │    │    └─ на каждом вызове пересобирает weights/counts dicts
  │    │    ├─ PlatePostProcessor.process (country validation)
  │    │    │    └─ нормализует текст, проверяет regex для активных стран
  │    │    └─ cooldown check (_on_cooldown)
  │    │
  │    └─ Возвращает детекции (в том числе unreadable / no-text)
  │
  ├─ Формирование и сохранение события
  │    ├─ _build_event_media_paths → mkdir (ДУБЛЬ mkdir ниже)
  │    ├─ _save_jpeg(frame) → cv2.imwrite
  │    ├─ _save_jpeg(plate_crop) → cv2.imwrite + mkdir (ДУБЛЬ mkdir)
  │    ├─ EventSink.insert_event (PostgreSQL)
  │    └─ publish_event_sync
  │         ├─ asyncio.create_task(event_bus.publish) [асинхронная SSE-доставка]
  │         └─ ControllerAutomationService.dispatch_event [СИНХРОННЫЙ DB-запрос]
  │
  └─ JPEG preview encoding (cv2.imencode) [ВСЕГДА, даже без viewers]
       └─ захват _lock для обновления latest_jpeg
```

**Ключевые дублирования и потери эффективности:**
1. ROI-полигон считается дважды.
2. `cleanup_stale` вызывается дважды на обработанном кадре.
3. `mkdir` вызывается дважды для одной и той же директории события.
4. CLAHE и kernel создаются заново на каждом `preprocess()`.
5. JPEG кодируется на каждом кадре даже без зрителей.
6. DB-запрос контроллера блокирует поток канала после каждого события.
7. `track_texts`, `_history` и `_last_seen` растут без ограничений.

---

#### RP-2 — `PlatePreprocessor` выполняет полный пайплайн даже на очень маленьких crop

**Серьезность:** Средняя  
**Уверенность:** Высокая  

В `plate_preprocessor.py` проверяется только `plate_image.size == 0`, но не минимальные размеры. Поэтому даже очень маленький crop вроде 40×10 проходит через полный preprocessing, хотя OCR-качество там уже заведомо слабое.

**Рекомендуемое исправление:**
Добавить early guard по минимальной ширине/высоте и для слишком маленьких изображений сразу возвращать исходный crop.

---

#### RP-3 — `process_frame` мутирует входные `detections` по месту

**Серьезность:** Низкая  
**Уверенность:** Высокая  
**Доказательства:**

```python
# anpr_pipeline.py:214-215
detection.update(direction_info)
detection["plate_image"] = None
```

`process_frame` изменяет словари детекций прямо по месту: дописывает `direction`, `plate_image`, `text`, `confidence`, `country` и другие поля. В текущем коде это не ломает логику, потому что ниже никто не требует "чистый исходный список". Но контракт остается неявным.

**Рекомендуемое исправление:**
Либо явно документировать, что функция мутирует входные данные, либо формировать новые dict-объекты.

---

#### RP-4 — В debug overlay используется отдельная терминология для direction

**Серьезность:** Низкая  
**Уверенность:** Высокая  

`TrackDirectionEstimator` возвращает: `"APPROACHING"`, `"RECEDING"`, `"UNKNOWN"`.  
`DebugRegistry._estimate_direction` использует: `"IN"`, `"OUT"`, `None`.

То есть в системе одновременно существуют две разные vocabularies для направления движения. Для отладки это может быть запутывающим, потому что debug overlay и реальное значение `direction` в событии могут расходиться.

**Рекомендуемое исправление:**
Использовать в debug overlay значение из пайплайна (`det.get("direction")`) и привести fallback-оценку к той же vocabulary либо удалить ее.

---

## 3. Проблемы согласованности

---

#### CI-1 — В одной системе используются две разные vocabularies для `direction`

См. RP-4. Это одна и та же проблема согласованности, просто с разных сторон: отладка и основная бизнес-логика говорят о направлении разными словами.

---

#### CI-2 — `ChannelPayload` (create) и `ChannelConfigPayload` (update) — несовместимые модели

**Серьезность:** Средняя  
**Уверенность:** Высокая  
**Доказательства:**

```python
# schemas.py:10-15 (ChannelPayload — used for POST /api/channels)
class ChannelPayload(BaseModel):
    name: str
    source: str
    enabled: bool = True
    roi_enabled: bool = True
    region: Dict[str, Any] | None = None
```

`ChannelPayload`, который используется при создании канала, не содержит многих важных полей (`detection_mode`, `best_shots`, `cooldown_seconds`, `ocr_min_confidence` и т. д.). В результате после `POST /api/channels` в YAML часть каналов будет храниться в "коротком" виде, а часть — в "полном", если пользователь затем сохранял форму настроек.

Runtime с этим справляется через `channel.get(..., default)`, но структура конфигурации при этом становится неравномерной.

**Рекомендуемое исправление:**
Сразу после создания канала заполнять все поля дефолтами из `ChannelConfigPayload`, чтобы в YAML все каналы хранились в согласованной форме.

---

#### CI-3 — `put_global_settings` перезапускает processor при каждом сохранении настроек

**Серьезность:** Средняя  
**Уверенность:** Высокая  
**Доказательства:**

```python
# routers/settings.py:67
container.restart_processor_for_settings()
```

```python
# container.py:133-145
def restart_processor_for_settings(self):
    ...
    for channel in channels:
        self.processor.stop(int(channel["id"]))
    self.processor = self._create_processor()   # ← rebuilds YOLO + CRNN models
    for channel in channels:
        self.processor.ensure_channel(channel)
    for channel_id in enabled_ids:
        self.processor.start(channel_id)
```

Каждый `PUT /api/settings`, включая изменения сетки или темы интерфейса, разрушает и пересоздает весь `ChannelProcessor`, заново загружает YOLO и CRNN и стартует каналы.

**Почему это проблема:**
Это серьезная UX-проблема. Простое изменение UI-настроек приводит к прерыванию всех видеопотоков на несколько секунд.

**Рекомендуемое исправление:**
Разделить настройки на:
- требующие рестарта processor (`plates`, detector/OCR, часть channel config, reconnect, storage changes),
- и не требующие рестарта (`grid`, `theme`, `logging.level`, `time`, `debug`).

`restart_processor_for_settings()` должен вызываться только для реально pipeline-affecting изменений.

---

## 4. Кандидаты на очистку

---

### Таблица 1: Можно безопасно удалить уже сейчас

| Элемент | Файл | Доказательство | Почему |
|--------|------|----------------|--------|
| `CRNNRecognizer.recognize()` | `anpr/recognition/crnn_recognizer.py:78-82` | Нигде не вызывается | Мертвый код, тонкая обертка над `recognize_batch` |
| `TrackAggregator.clear_last()` | `anpr/pipeline/anpr_pipeline.py:65-66` | Нигде не вызывается | Мертвый код, функционально заменен `reset()` |
| Второй `mkdir` в `_save_jpeg` | `runtime/channel_runtime.py:253` | Директория уже создается в `_build_event_media_paths` | Лишний filesystem syscall |
| Лишний `cleanup_stale` на строке 498 | `runtime/channel_runtime.py:498` | Такой же cleanup уже вызывается внутри `update_from_detections` | Двойная очистка на каждый кадр |
| Копия `list(plate_images)` в `recognize_batch` | `anpr/recognition/crnn_recognizer.py:69` | На callsite это уже `List` | Лишняя копия |

---

### Таблица 2: Требует проверки перед удалением

| Элемент | Файл | Что проверить | Почему есть сомнение |
|--------|------|---------------|----------------------|
| `log_perf_stage` | `common/logging.py:277-288` | Проверить использование вне Python (JS, конфиги, доки) | В Python не вызывается, но может быть задокументирован как API |
| `CONTROLLER_TYPES` dict | `controllers/service.py:14-16` | Проверить импорт со стороны фронтенда или внешних скриптов | Экспортируется через `__all__` |
| `ChannelFilterPayload.size_filter_enabled` | `app/api/schemas.py:70` | Проверить, как поле проходит через `update_channel` | Может использоваться косвенно через `payload.model_dump()` |

---

### Таблица 3: Нужно рефакторить, а не удалять

| Элемент | Файл | Что рефакторить | Ожидаемый результат |
|--------|------|------------------|---------------------|
| `TrackAggregator.track_texts` (list) | `anpr/pipeline/anpr_pipeline.py:30` | Заменить `List` на `deque(maxlen=best_shots)` + добавить TTL-эвикцию | Ограниченная память, O(1) pop |
| `TrackDirectionEstimator._history` | `anpr/pipeline/anpr_pipeline.py:96` | Добавить TTL-эвикцию через `time.monotonic()` | Ограниченная память |
| `ANPRPipeline._last_seen` | `anpr/pipeline/anpr_pipeline.py:193` | Чистить записи старше `cooldown_seconds * 2` | Ограниченная память |
| `_apply_roi_mask` + `_filter_detections_by_roi` | `runtime/channel_runtime.py:274, 321` | Считать полигон один раз, убрать full-frame mask | Меньше лишней работы на кадр |
| `PlatePreprocessor.preprocess` | `anpr/preprocessing/plate_preprocessor.py:145-170` | Перенести CLAHE и kernel в `__init__` | Нет per-call allocation |
| `CRNNRecognizer._decode_batch` | `anpr/recognition/crnn_recognizer.py:84-114` | Векторизовать `argmax` + `exp` по целому тензору | Более быстрый decode |
| `put_global_settings` restart logic | `app/api/routers/settings.py:47-68` | Перезапускать processor только при изменениях, влияющих на pipeline | Не будет прерывания каналов из-за UI-only изменений |
| `dispatch_event` + `handle_event` | `controllers/service.py:165-220` | Объединить в один метод | Меньше лишней косвенности |
| `DebugLogBus.wait_for_entries` | `runtime/debug.py:375-379` | Заменить на async queue по аналогии с `EventBus` | Не будут блокироваться thread pool threads |
| `settings.py` router file | `app/api/routers/settings.py` | Разделить на `settings.py` и `data.py` | Более чистая организация маршрутов |

---

## 5. Независимые задачи на реализацию

Полный список задач см. в `REVIEW_TASKS_RU.md`.
