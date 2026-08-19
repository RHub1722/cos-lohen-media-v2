"""Сколько работы синхронизация подсказок заказывает у медиаэлемента.

Тест, которого не хватало. Тренажёр подтормаживал НА ПЛАНШЕТЕ и только там, а
воспроизвести это на компьютере нельзя: там автозапуск разрешён, перемотка
дешёвая, и ветка, в которой всё вставало, просто не исполняется.

Значит проверять надо не «тормозит ли», а СКОЛЬКО ОПЕРАЦИЙ код заказывает.
Это число от устройства не зависит и считается точно. Стенд берёт живую
функцию из `src/training_template.html` — не копию, копия разошлась бы молча.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "tools/sync_budget.js"

# Пределы на десять секунд игры при шестидесяти кадрах в секунду. Взяты не с
# потолка: старая версия в заблокированном автозапуске делала 600 вызовов play
# и 39 перемоток, и это съедало 23% главного потока на модели слабого планшета.
MAX_PLAY = 20         # ~2 попытки в секунду: откат 800 мс плюс запас
MAX_SEEK = 4          # правка не чаще раза в секунду, и только здоровой дорожке
MAX_SHARE = 0.02      # доля главного потока на слабом устройстве


@pytest.fixture(scope="module")
def budget():
    if shutil.which("node") is None:
        pytest.skip("нет node — стенд синхронизации не запустить")
    done = subprocess.run(["node", str(BENCH), "--json"],
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr[-800:]
    return {row["key"]: row for row in json.loads(done.stdout)}


def test_a_blocked_autoplay_does_not_turn_into_a_storm(budget):
    """Главная причина подтормаживания на планшете.

    Планшет разрешает автозапуск только изнутри касания. Отказ оставлял
    элемент на паузе, а покадровая синхронизация звала play заново на КАЖДОМ
    кадре — шестьдесят отказов в секунду, каждый с обещанием. На компьютере
    автозапуск разрешён, поэтому этой ветки там нет вовсе.
    """
    row = budget["blocked"]
    assert row["old"]["ops"]["play"] > 500, "стенд перестал воспроизводить беду"
    assert row["now"]["ops"]["play"] <= MAX_PLAY, row["now"]["ops"]
    assert row["now"]["ops"]["seek"] <= MAX_SEEK, row["now"]["ops"]
    assert row["now"]["share"] <= MAX_SHARE, row["now"]["share"]


def test_a_starving_stream_is_not_seeked_into_the_ground(budget):
    """Перемотать дорожку, которой не хватает данных, значит заставить её
    буферизоваться заново — и так по кругу. Старая версия правила голодающий
    поток четыре раза в секунду."""
    row = budget["starving"]
    assert row["old"]["ops"]["seek"] > 30, "стенд перестал воспроизводить беду"
    assert row["now"]["ops"]["seek"] == 0, row["now"]["ops"]


def test_a_healthy_track_costs_nothing(budget):
    """Когда всё в порядке, синхронизация обязана молчать: две дорожки на
    одном устройстве идут вместе сами, и трогать их незачем."""
    row = budget["healthy"]
    assert row["now"]["ops"]["seek"] == 0
    assert row["now"]["ops"]["play"] == 0
