# Сведение номера в REAPER — вторая версия звука

Здесь лежит проект, из которого пришла фонограмма, звучащая в номере сейчас.
Это **вторая версия звука**. Первая — процедурная сборка `src/render_audio.py`
по `scenario/timeline.json`; она цела, но в деле её больше нет.

Скопировано 8 августа 2026 из `Documents/REAPER Media/Project Anime Video`
как есть, ничего не переименовано и не переложено.

| | первая версия | вторая версия |
|---|---|---|
| чем собрано | `src/render_audio.py` | REAPER, руками |
| откуда время | `scenario/timeline.json` | расставлено на слух |
| мастер | `output/master_ru_lo_v41.wav` | `output/master_ru_fx.wav` |
| в номере | нет | **да** |

Приёмка второй версии — [docs/status/2026-08-08-fx-adopted.md](../../docs/status/2026-08-08-fx-adopted.md),
замеры попадания в картинку — [2026-08-08-fx-sync.md](../../docs/status/2026-08-08-fx-sync.md).

---

## Что где

```text
Project Anime Video.rpp    сам микс: 12 дорожек, 127 ссылок на файлы, 36 плагинов
Backups/                   15 автосохранений REAPER за 8 августа
Media/                     всё, из чего собран микс
```

**Проект открывается прямо отсюда.** Все ссылки внутри `.rpp` относительные
(`Media\...`), абсолютных путей ноль — копия самодостаточна. Плагины только
штатные Cockos: ReaEQ, ReaVerb, ReaVerbate, ReaComp, ReaLimit, ReaDelay,
ReaXcomp. Ничего стороннего доставлять не нужно.

### Media, 74 файла, 933 МБ

| что | сколько | размер | в гите |
|---|---|---|---|
| купленные mp3 под ручные FX | 19 | 5.8 МБ | **да** |
| наш экспорт дорожек под REAPER | 53 wav | 916 МБ | нет |
| ролик, под который сводили | 1 mp4 | 44.6 МБ | нет |
| кэш формы волны REAPER | 74 `.reapeaks` | 1.5 МБ | нет |

Два последних пункта — наши же файлы, сверено по хешу: дорожки совпадают с
`output/reaper_stems` бит в бит, ролик — с `output/final_ru_nostrip_titles.mp4`.
Класть их в репозиторий второй раз незачем, но **на диске они лежат здесь**, и
проект открывается без единого «файл не найден».

Если папка `Media` когда-нибудь окажется неполной после клонирования — дорожки
пересобираются разовым скриптом из `output/reaper_stems`, ролик собирается
командой из `tools/render_logo.py`, а `.reapeaks` REAPER построит сам.

---

## Девятнадцать mp3 — новая библиотека

Это то, чего в проекте раньше не было и что нельзя восстановить: купленный
материал, из которого сделаны ручные FX.

| файл | на что похоже по имени |
|---|---|
| `alexis_gaming_cam-riser-paper-415195` | ризер |
| `audiopapkin-big-robot-footstep-017-499567` | шаг машины |
| `audiopapkin-sound-design-elements-robot-mechanism-032-500870` | механизм |
| `djartmusic-many-arrows-flying-by-306037` | пролёт |
| `dragon-studio-electric-discharge-386160` | разряд |
| `dragon-studio-ice-spell-impact-448563` | ледяной удар |
| `dragon-studio-whoosh-cinematic-376875` | взмах |
| `floraphonic-epic-swoosh-boom-3-183998` | взмах с ударом |
| `freesound_community-action-thrill-atmosphere-29209` | подложка боя |
| `freesound_community-footsteps_boots_gritty_ground_gravel-6028` | шаги по гравию |
| `freesound_community-sandfall5-83468` | сыпучее |
| `freesound_community-werderchile_tired-breath-103236` | тяжёлое дыхание |
| `freesounds123-walking-on-wood-363349` | шаги по дереву |
| `lordsonny-punch-a-rock-161647` | удар по камню |
| `soundreality-riser-wildfire-285209` | ризер |
| `soundreality-wind-blowing-457954` | ветер |
| `u_1pruylktlg-riser-7-130957` | ризер |
| `worldlikeall-whispers-in-the-dark-253489` | шёпот |
| `yodguard-spear_thrust-1-382402` | выпад копьём |

Описания даны по именам файлов, а не по прослушиванию. Что именно и где стоит —
видно в `.rpp`, а не здесь.

Три ризера в этом списке закрывают запись 2 из
[docs/proposals.md](../../docs/proposals.md): вопрос «где взять ризер» снят, но
вопрос «нужен ли он в номере» решался уже здесь, на слух.

---

## Правило на будущее

**Медиафайлы номера теперь берутся отсюда.** Новая версия сведения — новая
папка рядом (`mix_v3` и так далее), а не правка этой: сравнить две версии
дороже, чем хранить обе.

После каждой новой выгрузки из REAPER:

```bash
python tools/adopt_audio.py --audio "output/<новый файл>.wav" --suffix fx2
```

Он проверит длину и сдвиг **до** того, как что-то делать, приведёт истинный пик
к −2.0 dBTP одним линейным гейном и переложит звук во все четыре копии, не
трогая картинку.
