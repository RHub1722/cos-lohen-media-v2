# Контракт Atlas Cloud

Снято 3 августа 2026 со схемы модели `bytedance/seedance-2.0-mini/reference-to-video`
на <https://www.atlascloud.ai/models/bytedance/seedance-2.0-mini/reference-to-video>.

`tools/atlas_gen.py` берёт имена полей только отсюда. Atlas поменяет схему —
править здесь, в одном месте.

---

## Эндпоинты

```
Загрузка файла
  POST https://api.atlascloud.ai/api/v1/model/uploadMedia
  Authorization: Bearer <ключ>
  multipart/form-data, файл в поле "file"
  Ответ: JSON со ссылкой в "url". Ссылки временные, файлы чистятся периодически.

Отправка задания (асинхронно)
  POST https://api.atlascloud.ai/api/v1/model/generateVideo
  Authorization: Bearer <ключ>
  Content-Type: application/json

Опрос
  GET https://api.atlascloud.ai/api/v1/model/prediction/{prediction_id}
  Authorization: Bearer <ключ>
  Опрашивать примерно раз в две секунды, вебхуки не нужны.
```

---

## Что нам нужно и как это называется

| наше значение | поле | тип | значение у нас |
|---|---|---|---|
| модель | `model` | string, **обязательное** | `bytedance/seedance-2.0-mini/reference-to-video` |
| промпт | `prompt` | string | текст кадра из `shots.json` |
| референсы | `reference_images` | array[string], 1–9 | ссылки из `uploadMedia` |
| длительность | `duration` | integer | из `shots.json`, целое 4–15 |
| разрешение | `resolution` | string | `480p` на пробе, `720p` в продакшене |
| пропорции | **`ratio`** | string | `16:9` |
| битрейт | `bitrate_mode` | string | `standard` |
| генерировать звук | `generate_audio` | boolean | **`false`** |
| водяной знак | `watermark` | boolean | **`false`** |
| вернуть последний кадр | `return_last_frame` | boolean | `false` |

### Запретов отдельным полем НЕТ

**У модели нет `negative_prompt`.** Это главная неожиданность схемы: всё, что мы
считаем запретами, приходится дописывать в конец самого промпта. Поле `negative`
в `scenario/shots.json` остаётся — оно документирует замысел и проверяется
тестами, — но в запрос уходит склеенным с `prompt`, а не отдельно.

### Значения по умолчанию, которые надо перебить

| поле | по умолчанию | почему меняем |
|---|---|---|
| `generate_audio` | **`true`** | мастер-звук готов и лежит в `output/master_v2.wav`. Дорожка от модели нам не нужна ни в каком виде |
| `ratio` | `adaptive` | берёт пропорции первого референса. У нас референсы разных пропорций, кадр должен быть строго 16:9 |
| `duration` | `5` | у нас своя длина на каждый кадр, и она не 5 |

`watermark` и `return_last_frame` по умолчанию уже `false` — но передаём явно,
потому что молчаливая смена дефолта на стороне сервиса стоила бы водяного знака
в готовом номере, а виден он с любого места в зале.

---

## Полная схема входа

```
model               string, ОБЯЗАТЕЛЬНОЕ
reference_images    array[string], 1..9   ссылки, Base64 или asset://<ID>
reference_videos    array[string], 1..3   суммарно не больше 15 с
reference_audios    array[string], 1..3   wav/mp3, 2..15 с, до 15 МБ
prompt              string                «image 1», «video 1» ссылаются на входы по порядку
duration            integer               -1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15
resolution          string                480p | 720p | 720p-SR | 1080p-SR | 1440p-SR
ratio               string                16:9 | 4:3 | 1:1 | 3:4 | 9:16 | 21:9 | adaptive
bitrate_mode        string                standard | high (на стоимость не влияет)
generate_audio      boolean               по умолчанию true
watermark           boolean               по умолчанию false
return_last_frame   boolean               по умолчанию false
```

### Лимиты на каждое референсное изображение

```
форматы           jpeg, png, webp, bmp, tiff, gif, heic, heif
пропорции (W/H)   0.4 .. 2.5
ширина и высота   300 .. 6000 px
вес               меньше 30 МБ
```

Все 22 файла в `assets/screenshots/` проверены и проходят: пропорции от 1.07 до
2.20, минимальная сторона 498 px, самый тяжёлый файл 2.0 МБ.

### Как промпт ссылается на референсы

Схема: «References like 'image 1', 'video 1' refer to inputs in order».
Плейграунд пишет то же самое с собачкой:

```
Car 1 @image1 is speeding along the highway @image3, while Car 2 @image2,
with its hazard lights flashing, is rapidly closing in from the rear left.
```

Порядок токенов соответствует порядку в `reference_images`. Наши промпты
используют форму `@image1` и дополнительно перечисляют роли прозой в конце: если
собачку модель не поймёт, проза останется.

---

## Ответ

Тело завёрнуто в конверт: **идентификатор лежит в `data.id`, а не в корне.**

```json
{"code": 200, "data": {"id": "prediction_id", "status": "processing"}}
```

Схема самого объекта предсказания:

```
id                  string    идентификатор
urls                object    связанные эндпоинты
model               string
status              string    processing | completed | failed | timeout
outputs             array[string]   ссылки на результат
created_at          string
completion_tokens   integer   израсходовано на биллинг
total_tokens        integer
has_nsfw_contents   array[boolean]
```

**Статусов успеха два.** Схема перечисляет `completed`, а пример в cURL пишет
«keep polling until status is `completed`, `succeeded` or `failed`». Считать
успехом оба слова, иначе задание будет опрашиваться до таймаута на уже готовом
результате.

**Биллинг в токенах, а не в секундах.** В ответе есть `total_tokens` — это
настоящее списание. Наши `$0.056/с` и `$0.061/с` только оценка, поэтому в журнал
`docs/atlas-ledger.csv` пишется и оценка, и фактические токены, и сверяются они
уже по кабинету.

**`outputs` может содержать больше одного элемента**: при
`return_last_frame: true` туда добавляется отдельная картинка последнего кадра.
У нас флаг выключен, поэтому берём `outputs[0]`, но если флаг когда-нибудь
включат — проверять, что скачивается именно видео.
