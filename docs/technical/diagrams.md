# Диаграммы

Этот файл содержит вынесенные из корневого README схемы проекта. README остаётся короче и работает как обзорная точка входа, а все mermaid-диаграммы собраны здесь.

## 1. Общая схема взаимодействия сервисов

```mermaid
flowchart TD
    USER["Оператор / Браузер"] --> UI["Web UI\napp/web/index.html"]

    subgraph API["API service / FastAPI\napp/api/main.py"]
        HTTP["REST API"]
        SSE["SSE stream"]
        PREVIEW["Preview endpoints\nsnapshot / preview.mjpg"]
        PROC["ChannelProcessor"]
        BUS["EventBus"]
        SETTINGS["SettingsManager"]
        EVENTS_DB["PostgresEventDatabase"]
        LISTS_DB["ListDatabase"]
        CTRL["ControllerService"]
        LIFE["DataLifecycleService"]
    end

    subgraph CORE["Channel runtime / ANPR core"]
        SRC["RTSP / HTTP / file / camera"]
        CH["Channel thread"]
        YOLO["YOLODetector"]
        PIPE["ANPRPipeline"]
    end

    subgraph WORKER["Retention worker\napp/worker/main.py"]
        SCH["RetentionScheduler"]
        WLIFE["DataLifecycleService"]
    end

    subgraph STORAGE["Storage"]
        PG[("PostgreSQL")]
        MEDIA[("Screenshots / crops / exports")]
    end

    UI --> HTTP
    UI --> SSE
    UI --> PREVIEW

    HTTP --> SETTINGS
    HTTP --> PROC
    HTTP --> EVENTS_DB
    HTTP --> LISTS_DB
    HTTP --> CTRL
    HTTP --> LIFE

    PROC --> CH
    SRC --> CH
    CH --> YOLO
    YOLO --> PIPE
    PIPE --> EVENTS_DB
    PIPE --> BUS

    SSE --> BUS
    PREVIEW --> PROC

    EVENTS_DB --> PG
    LIFE --> PG
    LIFE --> MEDIA
    WLIFE --> PG
    WLIFE --> MEDIA
    SCH --> WLIFE
```

## 2. Видеоввод и формирование preview

```mermaid
flowchart TD
    A["Источник видео\nRTSP / HTTP / файл / камера"] --> B["ChannelProcessor.start()"]
    B --> C["Поток channel-{CHANNEL_ID}"]
    C --> D["cv2.VideoCapture(source)"]
    D --> E["cap.read() → frame"]

    E --> G["Preview ветка\nкаждый кадр"]
    G --> H["cv2.imencode('.jpg', frame)"]
    H --> I["latest_jpeg в памяти\nChannelContext"]
    I --> J["GET /api/channels/{id}/snapshot.jpg"]
    I --> K["GET /api/channels/{id}/preview.mjpg"]
    K --> L["Web UI"]

    E --> M["ANPR ветка"]
    M --> N["YOLODetector.track(frame)"]
    N --> O["ANPRPipeline.process_frame(...)"]
```

## 3. Внутренний ANPR pipeline

```mermaid
flowchart TD
    A["Frame"] --> B{"ROI enabled?"}
    B -->|Нет| C["detector_frame = frame"]
    B -->|Да| D["detector_frame = ROI-masked frame"]

    C --> E{"detection_mode == motion?"}
    D --> E
    E -->|Да| F["MotionDetector.update(detector_frame)"]
    E -->|Нет| H["Пропустить motion gate"]
    F --> G{"Движение активно?"}
    G -->|Нет| Z["Пропуск кадра"]
    G -->|Да| H

    H --> I["YOLODetector.track(detector_frame)"]
    I --> J{"Detections в ROI-polygon?"}
    J -->|Нет| Z
    J -->|Да| K["ANPRPipeline.process_frame(full frame, detections)"]

    K --> L["TrackDirectionEstimator.update(...)"]
    L --> BUDGET{"should_process(track_id)?\n(бюджет OCR не исчерпан,\nтрек не финализирован)"}
    BUDGET -->|Нет| UNREAD{"should_emit_unreadable?"}
    UNREAD -->|Да| UNREAD_EVENT["Один раз: событие «Нечитаемо»"]
    UNREAD -->|Нет| Z

    BUDGET -->|Да| N["Кроп bbox из full frame"]
    N --> O["PlatePreprocessor.preprocess(...)"]
    O --> P["CRNNRecognizer.recognize_batch(...)"]

    P --> Q{"confidence >=\nocr_min_confidence?"}
    Q -->|Нет| COUNT_EMPTY["Счётчик попыток +1\n(пустой текст в агрегатор)"]
    Q -->|Да| AGG["TrackAggregator.add_result()\nСчётчик попыток +1\nКандидат в пул"]

    COUNT_EMPTY --> EXHAUST{"Бюджет исчерпан?"}
    AGG --> CONSENSUS{"Консенсус достигнут?\n(кворум + weighted majority)"}
    CONSENSUS -->|Да| FINALIZE["Финализация трека\n→ Emit plate"]
    CONSENSUS -->|Нет| EXHAUST

    EXHAUST -->|Нет| Z
    EXHAUST -->|Да| BEST{"Есть кандидаты?"}
    BEST -->|Да| BEST_EMIT["Лучший кандидат по весу\n→ Emit plate"]
    BEST -->|Нет| UNREAD_FINAL["Событие «Нечитаемо»"]

    FINALIZE --> V["PlatePostProcessor.process(...)"]
    BEST_EMIT --> V

    V --> W{"Номер валиден?"}
    W -->|Нет| RESET["aggregator.reset(track_id)\n(история очищается,\nсчётчик сохраняется)"]
    W -->|Да| X{"Cooldown прошёл?"}
    X -->|Нет| Z
    X -->|Да| Y["Сформировать событие"]
    RESET --> EXHAUST2{"Бюджет исчерпан\nпосле reset?"}
    EXHAUST2 -->|Да| UNREAD_FINAL
    EXHAUST2 -->|Нет| Z
```

## 4. Сохранение и публикация события

```mermaid
flowchart TD
    A["Готовое событие"] --> D["PostgresEventDatabase.insert_event(...)"]
    D --> PG[("PostgreSQL")]

    A --> I["event_callback"]
    I --> J["EventBus.publish(...)"]
    J --> K["GET /api/events/stream (SSE)"]
    K --> L["EventSource в Web UI"]

    PG --> M["GET /api/events (paginated)"]
    M --> N["Журнал / детали события"]
```

## 5. Retention и обслуживание хранилища

```mermaid
flowchart TD
    A["Storage policy"] --> B["RetentionScheduler.start()"]
    B --> C{"auto_cleanup_enabled?"}
    C -->|Да| D["run_retention_cycle()"]
    C -->|Нет| J["Sleep до следующего интервала"]
    J --> B

    D --> F["cleanup_old_events()\nУдалить события старше retention_days\nУдалить связанные медиафайлы"]
    D --> G["cleanup_old_media()\nУдалить orphan-файлы по mtime"]
    D --> H["enforce_storage_limit()\nУдалить старейшие файлы при превышении max_screenshots_mb"]
    D --> B

    F --> PG[("PostgreSQL")]
    G --> MEDIA[("media dir")]
    H --> MEDIA
```
