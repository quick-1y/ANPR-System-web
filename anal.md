  Глубокий технический анализ CPU-нагрузки ANPR-системы                                                                                                                                                                                                                                                             
                                                                                                                                                                                                                                                                                                                    
  1. Executive Summary                                                                                                                                                                                                                                                                                              
                                                                                                                                                                                                                                                                                                                    
  Система имеет хорошо продуманную архитектуру с множеством уже реализованных оптимизаций (motion gate, detector stride, OCR budget, best_shots, cooldown). Однако есть несколько критических проблем, которые сводят на нет часть этих оптимизаций на CPU-only деплое:

  Главные проблемы:
  1. Thread oversubscription — ни torch.set_num_threads(), ни OMP_NUM_THREADS, ни cv2.setNumThreads() нигде не установлены. При N каналах × N внутренних потоков PyTorch/OpenMP = экспоненциальное переключение контекста.
  2. JPEG-кодирование каждого кадра — независимо от того, смотрит ли кто-нибудь preview. Это самый постоянный CPU-расход после YOLO inference.
  3. Тяжёлый PlatePreprocessor на каждый кроп — Canny, HoughLines, contour detection, perspective transform запускаются на каждом bbox на каждом кадре, даже если OCR потом отвергнет результат.
  4. Singleton CRNNRecognizer — batch inference под GIL по факту сериализует OCR всех каналов через один Python-поток, создавая contention.
  5. Неиспользуемая настройка inference.workers — подготовлена, но не подключена.

  Потенциальный суммарный CPU-выигрыш при реализации всех рекомендаций: 40–60% снижение нагрузки для типичного деплоя с 2–4 каналами на CPU.

  ---
  2. Текущая модель CPU-затрат (End-to-End Cost Map)

  Для каждого канала, путь обработки одного кадра:

  ┌─────────────────────────────────────────────────────────────────────┬────────────────────────────┬────────────────────┬───────────────────────────────┐
  │                               Стадия                                │        Тип нагрузки        │ Примерная доля CPU │              Код              │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ cap.read()                                                          │ I/O-bound (RTSP decode)    │ 10–15%             │ channel_runtime.py:457        │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ Motion detection (cvtColor + GaussianBlur + absdiff)                │ Always-on, даже при stride │ 3–5%               │ motion_detector.py:44-58      │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ YOLO track/detect                                                   │ CPU-burst, самый тяжёлый   │ 35–45%             │ yolo_detector.py:196          │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ ROI filtering (pointPolygonTest)                                    │ Negligible                 │ <1%                │ channel_runtime.py:320-321    │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ PlatePreprocessor (CLAHE+Canny+HoughLines+contours+warpPerspective) │ Per-bbox burst             │ 8–15%              │ plate_preprocessor.py:149-172 │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ CRNN inference (batch, quantized INT8)                              │ Per-bbox burst             │ 10–18%             │ crnn_recognizer.py:70-79      │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ TrackAggregator (consensus/budget)                                  │ Negligible                 │ <0.5%              │ anpr_pipeline.py:133-208      │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ PostProcessor (regex match)                                         │ Negligible                 │ <0.5%              │ validator.py                  │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ JPEG encode (preview)                                               │ Always-on, EVERY frame     │ 8–12%              │ channel_runtime.py:584        │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ Event persistence (DB insert + file write)                          │ Rare burst, I/O-bound      │ 1–2%               │ channel_runtime.py:555-573    │
  ├─────────────────────────────────────────────────────────────────────┼────────────────────────────┼────────────────────┼───────────────────────────────┤
  │ Debug registry updates                                              │ Light, per-frame           │ 1–2%               │ channel_runtime.py:526,531    │
  └─────────────────────────────────────────────────────────────────────┴────────────────────────────┴────────────────────┴───────────────────────────────┘

  Критическое наблюдение: JPEG encode (8–12%) — единственная постоянная CPU-нагрузка, которая не управляется ни motion gate, ни detector stride, ни OCR budget. Она работает на КАЖДЫЙ кадр.

  ---
  3. Уже реализованные оптимизации и их эффективность

  3.1 Motion Gate (detection_mode: motion)

  - Файл: motion_detector.py, channel_runtime.py:505-510
  - Как работает: GaussianBlur + absdiff + гистерезис (activation/release frames)
  - Эффективность: Высокая для статических камер. При пустой сцене полностью исключает YOLO + OCR.
  - Слабое место: Сам motion detector делает cvtColor + GaussianBlur на каждом кадре (с учётом своего motion_frame_stride). При stride=1 это ~3-5% CPU постоянно. Но это дёшево по сравнению с сэкономленным YOLO.

  3.2 Detector Frame Stride (detector_frame_stride)

  - Файл: channel_runtime.py:514-516
  - Как работает: Пропускает каждый N-й кадр для YOLO.
  - Эффективность: Средняя. По умолчанию stride=2, что снижает YOLO нагрузку в 2 раза. Но stride — фиксированный, не адаптируется к трафику.
  - Слабое место: Stride считается только среди кадров, прошедших motion gate (detector_input_frames — это filtered frames, не raw). Это правильно. Однако при detector_frame_stride=2 и 25 fps, YOLO всё равно вызывается 12.5 раз/сек.

  3.3 ROI Filtering

  - Файл: channel_runtime.py:323-342
  - Как работает: cv2.pointPolygonTest для центра bbox после detection.
  - Эффективность: Высокая для OCR, но не снижает стоимость детекции. YOLO работает на полном кадре; ROI фильтрует только результаты. Детекции вне ROI не проходят в pipeline, экономя OCR/preprocessing.
  - Слабое место: YOLO всё равно обрабатывает весь кадр. Для сцен, где ROI покрывает малую часть кадра — основная CPU-стоимость не снижается.

  3.4 OCR Budget (max_ocr_attempts) и Track Finalization

  - Файл: anpr_pipeline.py:88-97, 189-207
  - Как работает: Каждый трек ограничен max_ocr_attempts (default 15). После финализации should_process() → False, весь OCR pipeline пропускается.
  - Эффективность: Критически важная оптимизация. Для машины, видимой 5 секунд при 12.5 fps, это 62 кадра. С best_shots=3 и быстрым консенсусом, OCR работает только 3 из 62 кадров. С бюджетом 15 — максимум 15 из 62.
  - Слабое место: YOLO detection всё равно запускается на каждый stride-кадр — финализация трека не освобождает от detection. Это правильно (нужно отслеживать новые машины).

  3.5 Best Shots (Quorum Consensus)

  - Файл: anpr_pipeline.py:168-186
  - Как работает: Скользящий буфер из best_shots результатов. Если кворум (majority + weighted > 50%) достигнут — трек финализируется.
  - Эффективность: Высокая. При best_shots=3 и хорошем OCR — финализация за 3 попытки. На чистых номерах это экономит 80% OCR-бюджета.

  3.6 Cooldown

  - Файл: anpr_pipeline.py:373-383
  - Как работает: Тот же номер не эмитируется повторно в течение cooldown_seconds.
  - Эффективность: Экономит только DB writes и events, не CPU.

  3.7 Shared Singleton OCR Recognizer

  - Файл: factory.py:18-73
  - Как работает: Один CRNNRecognizer инстанс для всех каналов. Double-checked locking.
  - Эффективность: Экономит RAM (одна копия модели). Но создаёт contention — см. раздел 5.

  ---
  4. Подтверждённые точки CPU-расхода

  4.1 JPEG-кодирование на каждый кадр (ПОДТВЕРЖДЕНО)

  # channel_runtime.py:583-593
  if not self._debug_registry.get_settings().disable_video_output:
      ok_enc, preview_buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
  - Выполняется на каждом кадре, даже когда ни один клиент не смотрит preview.
  - Упоминается в AGENTS.md как known pitfall (строка 514).
  - cv2.imencode на 1920×1080 при quality=80 ≈ 2–4 мс на CPU. При 25 fps × 4 канала = 200–400 мс/сек = одно целое ядро.

  4.2 PlatePreprocessor — тяжёлый на каждый кроп (ПОДТВЕРЖДЕНО)

  # plate_preprocessor.py:149-172
  def preprocess(self, plate_image):
      gray = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)        # 1
      enhanced = self._clahe.apply(gray)                            # 2
      blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)              # 3
      thresh = cv2.adaptiveThreshold(...)                           # 4
      cleaned = cv2.morphologyEx(thresh, MORPH_CLOSE, ...)         # 5
      cleaned = cv2.morphologyEx(cleaned, MORPH_OPEN, ...)         # 6
      quadrilateral = self._detect_plate_quadrilateral(cleaned)    # 7 (findContours + approxPolyDP)
      # fallback path:
      angle, confidence = self._estimate_skew_angle(blurred, cleaned)  # 8 (Canny + HoughLinesP!)
  - 8 этапов обработки, включая Canny, HoughLinesP, findContours, approxPolyDP.
  - _estimate_skew_angle запускается, если нет quadrilateral — это включает Canny + HoughLinesP, что тяжело.
  - Это выполняется для каждого bbox, прошедшего ROI-фильтр и should_process().
  - На малоразмерных кропах (~200×60) это быстро (< 1 мс), но при нескольких номерах одновременно — суммируется.

  4.3 CRNN _preprocess дублирует работу (ПОДТВЕРЖДЕНО)

  # crnn_recognizer.py:58-68
  def _preprocess(self, img):
      if img.ndim == 3 and img.shape[2] == 3:
          gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)  # ВТОРОЙ cvtColor!
      resized = cv2.resize(gray, (self._ocr_width, self._ocr_height))
      tensor = torch.from_numpy(resized).float().unsqueeze(0) / 255.0
  - PlatePreprocessor уже делает cvtColor в grayscale, но если возвращает original plate_image (не grayscale), CRNN делает это повторно.
  - В path preprocess() → если quadrilateral is not None → _four_point_transform(plate_image, ...) — возвращает BGR (original plate_image). Значит CRNN-препроцессор всегда вызывает лишний cvtColor.

  4.4 inference.workers — мёртвая настройка (ПОДТВЕРЖДЕНО)

  # settings_schema.py:92-94
  def inference_defaults():
      cpu_count = os.cpu_count() or 1
      return {"workers": max(1, cpu_count - 1), "shared_memory": True}
  get_inference_settings() определён в settings_manager.py:417, но ни одна строка кода его не вызывает. Настройка inference.workers нигде не используется. Это подготовленный, но не подключённый механизм.

  4.5 Нет контроля потоков PyTorch/OpenMP/MKL (ПОДТВЕРЖДЕНО)

  Ни в Dockerfile, ни в коде, ни в .env.example нет:
  - torch.set_num_threads()
  - torch.set_num_interop_threads()
  - cv2.setNumThreads()
  - OMP_NUM_THREADS
  - MKL_NUM_THREADS
  - OPENBLAS_NUM_THREADS

  Это критическая проблема. По умолчанию PyTorch использует os.cpu_count() потоков для каждого вызова inference. На 8-ядерной машине с 4 каналами: 4 потока-канала × 8 внутренних потоков PyTorch = 32 логических потока, борющихся за 8 ядер. Это oversubscription, вызывающий cache thrashing и context switching
  overhead.

  ---
  5. Анализ многопоточности / многоядерности / Python GIL

  5.1 Текущая модель

  - Каждый канал = 1 daemon thread (channel-{id})
  - Все каналы делят один Python процесс
  - Общий singleton CRNNRecognizer
  - YOLO detector — отдельный инстанс на канал (создаётся в build_components)
  - Все OCR batch-вызовы проходят через GIL

  5.2 Что реально параллелится, а что сериализуется

  ┌───────────────────────────────────┬───────────────────────────────────────────────┬──────────────────────────────────────────────────┐
  │             Операция              │                 GIL-поведение                 │               Реальный параллелизм               │
  ├───────────────────────────────────┼───────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ cap.read() (RTSP decode)          │ Отпускает GIL (C-level OpenCV)                │ Да, параллельно                                  │
  ├───────────────────────────────────┼───────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ cv2.imencode() (JPEG)             │ Отпускает GIL                                 │ Да, параллельно                                  │
  ├───────────────────────────────────┼───────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ cv2.cvtColor/GaussianBlur/absdiff │ Отпускает GIL                                 │ Да, параллельно                                  │
  ├───────────────────────────────────┼───────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ model.track(frame) (YOLO)         │ PyTorch: отпускает GIL во время C++ inference │ Частично — GIL захватывается при Python-обёртках │
  ├───────────────────────────────────┼───────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ self.model(batch) (CRNN)          │ PyTorch: отпускает GIL для inference          │ Частично                                         │
  ├───────────────────────────────────┼───────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ torch.from_numpy(), torch.stack() │ Держит GIL                                    │ Сериализовано                                    │
  ├───────────────────────────────────┼───────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ _preprocess() Python-логика       │ Держит GIL                                    │ Сериализовано                                    │
  ├───────────────────────────────────┼───────────────────────────────────────────────┼──────────────────────────────────────────────────┤
  │ TrackAggregator / PostProcessor   │ Держит GIL                                    │ Сериализовано                                    │
  └───────────────────────────────────┴───────────────────────────────────────────────┴──────────────────────────────────────────────────┘

  5.3 Проблема oversubscription

  При дефолтных настройках (N = cpu_count потоков на PyTorch inference):

  Система с 8 ядрами, 4 канала:
    4 channel threads × 1 YOLO inference (каждый использует 8 OpenMP threads) = 32 потока
    + CRNN singleton (8 OpenMP threads)
    + 4 × OpenCV parallel regions
    + Uvicorn asyncio event loop
    = МАССОВЫЙ oversubscription

  Результат: cache thrashing, context switch overhead 15–30%, эффективная пропускная способность ниже, чем при правильной настройке.

  5.4 Contention на shared CRNNRecognizer

  CRNNRecognizer — singleton. Но Python GIL делает так, что только один поток может готовить batch (_preprocess, torch.stack). Пока один канал готовит batch, остальные ждут GIL. Само inference (self.model(batch)) отпускает GIL, но:
  - Batch size = количество номеров на одном кадре одного канала (обычно 1-3)
  - Другие каналы не могут добавить свои кропы в этот batch
  - Фактически, CRNN inference сериализован по каналам, а малый batch size = неэффективное использование

  ---
  6. Рекомендованные оптимизации

  6.1 Алгоритмические

  6.1.1 Conditional Preview Encoding (Ленивый JPEG encode)

  Текущее поведение: cv2.imencode() на каждый кадр (channel_runtime.py:583-593).

  Предложение: Кодировать только когда есть хотя бы один активный MJPEG/snapshot клиент, или с ограниченной частотой (например, 5 fps вместо полной).

  # Добавить counter/flag в ChannelContext:
  has_preview_consumers: bool = False
  preview_encode_interval: float = 0.2  # 5 fps

  # В цикле:
  now = time.monotonic()
  if ctx.has_preview_consumers and (now - last_encode_ts) >= preview_encode_interval:
      ok_enc, preview_buf = cv2.imencode(...)
      last_encode_ts = now

  - CPU impact: HIGH (8–12% на канал)
  - Accuracy risk: NONE
  - Complexity: LOW
  - Файлы: runtime/channel_runtime.py, app/api/routers/channels.py

  6.1.2 Адаптивный detector_frame_stride

  Текущее поведение: Фиксированный stride (default 2).

  Предложение: Увеличивать stride, когда нет активных треков или все треки финализированы. Уменьшать, когда есть новые треки.

  active_tracks = sum(1 for s in aggregator._track_states.values() if not s.finalized)
  effective_stride = base_stride if active_tracks > 0 else base_stride * 3

  - CPU impact: MEDIUM (снижает YOLO вызовы в idle на 60-70%)
  - Accuracy risk: LOW (при появлении нового объекта реакция задержится на stride кадров)
  - Complexity: LOW
  - Файлы: runtime/channel_runtime.py

  6.1.3 Skip preprocessing для мелких/некачественных bbox

  Текущее поведение: PlatePreprocessor запускает полный pipeline на каждый bbox.

  Предложение: Пропускать тяжёлые этапы (Canny, HoughLines) для bbox площадью < порога или с малым aspect ratio:

  def preprocess(self, plate_image):
      h, w = plate_image.shape[:2]
      # Слишком мелкий для perspective correction
      if w < 50 or h < 15:
          return plate_image  # Быстрый путь — просто отдать как есть
      # Полный pipeline для крупных bbox
      ...

  - CPU impact: MEDIUM (экономит Canny+HoughLines на ~30-50% кропов)
  - Accuracy risk: LOW (мелкие кропы всё равно плохо распознаются)
  - Complexity: LOW
  - Файлы: anpr/preprocessing/plate_preprocessor.py

  6.1.4 Передача grayscale из preprocessor в CRNN

  Текущее поведение: PlatePreprocessor делает cvtColor(BGR2GRAY), потом возвращает BGR plate_image (через _four_point_transform). CRNNRecognizer._preprocess делает cvtColor(BGR2GRAY) повторно.

  Предложение: Вернуть grayscale вместе с корректированным изображением или передать уже grayscale-версию в CRNN.

  - CPU impact: LOW (экономит ~0.3 мс на кроп)
  - Accuracy risk: NONE
  - Complexity: LOW
  - Файлы: anpr/preprocessing/plate_preprocessor.py, anpr/recognition/crnn_recognizer.py

  6.1.5 Более агрессивный early-exit по confidence

  Текущее поведение: Если CRNN confidence < min_confidence, результат передаётся в aggregator как пустой текст, но попытка считается. Трек не финализируется.

  Предложение: Для треков, где все N последних попыток были low-confidence (текст пустой), снижать оставшийся бюджет быстрее:

  consecutive_failures = ...  # подряд пустых результатов
  if consecutive_failures >= 5:
      state.finalized = True  # ранний exit

  - CPU impact: MEDIUM (для нечитаемых номеров — большая экономия)
  - Accuracy risk: MEDIUM (может пропустить номер, который появляется чётче позже)
  - Complexity: LOW
  - Файлы: anpr/pipeline/anpr_pipeline.py

  6.2 Concurrency / Runtime

  6.2.1 КРИТИЧНО: Установить torch.set_num_threads() и cv2.setNumThreads()

  Текущее поведение: Не контролируется. PyTorch использует все ядра.

  Предложение: В начале процесса (или в каждом channel thread):

  import torch
  import cv2

  num_channels = len(enabled_channels)
  total_cores = os.cpu_count() or 4
  # 1-2 потока на PyTorch для каждого канала
  threads_per_channel = max(1, total_cores // max(1, num_channels + 1))
  torch.set_num_threads(threads_per_channel)
  torch.set_num_interop_threads(2)
  cv2.setNumThreads(threads_per_channel)

  Или через environment variables в Dockerfile / .env:
  OMP_NUM_THREADS=2
  MKL_NUM_THREADS=2
  OPENBLAS_NUM_THREADS=2

  - CPU impact: HIGH (устраняет oversubscription, 15–30% реальный выигрыш на 3+ каналах)
  - Accuracy risk: NONE
  - Complexity: VERY LOW (3-5 строк кода или 3 env vars)
  - Файлы: app/api/main.py (startup), Dockerfile, .env.example

  6.2.2 Подключить inference.workers для OCR worker pool

  Текущее поведение: inference.workers определён, но не используется. CRNN вызывается inline в каждом channel thread.

  Предложение: Создать пул OCR-воркеров на основе concurrent.futures.ThreadPoolExecutor (или ProcessPoolExecutor для настоящего параллелизма):

  # В factory.py или container:
  ocr_pool = ThreadPoolExecutor(max_workers=inference_workers)

  # В channel thread вместо прямого вызова:
  future = ocr_pool.submit(recognizer.recognize_batch, plate_inputs)
  results = future.result(timeout=5.0)

  Это позволит:
  - Контролировать concurrency OCR inference
  - При использовании ProcessPoolExecutor — обойти GIL для CPU-bound inference
  - Батчить кропы от разных каналов в один batch
  - CPU impact: HIGH (реальный параллелизм для inference, если ProcessPoolExecutor)
  - Accuracy risk: NONE
  - Complexity: MEDIUM (нужна очередь, timeout-логика, IPC для процессов)
  - Файлы: anpr/pipeline/factory.py, anpr/pipeline/anpr_pipeline.py, runtime/channel_runtime.py

  6.2.3 Motion detector на downscaled frame

  Текущее поведение: motion_detector.py:44-45 — cvtColor + GaussianBlur на полном кадре.

  Предложение: Downscale до 320×240 перед motion detection:

  small = cv2.resize(frame, (320, 240), interpolation=cv2.INTER_NEAREST)
  gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

  - CPU impact: LOW-MEDIUM (motion detection сам по себе лёгкий, но на 4K кадрах разница заметна)
  - Accuracy risk: VERY LOW (motion detection не требует высокого разрешения)
  - Complexity: VERY LOW
  - Файлы: anpr/detection/motion_detector.py

  6.3 Streaming / Preview

  6.3.1 Lazy JPEG encode (см. 6.1.1)

  Уже описано выше. Самый быстрый и безопасный win.

  6.3.2 Shared JPEG frame для всех MJPEG клиентов

  Текущее поведение: Каждый MJPEG клиент (channel_preview_stream) поллит get_preview_frame() каждые 80 мс. Сам frame — один и тот же bytes object. Это уже OK.

  Анализ: Текущая реализация уже эффективна — все клиенты читают один latest_jpeg. Нет дублирования encode. Но 80 мс sleep (12.5 fps) на каждого клиента — это asyncio task, а не CPU. OK.

  Одно улучшение: При asyncio.sleep(0.08) каждый idle клиент пробуждается 12.5 раз/сек, проверяя timestamp. При 10 клиентах = 125 wake-ups/sec. Замена на asyncio.Event с notify при обновлении frame убрала бы polling.

  - CPU impact: LOW (только при множестве клиентов)
  - Accuracy risk: NONE
  - Complexity: MEDIUM
  - Файлы: app/api/routers/channels.py, runtime/channel_runtime.py

  6.4 DB / I/O

  6.4.1 EventSink создаёт дубль connection pool

  Текущее поведение: EventSink.__init__ создаёт свой PostgresEventDatabase (event_sink.py:11), а AppContainer создаёт ещё один (container.py:46). Итого 3 pool'а (events via API, events via sink, lists) × max 10 = 30 connections.

  Предложение: Передать в EventSink уже существующий PostgresEventDatabase инстанс.

  - CPU impact: LOW (меньше connections = меньше overhead)
  - Accuracy risk: NONE
  - Complexity: LOW
  - Файлы: runtime/event_sink.py, runtime/channel_runtime.py, app/api/container.py

  6.4.2 JPEG-сохранение screenshots блокирует канал

  Текущее поведение: _save_jpeg() вызывает cv2.imwrite() синхронно в channel thread (channel_runtime.py:264-265). При медленном диске это блокирует processing loop.

  Предложение: Отправлять JPEG-сохранение в отдельный I/O thread pool:

  io_pool.submit(self._save_jpeg, frame_file, frame)

  - CPU impact: LOW-MEDIUM (разблокирует channel thread от I/O wait)
  - Accuracy risk: NONE (fire-and-forget для screenshots)
  - Complexity: LOW
  - Файлы: runtime/channel_runtime.py

  6.5 Конфигурационные тюнинги

  Текущие настройки, которые уже дают большой эффект:

  ┌───────────────────────┬─────────┬─────────────────────────────────┬─────────────────────────────────────────────────────┐
  │       Настройка       │ Default │    Рекомендация CPU-экономии    │                        Риск                         │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ detector_frame_stride │ 2       │ 3–4 для дальних камер           │ Может пропустить быстрый автомобиль                 │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ detection_mode        │ motion  │ Всегда motion для CPU           │ Потеря номеров при постоянном движении              │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ motion_release_frames │ 100     │ 50–200 в зависимости от трафика │ Слишком малое значение — пропуск задержавшихся авто │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ best_shots            │ 3       │ 3 (оптимально)                  │ < 2 = нет консенсуса                                │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ max_ocr_attempts      │ 15      │ 8–10 при хорошем освещении      │ Снижение при сложных условиях                       │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ ocr_min_confidence    │ 0.6     │ 0.5–0.7                         │ Ниже = больше false positives                       │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ cooldown_seconds      │ 5       │ 10–30 для парковок              │ Пропуск быстрых повторных проездов                  │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ size_filter_enabled   │ true    │ true всегда                     │ —                                                   │
  ├───────────────────────┼─────────┼─────────────────────────────────┼─────────────────────────────────────────────────────┤
  │ min_plate_size.width  │ 80      │ 100+ для дальних камер          │ Пропуск мелких номеров                              │
  └───────────────────────┴─────────┴─────────────────────────────────┴─────────────────────────────────────────────────────┘

  Preset: Слабый CPU / 1 канал

  detector_frame_stride: 2
  detection_mode: motion
  motion_release_frames: 60
  best_shots: 3
  max_ocr_attempts: 10
  min_plate_size: {width: 100, height: 25}
  # + OMP_NUM_THREADS=4

  Preset: Средний CPU / 2–4 канала

  detector_frame_stride: 3
  detection_mode: motion
  motion_release_frames: 100
  best_shots: 3
  max_ocr_attempts: 12
  min_plate_size: {width: 80, height: 20}
  # + OMP_NUM_THREADS=2

  Preset: Максимальная пропускная способность / 4+ каналов

  detector_frame_stride: 4
  detection_mode: motion
  motion_release_frames: 150
  best_shots: 3
  max_ocr_attempts: 8
  ocr_min_confidence: 0.65
  min_plate_size: {width: 120, height: 30}
  # + OMP_NUM_THREADS=1
  # + disable_video_output: true (если preview не нужен)

  Самые опасные настройки для неправильного тюнинга:

  1. best_shots: 1 — отключает консенсус, любой мусор проходит
  2. max_ocr_attempts: 1-2 — недостаточно попыток для сложных номеров
  3. detector_frame_stride: > 5 — может пропустить быстро проезжающие авто
  4. motion_threshold: > 0.05 — не заметит плавное движение
  5. ocr_min_confidence: > 0.8 — отвергает большинство корректных распознаваний

  ---
  7. Лучшие изменения для реализации в первую очередь

  Quick Wins (1–2 часа каждый, высокий ROI)

  1. Установить OMP_NUM_THREADS / torch thread limits — 3 строки в Dockerfile
  2. Lazy JPEG encode — ~20 строк, проверка флага has_consumers
  3. Motion detector на downscaled frame — 2 строки
  4. Skip preprocessor для мелких bbox — 3 строки early return

  Medium Effort (0.5–2 дня)

  5. Адаптивный detector stride — по наличию активных треков
  6. Передать shared events_db в EventSink — устранить дубль pool
  7. Асинхронное сохранение screenshots — io_pool
  8. Grayscale passthrough в CRNN — убрать дублирующий cvtColor

  ---
  8. Рискованные идеи, которые стоит отложить

  ┌───────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │               Идея                │                                                   Почему рискованно                                                    │
  ├───────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ ProcessPoolExecutor для OCR       │ IPC overhead на передачу numpy arrays; сложная отладка; нужен shared memory для batch. Оправдано только при 4+ каналах │
  ├───────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Замена CRNN на ONNX Runtime       │ Может дать 2–3x ускорение inference, но требует перетренировки/экспорта модели и тестирования точности                 │
  ├───────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ YOLO downscale/resize             │ YOLO обучена на определённом разрешении; downscale может убить detection мелких номеров                                │
  ├───────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Async DB через psycopg async      │ Потребует переписать весь DAL; канальные потоки синхронные, а async DB нужен для API side                              │
  ├───────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Полный переход на multiprocessing │ Требует радикальной реархитектуры; shared state (ChannelContext, metrics, preview) усложняется                         │
  ├───────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
  │ YOLO export в ONNX + OpenCV DNN   │ Может убрать зависимость от ultralytics, но tracker API потеряется                                                     │
  └───────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

  ---
  9. Финальный приоритизированный план действий

  Фаза 1: Быстрые wins (суммарно ~20–35% CPU экономии)

  ┌─────┬───────────────────────────────────┬───────────────────────┬──────────┬─────────────────────────────────┐
  │  #  │             Действие              │      CPU-выигрыш      │   Риск   │              Файлы              │
  ├─────┼───────────────────────────────────┼───────────────────────┼──────────┼─────────────────────────────────┤
  │ 1   │ OMP_NUM_THREADS=2 в Dockerfile    │ 15–30% при 3+ каналах │ NONE     │ Dockerfile, .env.example        │
  ├─────┼───────────────────────────────────┼───────────────────────┼──────────┼─────────────────────────────────┤
  │ 2   │ Lazy JPEG encode                  │ 8–12% на канал        │ NONE     │ channel_runtime.py, channels.py │
  ├─────┼───────────────────────────────────┼───────────────────────┼──────────┼─────────────────────────────────┤
  │ 3   │ Motion detector downscale         │ 2–4% на 1080p+        │ VERY LOW │ motion_detector.py              │
  ├─────┼───────────────────────────────────┼───────────────────────┼──────────┼─────────────────────────────────┤
  │ 4   │ Skip preprocessor для мелких bbox │ 2–5%                  │ LOW      │ plate_preprocessor.py           │
  └─────┴───────────────────────────────────┴───────────────────────┴──────────┴─────────────────────────────────┘

  Фаза 2: Средние улучшения (~10–20% дополнительно)

  ┌─────┬────────────────────────────────────┬────────────────┬────────┬───────────────────────────────────────────┐
  │  #  │              Действие              │  CPU-выигрыш   │  Риск  │                   Файлы                   │
  ├─────┼────────────────────────────────────┼────────────────┼────────┼───────────────────────────────────────────┤
  │ 5   │ Адаптивный detector stride         │ 5–15% при idle │ LOW    │ channel_runtime.py                        │
  ├─────┼────────────────────────────────────┼────────────────┼────────┼───────────────────────────────────────────┤
  │ 6   │ Early exit по consecutive failures │ 3–8%           │ MEDIUM │ anpr_pipeline.py                          │
  ├─────┼────────────────────────────────────┼────────────────┼────────┼───────────────────────────────────────────┤
  │ 7   │ Async screenshot save              │ 2–5%           │ NONE   │ channel_runtime.py                        │
  ├─────┼────────────────────────────────────┼────────────────┼────────┼───────────────────────────────────────────┤
  │ 8   │ Объединить connection pools        │ 1–2%           │ NONE   │ event_sink.py, container.py               │
  ├─────┼────────────────────────────────────┼────────────────┼────────┼───────────────────────────────────────────┤
  │ 9   │ Grayscale passthrough              │ 1–2%           │ NONE   │ plate_preprocessor.py, crnn_recognizer.py │
  └─────┴────────────────────────────────────┴────────────────┴────────┴───────────────────────────────────────────┘

  Фаза 3: Архитектурные (отложить до необходимости)

  ┌─────┬───────────────────────────────────┬─────────────┬────────┬──────────────────────────────────────┐
  │  #  │             Действие              │ CPU-выигрыш │  Риск  │                Файлы                 │
  ├─────┼───────────────────────────────────┼─────────────┼────────┼──────────────────────────────────────┤
  │ 10  │ OCR worker pool (ThreadPool)      │ 5–10%       │ LOW    │ factory.py, anpr_pipeline.py         │
  ├─────┼───────────────────────────────────┼─────────────┼────────┼──────────────────────────────────────┤
  │ 11  │ Cross-channel OCR batching        │ 10–20%      │ MEDIUM │ channel_runtime.py, anpr_pipeline.py │
  ├─────┼───────────────────────────────────┼─────────────┼────────┼──────────────────────────────────────┤
  │ 12  │ ProcessPoolExecutor для inference │ 15–25%      │ HIGH   │ Множество файлов                     │
  └─────┴───────────────────────────────────┴─────────────┴────────┴──────────────────────────────────────┘

  ---
  Сводная таблица

  ┌─────────────────────────────────┬───────────────────────┬───────────────┬─────────────┬───────────────────────────────────────────┐
  │              Идея               │ Ожидаемый CPU-выигрыш │ Риск точности │  Сложность  │              Ключевые файлы               │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ OMP_NUM_THREADS ограничение     │ HIGH (15–30%)         │ None          │ Very Low    │ Dockerfile, .env.example                  │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Lazy JPEG encode                │ HIGH (8–12%/канал)    │ None          │ Low         │ channel_runtime.py, channels.py           │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Motion downscale                │ Low-Medium (2–4%)     │ Very Low      │ Very Low    │ motion_detector.py                        │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Skip preprocessor мелких bbox   │ Medium (2–5%)         │ Low           │ Very Low    │ plate_preprocessor.py                     │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Адаптивный detector stride      │ Medium (5–15%)        │ Low           │ Low         │ channel_runtime.py                        │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Early exit consecutive failures │ Medium (3–8%)         │ Medium        │ Low         │ anpr_pipeline.py                          │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Async screenshot save           │ Low-Medium (2–5%)     │ None          │ Low         │ channel_runtime.py                        │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Merge connection pools          │ Low (1–2%)            │ None          │ Low         │ event_sink.py, container.py               │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Grayscale passthrough           │ Low (1–2%)            │ None          │ Low         │ plate_preprocessor.py, crnn_recognizer.py │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ OCR worker pool (Thread)        │ Medium (5–10%)        │ None          │ Medium      │ factory.py, anpr_pipeline.py              │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ Cross-channel batching          │ Medium-High (10–20%)  │ None          │ Medium-High │ channel_runtime.py, anpr_pipeline.py      │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ ProcessPoolExecutor             │ High (15–25%)         │ None          │ High        │ Множество файлов                          │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ ONNX Runtime для CRNN           │ High (20–40%)         │ Medium        │ High        │ crnn_recognizer.py, crnn.py               │
  ├─────────────────────────────────┼───────────────────────┼───────────────┼─────────────┼───────────────────────────────────────────┤
  │ YOLO → ONNX + DNN backend       │ Medium-High (10–20%)  │ High          │ Very High   │ yolo_detector.py                          │
  └─────────────────────────────────┴───────────────────────┴───────────────┴─────────────┴───────────────────────────────────────────┘
