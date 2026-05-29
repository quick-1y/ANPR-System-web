# Roadmap внедрения inference-настроек

Этот документ фиксирует возможный будущий дизайн секции `inference` для ANPR System. Сейчас секция `inference` удалена из актуального `config/settings.yaml`, потому что прежние параметры `workers` и `shared_memory` не использовались runtime-кодом. Возвращать её стоит только вместе с реальной реализацией управления ML-инференсом.

## Текущее состояние

Сейчас инференс выполняется внутри потока конкретного канала:

1. `ChannelProcessor.start()` создаёт отдельный `threading.Thread` для канала.
2. Внутри `_run_channel()` канал читает кадры, применяет motion gate и stride-логику.
3. Если кадр нужно обработать, канал синхронно вызывает `detector.track(frame)`.
4. Затем тот же поток вызывает `pipeline.process_frame(frame, detections)` для OCR, постобработки и агрегации.

Отдельного inference executor, очереди inference-задач, process pool или shared-memory транспорта сейчас нет.

При этом часть оптимизаций уже реализована:

- YOLO-веса кешируются и переиспользуются, а каналы получают lightweight clone с отдельным predictor/tracker state.
- OCR recognizer создаётся как общий singleton, чтобы не инициализировать CRNN параллельно в нескольких каналах.
- Частота тяжёлой обработки регулируется настройками канала в PostgreSQL: `detector_frame_stride`, `adaptive_stride_enabled`, `motion_threshold`, `max_ocr_attempts`, `preview_fps_limit` и другими.

## Как можно трактовать `inference`

Если в будущем вернуть секцию:

```yaml
inference:
  workers: 2
  shared_memory: true
```

то её профессиональный смысл должен быть таким:

| Поле | Смысл |
|---|---|
| `workers` | Глобальный лимит параллельных ML-задач или количество inference worker'ов по всем каналам |
| `shared_memory` | Использование shared memory для передачи больших кадров между процессами без лишнего копирования; имеет смысл только для process-based backend |

Важно: `shared_memory: true` не делает PyTorch/YOLO-модели автоматически общими между процессами. Shared memory подходит прежде всего для OpenCV/Numpy кадров и требует отдельного lifecycle management.

## Рекомендуемый путь внедрения

### Этап 1. Глобальный limiter параллельного инференса

Минимальный полезный вариант:

```yaml
inference:
  workers: 2
  queue_wait_ms: 0
  overload_policy: skip_frame
```

Смысл:

- одновременно не больше `workers` каналов выполняют тяжёлый блок `detector.track(...) + pipeline.process_frame(...)`;
- если все слоты заняты, канал не накапливает задержку, а пропускает текущий кадр;
- канальные потоки, текущие модели и tracking state остаются в прежней архитектуре.

Ожидаемое место применения — вокруг синхронного блока ANPR-обработки в `runtime/channel_runtime.py`:

```python
with inference_limiter:
    detections = detector.track(frame)
    results = pipeline.process_frame(frame, detections)
```

Преимущества:

- быстро снижает пики CPU/GPU-нагрузки;
- не требует сериализации кадров;
- не требует shared memory;
- не ломает изоляцию каналов и текущую схему YOLO tracker state.

Ограничения:

- это limiter конкурентности, а не полноценный worker pool;
- зависший inference-вызов занимает слот до таймаута/остановки канала;
- нужно явно выбрать policy: ждать слот или пропускать кадр.

### Этап 2. Очередь inference-задач и backpressure

Расширенный thread-based вариант:

```yaml
inference:
  backend: thread_pool
  workers: 2
  queue_size: 8
  drop_policy: latest
  job_timeout_ms: 5000
```

Смысл:

- канальный поток читает поток и принимает решение motion/stride;
- тяжёлую ML-задачу отдаёт в общий executor;
- очередь ограничена, чтобы система не обрабатывала устаревшие кадры;
- для каждого канала желательно иметь не больше одной pending/in-flight задачи.

Ключевые правила:

- результат задачи применяется только если канал всё ещё активен и generation/version канала совпадает;
- при перегрузке старые кадры лучше заменять новыми, а не копить backlog;
- порядок кадров в рамках одного канала нельзя нарушать без явного отказа от tracker-dependent логики.

### Этап 3. Process workers и shared memory

Process-based вариант:

```yaml
inference:
  backend: process_pool
  workers: 2
  shared_memory: true
  queue_size: 8
  drop_policy: latest
  job_timeout_ms: 5000
```

Смысл:

- inference выполняется в отдельных процессах;
- кадры передаются worker'ам через shared memory;
- API/channel runtime получает назад только лёгкий результат: bbox, track id, text, confidence, direction и служебные метаданные.

Преимущества:

- лучшая изоляция CPU-heavy ML workload;
- потенциально лучшее использование CPU cores;
- падение worker-процесса можно обрабатывать отдельно от API process.

Сложности:

- каждый process worker, скорее всего, загрузит собственные YOLO/OCR модели;
- нужно sticky routing `channel_id -> worker`, иначе можно сломать YOLO tracker state;
- нужно управлять lifecycle shared memory: create, attach, close, unlink, cleanup after timeout/crash;
- требуется health-check и restart worker'ов;
- сложнее тестирование, graceful shutdown и отладка.

## Почему `shared_memory` не нужен на первом этапе

В текущей архитектуре канальные потоки работают внутри одного процесса. Потоки уже видят одну память процесса, поэтому shared memory между ними не нужна.

Shared memory становится полезной только при переносе inference в отдельные процессы, потому что один full HD frame может занимать несколько мегабайт:

```text
1920 × 1080 × 3 uint8 ≈ 6 MB
```

Передавать такие кадры через обычную `multiprocessing.Queue` дорого из-за копирования/сериализации. Shared memory позволяет передавать worker'у только метаданные: имя сегмента, shape, dtype, `channel_id`, `frame_id`.

## Что нельзя смешивать

`inference.workers` не должен заменять настройки каналов.

Глобальный `workers` — это лимит ресурсов всей системы. А параметры качества, частоты и чувствительности остаются настройками конкретного канала в PostgreSQL:

- `detector_frame_stride`;
- `adaptive_stride_enabled`;
- `motion_threshold`;
- `motion_frame_stride`;
- `max_ocr_attempts`;
- `preview_fps_limit`;
- ROI и фильтры размера номера.

Такое разделение сохраняет независимость каналов: слабая или загруженная камера не должна менять поведение всех остальных каналов.

## Рекомендуемая итоговая модель настроек

Для первого внедрения лучше не возвращать `shared_memory`, а начать с понятного limiter'а:

```yaml
inference:
  workers: 2
  queue_wait_ms: 0
  overload_policy: skip_frame
```

Для будущего process-based backend можно расширить схему:

```yaml
inference:
  backend: process_pool
  workers: 2
  shared_memory: true
  queue_size: 8
  drop_policy: latest
  job_timeout_ms: 5000
```

## Критерии готовности к возврату секции `inference`

Секцию `inference` стоит возвращать в `settings.yaml` только если одновременно выполнены условия:

1. настройки читаются через `SettingsManager`;
2. normalizer валидирует и нормализует все поля;
3. `ChannelProcessor` или отдельный inference service реально применяет `workers`;
4. есть понятная overload policy;
5. есть тесты на нормализацию и runtime-поведение;
6. документация описывает, какие поля глобальные, а какие остаются настройками каналов;
7. если включён `shared_memory`, реализован безопасный cleanup сегментов при timeout, exception и shutdown.

## Итоговая рекомендация

Для ANPR System наиболее безопасный путь — поэтапный:

1. сначала реализовать `workers` как глобальный limiter одновременных ML-вызовов;
2. затем добавить bounded queue и backpressure;
3. только после этого рассматривать `process_pool + shared_memory` как отдельную крупную архитектурную задачу.

Такой путь даст практическую пользу без преждевременного усложнения runtime и без риска снова получить неиспользуемую секцию в `settings.yaml`.
