# Голоса: что использовалось и что сгенерировано

Собран командой `python tools/voice_report.py` из `docs/eleven-voice-ledger.csv` — журнала, который пишется при каждом обращении к API. Кредиты — оценка на момент запроса; настоящее списание смотреть в дашборде.

Всего обращений: **119**, голосов задействовано: **11**, оценка расхода: **3565 кредитов**.

## Как читать метки

- `lo_v2`, `lo_v41`, `lo_v43` и прочие — **синтез** из текста соответствующим голосом аккаунта;
- `mysts<-lo_v2` — **преобразование живой записи**: игра и тайминг от исполнителя, тембр от `lo_v2`. Модель `eleven_multilingual_sts_v2`;
- `mystsalt<-lo_v2` — то же, но альтернативный дубль, только для сравнения на слух.

## Сводка по голосам

| метка | обращений | реплик | кредитов | модель |
|---|---|---|---|---|
| `mysts<-lo_v2` | 17 | 13 | 711 | eleven_multilingual_sts_v2 |
| `myvoicefordublo` | 16 | 13 | 362 | eleven_v3 |
| `lo_v2` | 15 | 13 | 318 | eleven_v3 |
| `lo_v41` | 14 | 13 | 326 | eleven_v3 |
| `mysts41<-lo_v41` | 13 | 13 | 476 | eleven_multilingual_sts_v2 |
| `mysts43<-lo_v43` | 13 | 13 | 476 | eleven_multilingual_sts_v2 |
| `mystsed<-edward` | 13 | 13 | 476 | eleven_multilingual_sts_v2 |
| `edward` | 12 | 12 | 262 | eleven_v3 |
| `lo_v43` | 4 | 4 | 92 | eleven_v3 |
| `mystsalt<-lo_v2` | 1 | 1 | 42 | eleven_multilingual_sts_v2 |
| `zYcjlYFO` | 1 | 1 | 24 | eleven_v3 |

## Что сгенерировано по репликам

| реплика | метка | сек | предел | влезает | файл |
|---|---|---|---|---|---|
| lohen_impressed | `myvoicefordublo` | 2.240 | 2.70 | да | `lohen_impressed__myvoicefordublo_a1.mp3` |
| lohen_security | `myvoicefordublo` | 2.400 | 3.60 | да | `lohen_security__myvoicefordublo_a1.mp3` |
| prisoner_refuse | `myvoicefordublo` | 2.560 | 2.60 | да | `prisoner_refuse__myvoicefordublo_a1.mp3` |
| lohen_tongue | `myvoicefordublo` | 1.760 | 2.30 | да | `lohen_tongue__myvoicefordublo_a1.mp3` |
| lohen_game | `myvoicefordublo` | 1.520 | 2.20 | да | `lohen_game__myvoicefordublo_a1.mp3` |
| lohen_chambers | `myvoicefordublo` | 3.840 | 2.90 | нет | `lohen_chambers__myvoicefordublo_a1.mp3` |
| lohen_count | `myvoicefordublo` | 2.080 | 3.50 | да | `lohen_count__myvoicefordublo_a1.mp3` |
| guard_shout | `myvoicefordublo` | 2.160 | 1.60 | нет | `guard_shout__myvoicefordublo_a1.mp3` |
| lohen_finally | `myvoicefordublo` | 1.680 | 5.10 | да | `lohen_finally__myvoicefordublo_a1.mp3` |
| lohen_feel | `myvoicefordublo` | 1.920 | 5.20 | да | `lohen_feel__myvoicefordublo_a1.mp3` |
| lohen_thatall | `myvoicefordublo` | 1.680 | 5.20 | да | `lohen_thatall__myvoicefordublo_a1.mp3` |
| lohen_really | `myvoicefordublo` | 1.680 | 2.00 | да | `lohen_really__myvoicefordublo_a1.mp3` |
| lohen_final | `myvoicefordublo` | 4.880 | 9.40 | да | `lohen_final__myvoicefordublo_a1.mp3` |
| lohen_chambers | `myvoicefordublo` | 2.480 | 2.90 | да | `lohen_chambers__myvoicefordublo_a2.mp3` |
| guard_shout | `myvoicefordublo` | 1.760 | 1.60 | нет | `guard_shout__myvoicefordublo_a2.mp3` |
| guard_shout | `myvoicefordublo` | 1.440 | 1.60 | да | `guard_shout__myvoicefordublo_a3.mp3` |
| lohen_impressed | `lo_v41` | 2.080 | 2.70 | да | `lohen_impressed__lo_v41_a1.mp3` |
| lohen_security | `lo_v41` | 2.880 | 3.60 | да | `lohen_security__lo_v41_a1.mp3` |
| prisoner_refuse | `lo_v41` | 2.640 | 2.60 | нет | `prisoner_refuse__lo_v41_a1.mp3` |
| lohen_tongue | `lo_v41` | 1.840 | 2.30 | да | `lohen_tongue__lo_v41_a1.mp3` |
| lohen_game | `lo_v41` | 1.760 | 2.20 | да | `lohen_game__lo_v41_a1.mp3` |
| lohen_chambers | `lo_v41` | 2.800 | 2.90 | да | `lohen_chambers__lo_v41_a1.mp3` |
| lohen_count | `lo_v41` | 2.000 | 3.50 | да | `lohen_count__lo_v41_a1.mp3` |
| guard_shout | `lo_v41` | 1.360 | 1.60 | да | `guard_shout__lo_v41_a1.mp3` |
| lohen_finally | `lo_v41` | 1.440 | 5.10 | да | `lohen_finally__lo_v41_a1.mp3` |
| lohen_feel | `lo_v41` | 2.080 | 5.20 | да | `lohen_feel__lo_v41_a1.mp3` |
| lohen_thatall | `lo_v41` | 1.840 | 5.20 | да | `lohen_thatall__lo_v41_a1.mp3` |
| lohen_really | `lo_v41` | 1.360 | 2.00 | да | `lohen_really__lo_v41_a1.mp3` |
| lohen_final | `lo_v41` | 5.440 | 9.40 | да | `lohen_final__lo_v41_a1.mp3` |
| prisoner_refuse | `lo_v41` | 2.560 | 2.60 | да | `prisoner_refuse__lo_v41_a2.mp3` |
| lohen_impressed | `mysts<-lo_v2` | 4.876 | 2.70 | нет | `lohen_impressed__mysts_a1.mp3` |
| lohen_security | `mysts<-lo_v2` | 3.344 | 3.60 | да | `lohen_security__mysts_a1.mp3` |
| prisoner_refuse | `mysts<-lo_v2` | 3.390 | 2.60 | нет | `prisoner_refuse__mysts_a1.mp3` |
| lohen_tongue | `lo_v2` | 1.760 | 2.30 | да | `lohen_tongue__lo_v2_a1.mp3` |
| lohen_game | `lo_v2` | 1.360 | 2.20 | да | `lohen_game__lo_v2_a1.mp3` |
| lohen_chambers | `lo_v2` | 2.800 | 2.90 | да | `lohen_chambers__lo_v2_a1.mp3` |
| lohen_count | `lo_v2` | 3.360 | 3.50 | да | `lohen_count__lo_v2_a1.mp3` |
| guard_shout | `lo_v2` | 0.960 | 1.60 | да | `guard_shout__lo_v2_a1.mp3` |
| lohen_finally | `lo_v2` | 1.760 | 5.10 | да | `lohen_finally__lo_v2_a1.mp3` |
| lohen_feel | `lo_v2` | 2.160 | 5.20 | да | `lohen_feel__lo_v2_a1.mp3` |
| lohen_thatall | `lo_v2` | 1.600 | 5.20 | да | `lohen_thatall__lo_v2_a1.mp3` |
| lohen_really | `lo_v2` | 1.920 | 2.00 | да | `lohen_really__lo_v2_a1.mp3` |
| lohen_final | `lo_v2` | 4.320 | 9.40 | да | `lohen_final__lo_v2_a1.mp3` |
| lohen_impressed | `lo_v2` | 2.560 | 2.70 | да | `lohen_impressed__lo_v2_a1.mp3` |
| lohen_security | `lo_v2` | 2.320 | 3.60 | да | `lohen_security__lo_v2_a1.mp3` |
| prisoner_refuse | `lo_v2` | 2.400 | 2.60 | да | `prisoner_refuse__lo_v2_a1.mp3` |
| lohen_really | `lo_v2` | 2.000 | 1.20 | нет | `lohen_really__lo_v2_a2.mp3` |
| lohen_really | `lo_v2` | 0.640 | 1.20 | да | `lohen_really__lo_v2_a3.mp3` |
| lohen_impressed | `mysts<-lo_v2` | 2.601 | 2.70 | да | `lohen_impressed__mysts_a2.mp3` |
| lohen_impressed | `mystsalt<-lo_v2` | 2.508 | 2.70 | да | `lohen_impressed__mystsalt_a1.mp3` |
| lohen_impressed | `mysts<-lo_v2` | 2.508 | 2.70 | да | `lohen_impressed__mysts_a3.mp3` |
| lohen_security | `mysts<-lo_v2` | 3.344 | 3.60 | да | `lohen_security__mysts_a2.mp3` |
| prisoner_refuse | `mysts<-lo_v2` | 2.229 | 2.60 | да | `prisoner_refuse__mysts_a2.mp3` |
| lohen_tongue | `mysts<-lo_v2` | 2.183 | 2.30 | да | `lohen_tongue__mysts_a1.mp3` |
| lohen_game | `mysts<-lo_v2` | 1.811 | 2.20 | да | `lohen_game__mysts_a1.mp3` |
| lohen_chambers | `mysts<-lo_v2` | 2.183 | 2.90 | да | `lohen_chambers__mysts_a1.mp3` |
| lohen_count | `mysts<-lo_v2` | 1.858 | 3.50 | да | `lohen_count__mysts_a1.mp3` |
| guard_shout | `mysts<-lo_v2` | 0.975 | 1.60 | да | `guard_shout__mysts_a1.mp3` |
| lohen_finally | `mysts<-lo_v2` | 1.393 | 5.10 | да | `lohen_finally__mysts_a1.mp3` |
| lohen_impressed | `mysts41<-lo_v41` | 2.508 | 2.70 | да | `lohen_impressed__mysts41_a1.mp3` |
| lohen_security | `mysts41<-lo_v41` | 3.344 | 3.60 | да | `lohen_security__mysts41_a1.mp3` |
| prisoner_refuse | `mysts41<-lo_v41` | 2.229 | 2.60 | да | `prisoner_refuse__mysts41_a1.mp3` |
| lohen_tongue | `mysts41<-lo_v41` | 2.183 | 2.30 | да | `lohen_tongue__mysts41_a1.mp3` |
| lohen_game | `mysts41<-lo_v41` | 1.811 | 2.20 | да | `lohen_game__mysts41_a1.mp3` |
| lohen_chambers | `mysts41<-lo_v41` | 2.183 | 2.90 | да | `lohen_chambers__mysts41_a1.mp3` |
| lohen_count | `mysts41<-lo_v41` | 1.858 | 3.50 | да | `lohen_count__mysts41_a1.mp3` |
| guard_shout | `mysts41<-lo_v41` | 0.975 | 1.60 | да | `guard_shout__mysts41_a1.mp3` |
| lohen_finally | `mysts41<-lo_v41` | 1.393 | 5.10 | да | `lohen_finally__mysts41_a1.mp3` |
| lohen_impressed | `mysts43<-lo_v43` | 2.508 | 2.70 | да | `lohen_impressed__mysts43_a1.mp3` |
| lohen_security | `mysts43<-lo_v43` | 3.344 | 3.60 | да | `lohen_security__mysts43_a1.mp3` |
| prisoner_refuse | `mysts43<-lo_v43` | 2.229 | 2.60 | да | `prisoner_refuse__mysts43_a1.mp3` |
| lohen_tongue | `mysts43<-lo_v43` | 2.183 | 2.30 | да | `lohen_tongue__mysts43_a1.mp3` |
| lohen_game | `mysts43<-lo_v43` | 1.811 | 2.20 | да | `lohen_game__mysts43_a1.mp3` |
| lohen_chambers | `mysts43<-lo_v43` | 2.183 | 2.90 | да | `lohen_chambers__mysts43_a1.mp3` |
| lohen_count | `mysts43<-lo_v43` | 1.858 | 3.50 | да | `lohen_count__mysts43_a1.mp3` |
| guard_shout | `mysts43<-lo_v43` | 0.975 | 1.60 | да | `guard_shout__mysts43_a1.mp3` |
| lohen_finally | `mysts43<-lo_v43` | 1.393 | 5.10 | да | `lohen_finally__mysts43_a1.mp3` |
| lohen_feel | `lo_v43` | 2.000 | 5.20 | да | `lohen_feel__lo_v43_a1.mp3` |
| lohen_thatall | `lo_v43` | 1.520 | 5.20 | да | `lohen_thatall__lo_v43_a1.mp3` |
| lohen_really | `lo_v43` | 0.960 | 1.20 | да | `lohen_really__lo_v43_a1.mp3` |
| lohen_final | `lo_v43` | 3.680 | 9.40 | да | `lohen_final__lo_v43_a1.mp3` |
| lohen_security | `zYcjlYFO` | 3.600 | 3.60 | да | `lohen_security__zYcjlYFO_a1.mp3` |
| lohen_impressed | `mystsed<-edward` | 2.508 | 2.70 | да | `lohen_impressed__mystsed_a1.mp3` |
| lohen_security | `mystsed<-edward` | 3.344 | 3.60 | да | `lohen_security__mystsed_a1.mp3` |
| prisoner_refuse | `mystsed<-edward` | 2.229 | 2.60 | да | `prisoner_refuse__mystsed_a1.mp3` |
| lohen_tongue | `mystsed<-edward` | 2.183 | 2.30 | да | `lohen_tongue__mystsed_a1.mp3` |
| lohen_game | `mystsed<-edward` | 1.811 | 2.20 | да | `lohen_game__mystsed_a1.mp3` |
| lohen_chambers | `mystsed<-edward` | 2.183 | 2.90 | да | `lohen_chambers__mystsed_a1.mp3` |
| lohen_count | `mystsed<-edward` | 1.858 | 3.50 | да | `lohen_count__mystsed_a1.mp3` |
| guard_shout | `mystsed<-edward` | 0.975 | 1.60 | да | `guard_shout__mystsed_a1.mp3` |
| lohen_finally | `mystsed<-edward` | 1.393 | 5.10 | да | `lohen_finally__mystsed_a1.mp3` |
| lohen_feel | `edward` | 2.880 | 5.20 | да | `lohen_feel__edward_a1.mp3` |
| lohen_thatall | `edward` | 2.080 | 5.20 | да | `lohen_thatall__edward_a1.mp3` |
| lohen_really | `edward` | 1.040 | 1.20 | да | `lohen_really__edward_a1.mp3` |
| lohen_final | `edward` | 5.680 | 9.40 | да | `lohen_final__edward_a1.mp3` |
| lohen_impressed | `edward` | 2.960 | 2.70 | нет | `lohen_impressed__edward_a1.mp3` |
| prisoner_refuse | `edward` | 3.360 | 2.60 | нет | `prisoner_refuse__edward_a1.mp3` |
| lohen_tongue | `edward` | 2.880 | 2.30 | нет | `lohen_tongue__edward_a1.mp3` |
| lohen_game | `edward` | 2.240 | 2.20 | нет | `lohen_game__edward_a1.mp3` |
| lohen_chambers | `edward` | 3.200 | 2.90 | нет | `lohen_chambers__edward_a1.mp3` |
| lohen_count | `edward` | 2.400 | 3.50 | да | `lohen_count__edward_a1.mp3` |
| guard_shout | `edward` | 1.440 | 1.60 | да | `guard_shout__edward_a1.mp3` |
| lohen_finally | `edward` | 1.680 | 5.10 | да | `lohen_finally__edward_a1.mp3` |
| lohen_feel | `mysts<-lo_v2` | 1.579 | 5.20 | да | `lohen_feel__mysts_a1.mp3` |
| lohen_feel | `mysts41<-lo_v41` | 1.579 | 5.20 | да | `lohen_feel__mysts41_a1.mp3` |
| lohen_feel | `mysts43<-lo_v43` | 1.579 | 5.20 | да | `lohen_feel__mysts43_a1.mp3` |
| lohen_feel | `mystsed<-edward` | 1.579 | 5.20 | да | `lohen_feel__mystsed_a1.mp3` |
| lohen_thatall | `mysts<-lo_v2` | 2.786 | 5.20 | да | `lohen_thatall__mysts_a1.mp3` |
| lohen_really | `mysts<-lo_v2` | 1.068 | 1.20 | да | `lohen_really__mysts_a1.mp3` |
| lohen_final | `mysts<-lo_v2` | 4.830 | 9.40 | да | `lohen_final__mysts_a1.mp3` |
| lohen_thatall | `mysts41<-lo_v41` | 2.786 | 5.20 | да | `lohen_thatall__mysts41_a1.mp3` |
| lohen_really | `mysts41<-lo_v41` | 1.068 | 1.20 | да | `lohen_really__mysts41_a1.mp3` |
| lohen_final | `mysts41<-lo_v41` | 4.830 | 9.40 | да | `lohen_final__mysts41_a1.mp3` |
| lohen_thatall | `mysts43<-lo_v43` | 2.786 | 5.20 | да | `lohen_thatall__mysts43_a1.mp3` |
| lohen_really | `mysts43<-lo_v43` | 1.068 | 1.20 | да | `lohen_really__mysts43_a1.mp3` |
| lohen_final | `mysts43<-lo_v43` | 4.830 | 9.40 | да | `lohen_final__mysts43_a1.mp3` |
| lohen_thatall | `mystsed<-edward` | 2.786 | 5.20 | да | `lohen_thatall__mystsed_a1.mp3` |
| lohen_really | `mystsed<-edward` | 1.068 | 1.20 | да | `lohen_really__mystsed_a1.mp3` |
| lohen_final | `mystsed<-edward` | 4.830 | 9.40 | да | `lohen_final__mystsed_a1.mp3` |

## Не влезли в своё окно

Эти генерации остались на диске, но в номер поставить их нельзя — реплика заехала бы на следующую.

- `lohen_chambers__myvoicefordublo_a1.mp3` — 3.840 с при пределе 2.90: театральная подача, максимум ЧСВ
- `guard_shout__myvoicefordublo_a1.mp3` — 2.160 с при пределе 1.60: театральная подача, максимум ЧСВ
- `guard_shout__myvoicefordublo_a2.mp3` — 1.760 с при пределе 1.60: правка: не влезали
- `prisoner_refuse__lo_v41_a1.mp3` — 2.640 с при пределе 2.60: тот же прогон голосом lo_v41
- `lohen_impressed__mysts_a1.mp3` — 4.876 с при пределе 2.70: из lohen_impressed_all3_take4.wav; выбор из чата: impressed последний, security 4 из 5, prisoner последний
- `prisoner_refuse__mysts_a1.mp3` — 3.390 с при пределе 2.60: из prisoner_refuse_all_take4.wav; выбор из чата: impressed последний, security 4 из 5, prisoner последний
- `lohen_really__lo_v2_a2.mp3` — 2.000 с при пределе 1.20: правка: не влезала в жёсткий предел 1.20 до удара
- `lohen_impressed__edward_a1.mp3` — 2.960 с при пределе 2.70: полный синтез Edward
- `prisoner_refuse__edward_a1.mp3` — 3.360 с при пределе 2.60: полный синтез Edward
- `lohen_tongue__edward_a1.mp3` — 2.880 с при пределе 2.30: полный синтез Edward
- `lohen_game__edward_a1.mp3` — 2.240 с при пределе 2.20: полный синтез Edward
- `lohen_chambers__edward_a1.mp3` — 3.200 с при пределе 2.90: полный синтез Edward
