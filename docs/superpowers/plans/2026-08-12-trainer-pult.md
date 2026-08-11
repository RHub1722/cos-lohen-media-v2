# Пульт: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** вкладка тренажёра, где ролик номера и клип приёма идут одновременно под одними часами, плюс окно предпросмотра следующего приёма.

**Architecture:** новых данных нет — окна приёмов считаются в браузере из `DATA.clips[].beats`, которые уже уезжают в страницу. Ролик номера остаётся единственным: панель с ним уже левая колонка сетки, и в этом виде ей разрешается стать широкой через `--railw`. Слот «сейчас» ведётся часами номера: темп клипа = темп номера × его замедление, расхождение больше 0.15 с правится одним прыжком.

**Tech Stack:** `src/training_template.html` (самодостаточный HTML с вшитыми данными), pytest для проверок времён, FFmpeg не нужен — ни одного нового файла.

**Решение:** [docs/superpowers/specs/2026-08-12-trainer-pult-design.md](../specs/2026-08-12-trainer-pult-design.md)

---

## Что уже готово и трогать не надо

- полоса времени в подвале: метки контактов, движений, сцен, клик — переход, петля, шаг кадром, темп 0.25–1×;
- плеер номера `#video` в `<aside class="rail">`, `--railw` участвует в `grid-template-columns` с 640 px;
- `DATA.clips[]` с полями `file`, `poster`, `w`, `h`, `duration`, `real`, `slow`, `title`, `strike`, `beats[]`;
- `render(t)` вызывается каждый кадр из `frame()` и уже разделяет работу по видам через `currentView`;
- помощники `$`, `el`, `fmt1`, `seek`, `ROLE_NAMES`, `activeIndex`.

## Файлы

| файл | что делает |
|---|---|
| `src/training_template.html` | вся вкладка: разметка, стили, логика окон и ведения |
| `tests/test_render_training.py` | проверки времён и порядка вкладок |
| `README.md` | «пять видов» → «шесть видов» |
| `docs/status/2026-08-12-trainer-pult.md` | точка состояния |
| `docs/status/INDEX.md` | строка в таблице |

---

### Task 1: Проверки времён

Это тесты-сторожа: они защищают свойства, которые в данных **уже верны**, и на
первом прогоне пройдут. Ценность в том, что они упадут, если свойство сломают.
Что каждый ловит — сказано в его строке документации.

**Files:**
- Modify: `tests/test_render_training.py`

- [ ] **Step 1: Дописать четыре проверки в конец файла, перед `test_render_leaves_no_marker_and_closes_no_script`**

```python
def test_the_windows_of_the_strikes_do_not_overlap(payload):
    """Окно приёма — от слышимого времени первой доли клипа до последней. Вид
    «Пульт» выбирает по ним, какой приём идёт сейчас, и если два окна налезут
    друг на друга, слот начнёт мигать между двумя клипами на каждом кадре."""
    windows = sorted(((c["beats"][0]["heard"], c["beats"][-1]["heard"], c["id"])
                      for c in payload["clips"]))
    for (start, end, cid) in windows:
        assert 0 < start < end < payload["total"], cid
    for (a_start, a_end, a_id), (b_start, b_end, b_id) in zip(windows, windows[1:]):
        assert a_end <= b_start, "окна %s и %s налезают" % (a_id, b_id)


def test_the_clips_reach_the_page_in_the_order_of_the_number(payload):
    """Вид «Пульт» сортирует окна сам, но если в данных порядок сбился, значит
    сбился он и в сценарии клипов — а там по нему читают глазами."""
    starts = [c["beats"][0]["heard"] for c in payload["clips"]]
    assert starts == sorted(starts)


def test_no_clip_asks_the_browser_for_an_impossible_speed(payload):
    """Слот «сейчас» ведётся темпом: playbackRate = темп номера × замедление
    клипа. Предел в браузере — 16, и выше он зажимает темп МОЛЧА: синхронизация
    выродится в перемотку каждые 0.15 с, и никто об этом не узнает."""
    for clip in payload["clips"]:
        assert 1.0 < clip["slow"] <= 16.0, (clip["id"], clip["slow"])


def test_only_the_second_contact_of_burst_2_has_no_clip(payload):
    """Дыра, о которой вид «Пульт» обязан сказать вслух: контакт в 36.58 не
    покрыт ни одним клипом — burst_2 показывает четыре доли из пяти. Тест
    сторожит и обратное: если однажды покрытие изменится, подпись на странице
    станет ложной, и заметить это будет негде."""
    windows = [(c["beats"][0]["heard"], c["beats"][-1]["heard"])
               for c in payload["clips"]]
    uncovered = [round(h["t"], 2) for h in payload["hits"]
                 if not any(start <= h["t"] <= end for start, end in windows)]
    assert uncovered == [36.58]
```

- [ ] **Step 2: Прогнать**

Run: `python -m pytest tests/test_render_training.py -q -k "windows or order_of_the_number or impossible_speed or second_contact"`
Expected: `4 passed`

- [ ] **Step 3: Убедиться, что сторож работает**

Временно поменять в `test_only_the_second_contact_of_burst_2_has_no_clip`
ожидание на `assert uncovered == []`, прогнать тот же тест, увидеть
`AssertionError: assert [36.58] == []`, вернуть `[36.58]` обратно.

Смысл шага: проверка, которая проходит всегда, ничего не сторожит.

- [ ] **Step 4: Коммит**

```bash
git add tests/test_render_training.py
git commit -m "test: сторожа времён под вид «Пульт» — окна, темп, непокрытый контакт"
```

---

### Task 2: Вид «Пульт»

**Files:**
- Modify: `src/training_template.html`
- Modify: `tests/test_render_training.py` (порядок вкладок)

- [ ] **Step 1: Стили. Вставить перед строкой `/* ── вид «Клипы» ─────`**

```css
  /* ── вид «Пульт» ─────────────────────────────────────────────────────── */
  /* Панель с роликом номера становится главной колонкой только здесь. Второго
     плеера не создаём: тот же файл скачивался бы и расшифровывался дважды, а
     перенос живого <video> по DOM в части браузеров сбрасывает воспроизведение. */
  body[data-view="pult"] { --railw: 58%; }
  .pult-note { margin: 0 0 10px; font-size: 0.88rem; }
  .duo { display: grid; gap: 10px; }
  .slot {
    display: grid; gap: 6px;
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 8px 10px;
  }
  .slot video {
    display: block; width: 100%; height: auto;
    border-radius: 8px; background: #000;
  }
  /* Приёма сейчас нет — держим прошедший стоп-кадром, но приглушённо, чтобы он
     не читался как происходящее. */
  .slot.idle video { opacity: 0.34; }
  .slot .cap { font-size: 0.82rem; color: var(--muted); min-height: 2.4em; }
  .slot .cap b { color: var(--accent); font-weight: 700; }
```

- [ ] **Step 2: Разметка. Вставить перед комментарием `<!-- Тренировочные клипы:`**

```html
  <!-- id не `pult`: то же правило, что у видов «Движения» и «Клипы» — имя вида
       уезжает в хеш адреса, и браузер прокрутил бы страницу к элементу с таким
       же id поверх нашего showView. Ролика номера здесь нет: он в левой панели,
       и панели в этом виде разрешено стать широкой. -->
  <section class="view" id="view-pult">
    <p class="warn pult-note">Клип справа встаёт в верную точку <b>окна</b>, но
    не обязательно в верную <b>позу</b>: внутри себя клипы врут про время — у
    части 1 вспышки 3 весь оборот кончен к 2.55 с из 5.04. Он отвечает, какой
    приём идёт сейчас, а не в какой ты позе.</p>
    <div class="duo">
      <div class="slot" id="slotNow">
        <div class="label">Сейчас</div>
        <video id="clipNow" playsinline preload="auto" muted></video>
        <div class="cap" id="capNow">—</div>
      </div>
      <div class="slot" id="slotNext">
        <div class="label">Дальше</div>
        <video id="clipNext" playsinline preload="auto" muted loop></video>
        <div class="cap" id="capNext">—</div>
      </div>
    </div>
  </section>
```

- [ ] **Step 3: Вкладка. Заменить список `VIEWS`**

```javascript
const VIEWS = [
  ["run", "Прогон"],
  ["pult", "Пульт"],
  ["fight", "Бой"],
  ["clips", "Клипы"],
  ["moves", "Движения"],
  ["how", "Как тренироваться"],
];
```

- [ ] **Step 4: Логика окон. Вставить перед комментарием `// ── вид «Клипы» ───`**

```javascript
// ── вид «Пульт» ───────────────────────────────────────────────────────────
// Окно приёма — от слышимого времени первой доли клипа до последней. Порядок
// задаём сортировкой, а не верой в порядок в данных.
const PULT = (DATA.clips || [])
  .map((c) => ({ clip: c, from: c.beats[0].heard, to: c.beats[c.beats.length - 1].heard }))
  .sort((a, b) => a.from - b.from);
const DRIFT = 0.15;        // допуск расхождения клипа с часами номера, секунды
const clipNow = $("clipNow");
const clipNext = $("clipNext");

// Стык 39.92 достаётся второму клипу: там кончается часть 1 вспышки 3 и с этого
// же мгновения начинается часть 2. Без строгого `<` слот мигал бы между ними.
function windowAt(t) {
  for (const w of PULT) if (t >= w.from && t < w.to) return w;
  return null;
}
function windowBefore(t) {
  let found = null;
  for (const w of PULT) if (w.to <= t) found = w;
  return found;
}
function windowAfter(t) {
  for (const w of PULT) if (w.from > t) return w;
  return null;
}
// Контакт, которого нет ни в одном клипе. Не вписан числом: у вспышки 2 второе
// попадание в 36.58 действительно не покрыто, а у вспышки 3 второе попадание
// покрыто частью 2 — разница видна только проверкой по всем окнам.
function uncoveredAfter(w) {
  const strike = DATA.strikes.find((s) => s.id === w.clip.strike);
  if (!strike) return null;
  return strike.beats.find((b) => b.role === "contact" && b.heard > w.to + 0.001
    && !PULT.some((x) => b.heard >= x.from && b.heard <= x.to)) || null;
}

// Источник ставится только при смене клипа: присваивать src каждый кадр значит
// перезапускать загрузку шестьдесят раз в секунду.
function setClip(v, clip) {
  const id = clip ? clip.id : "";
  if (v.dataset.clip === id) return;
  v.dataset.clip = id;
  if (!clip) {
    v.removeAttribute("src");
    v.removeAttribute("poster");
    v.load();
    return;
  }
  v.style.aspectRatio = (clip.w && clip.h) ? clip.w + " / " + clip.h : "";
  v.poster = clip.poster;
  v.src = clip.file;
}
```

- [ ] **Step 5: Ведение часами. Дописать сразу за кодом шага 4**

```javascript
// Ведём клип часами номера. Не перемоткой каждый кадр — это семьдесят перемоток
// в секунду по потоку без опорных кадров под каждую, и на планшете это заикание.
// Вместо этого выставляется темп, а прыжок делается только когда разошлось.
function drive(v, want, rate) {
  if (v.readyState < 1) return;               // метаданных нет — перематывать нечего
  const at = Math.max(0, Math.min(v.duration || want, want));
  if (rate > 0) {
    if (v.dataset.rate !== String(rate)) {
      v.dataset.rate = String(rate);
      v.playbackRate = rate;
    }
    if (v.paused) v.play().catch(() => {});
    if (Math.abs(v.currentTime - at) > DRIFT) v.currentTime = at;
  } else {
    if (!v.paused) v.pause();
    if (Math.abs(v.currentTime - at) > 0.01) v.currentTime = at;
  }
}

function pult(t) {
  const now = windowAt(t);
  const shown = now || windowBefore(t);
  const nxt = windowAfter(t);
  setClip(clipNow, shown ? shown.clip : null);
  setClip(clipNext, nxt ? nxt.clip : null);
  $("slotNow").classList.toggle("idle", !now);

  if (shown) {
    const c = shown.clip;
    // Идёт приём — линейно по окну; прошёл — стоп-кадром на последнем кадре.
    const want = now
      ? (t - now.from) / (now.to - now.from) * c.duration
      : c.duration - 0.04;
    drive(clipNow, want, now && !video.paused ? video.playbackRate * c.slow : 0);
  }
  // «Дальше» крутится своим темпом и встаёт вместе с номером: два разных
  // состояния на одном экране путают больше, чем помогают.
  if (nxt && clipNext.readyState >= 1) {
    if (clipNext.dataset.rate !== "1") { clipNext.dataset.rate = "1"; clipNext.playbackRate = 1; }
    if (video.paused) { if (!clipNext.paused) clipNext.pause(); }
    else if (clipNext.paused) clipNext.play().catch(() => {});
  }

  if (now) {
    const beat = now.clip.beats.filter((b) => b.heard <= t + 0.001).pop()
      || now.clip.beats[0];
    $("capNow").innerHTML = "<b>" + now.clip.title + "</b><br>доля: "
      + (ROLE_NAMES[beat.role] || beat.role) + " " + beat.heard.toFixed(2);
  } else if (shown) {
    const late = uncoveredAfter(shown);
    $("capNow").innerHTML = "прошёл: <b>" + shown.clip.title + "</b>"
      + (late ? "<br>попадание в " + late.heard.toFixed(2)
                + " в клип не вошло — держишь его сам" : "");
  } else {
    $("capNow").innerHTML = "приёмов ещё не было<br>первый в "
      + (PULT.length ? PULT[0].from.toFixed(2) : "—");
  }
  $("capNext").innerHTML = nxt
    ? "<b>" + nxt.clip.title + "</b><br>через " + Math.max(0, nxt.from - t).toFixed(1) + " с"
    : "ударов больше нет<br>дальше лёд";
}
```

- [ ] **Step 6: Подключить к кадру. В функции `render(t)` вставить сразу после строки `$("cur").textContent = fmt1(t);`**

```javascript
  if (currentView === "pult") pult(t);
```

- [ ] **Step 7: Остановить клипы при уходе с вида. В `showView` заменить строку `window.scrollTo({ top: 0 });`**

```javascript
  // Вид уезжает в атрибут body: по нему стилями включается широкая панель.
  document.body.dataset.view = name;
  // Ушли с пульта — клипы не должны играть за кадром.
  if (name !== "pult") { clipNow.pause(); clipNext.pause(); }
  window.scrollTo({ top: 0 });
```

- [ ] **Step 8: Дописать вкладку в список видов на вкладке «Как тренироваться». Вставить сразу после пункта `<li><b>Прогон</b> …</li>`**

```html
          <li><b>Пульт</b> — ролик номера и клип приёма рядом, под одними
          часами: слева то, что зал видит за спиной, справа то, что ты в этот
          момент делаешь, и предпросмотр следующего приёма. Клипов на бой семь,
          и покрывают они 9.4 секунды из шестидесяти — остальное время справа
          стоит стоп-кадр прошедшего приёма.</li>
```

- [ ] **Step 9: Поправить тест порядка вкладок**

В `tests/test_render_training.py`, в `test_every_tab_of_the_page_has_a_section_to_show`:

```python
    assert names == ["run", "pult", "fight", "clips", "moves", "how"]
```

- [ ] **Step 10: Собрать страницу**

Run: `python src/render_training.py`
Expected: последняя строка — `тренировочных клипов: 7 в output\clips (9.7 МБ с постерами)`, без ошибок.

- [ ] **Step 11: Прогнать тесты вида**

Run: `python -m pytest tests/test_render_training.py -q`
Expected: `18 passed` (было 14, добавлено 4)

- [ ] **Step 12: Приёмка глазами, по списку из решения**

Открыть `output/training.html`, вкладка «Пульт»:

1. пробел — фон играет, справа «сейчас» пусто с подписью «первый в 28.50», «дальше» крутит вспышку 1 петлёй;
2. на 28.50 справа сам встаёт `burst_1` и едет вместе с фоном, «дальше» переключается на вспышку 2;
3. темп 0.25× — приём идёт плавно, примерно своим темпом;
4. пауза и шаг кадром (`.`): оба видео шагают вместе;
5. на 39.92 в «сейчас» — часть 2 вспышки 3, без мигания;
6. на 35.0 — «прошёл: Вспышка 2» и приписка про попадание в 36.58;
7. на 47.63 и дальше — финал стоп-кадром, «дальше» говорит, что ударов больше нет;
8. ширина 375 px — столбик фон → «сейчас» → «дальше», горизонтальной прокрутки нет;
9. в консоли браузера ошибок нет.

- [ ] **Step 13: Коммит**

```bash
git add src/training_template.html tests/test_render_training.py
git commit -m "train: вид «Пульт» — ролик номера и клип приёма под одними часами"
```

---

### Task 3: Публикация и документы

**Files:**
- Modify: `README.md`
- Create: `docs/status/2026-08-12-trainer-pult.md`
- Modify: `docs/status/INDEX.md`
- Modify: `site/index.html` (пересборка)

- [ ] **Step 1: README — заменить строку про виды**

```markdown
| `src/render_training.py` | тренажёр: плеер, разбор боя, тренировочные клипы, шесть видов |
```

- [ ] **Step 2: Точка состояния**

Создать `docs/status/2026-08-12-trainer-pult.md`: что появилось, как ведётся слот
«сейчас» и с каким допуском, чего вид не показывает (поза внутри клипа,
непокрытый контакт 36.58), что вынесено из захода (двадцать шесть отметок долей),
число тестов.

- [ ] **Step 3: Строка в INDEX.md**

Добавить сверху таблицы «История», по образцу соседних строк.

- [ ] **Step 4: Пересобрать опубликованную копию**

Run: `python src/render_training.py --site`
Expected: `Готово: …\site\index.html`, клипы 7, вес не изменился

- [ ] **Step 5: Полный прогон тестов**

Run: `python -m pytest -q`
Expected: `407 passed` (было 403, добавлено 4)

- [ ] **Step 6: Коммит и пуш в обе ветки**

```bash
git add README.md docs/status site/index.html
git commit -m "train: пульт на сайте, точка состояния"
git push origin main
git push origin main:master
```

- [ ] **Step 7: Проверить, что Pages отдал новую страницу**

Run: `curl -s https://rhub1722.github.io/cos-lohen-media-v2/site/ | grep -c 'id="view-pult"'`
Expected: `1` (Pages пересобирается около 75 секунд — если `0`, повторить)

---

## Самопроверка плана против решения

| требование решения | где сделано |
|---|---|
| вкладка «Пульт», второй, `#pult`, `id="view-pult"` | Task 2, шаги 2–3 |
| фон — существующий плеер, второго нет | Task 2, шаг 1 (`--railw` под `body[data-view]`) |
| слот «сейчас», окно `from ≤ t < to` | Task 2, шаг 4 (`windowAt`) |
| между окнами — стоп-кадр прошедшего, приглушённо | Task 2, шаги 1 и 5 (`.idle`, `c.duration - 0.04`) |
| до первого удара пусто, после финала стоп-кадр | Task 2, шаг 5 (ветки подписи) |
| слот «дальше», петлёй, темпом 1×, встаёт с номером | Task 2, шаги 2 и 5 |
| темп = темп номера × замедление, сверка 0.15 с | Task 2, шаг 5 (`drive`) |
| пауза и шаг кадром — точная перемотка | Task 2, шаг 5 (ветка `rate = 0`) |
| оговорка про позу — одной строкой над слотами | Task 2, шаг 2 |
| дыра 34.55–36.58 сказана вслух | Task 2, шаг 5 (`uncoveredAfter`) |
| стык 39.92 — второму клипу | Task 2, шаг 4 |
| подписи из данных | Task 2, шаг 5 |
| тест: окна не налезают | Task 1 |
| тест: замедление ≤ 16 | Task 1 |
| тест: 36.58 не покрыт | Task 1 |
| тест: у вкладки есть раздел | Task 2, шаг 9 (существующий тест) |
| риск: три потока, узкий экран, зажатый темп | Task 2, шаг 12 (приёмка глазами) |
| пункт в списке видов на «Как тренироваться» | Task 2, шаг 8 |

Заглушек в плане нет: каждый шаг, меняющий код, несёт код целиком. Имена
сходятся между шагами: `PULT`, `DRIFT`, `clipNow`, `clipNext`, `windowAt`,
`windowBefore`, `windowAfter`, `uncoveredAfter`, `setClip`, `drive`, `pult`.
