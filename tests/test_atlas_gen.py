"""Генератор кадров: раскладка попыток, слоты и журнал.

К живому API тесты не обращаются: генерация стоит денег, а ключа у тестов нет.
Подменяются requests.post, requests.get и вызов ffmpeg — этого достаточно, чтобы
проверить всё, что делает инструмент с файлами и журналом.
"""

import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.footage import BaseShot
from tools import atlas_gen as atlas

# Ключ подставляется настоящей формы и проверяется на утечку: он не должен
# оказаться ни в журнале, ни в выводе, ни в тексте ошибки.
KEY = "sk-atlas-tests-must-never-print-this"


# --- подменённый сервис -------------------------------------------------------


class Reply:
    """Ответ requests в объёме, который читает atlas_gen."""

    def __init__(self, payload=None, status=200, body=b""):
        self.status_code = status
        self.text = str(payload)
        self._payload = payload or {}
        self._body = body

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=0):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Service:
    """Atlas, которого нет: отдаёт заготовленные ответы и считает вызовы."""

    def __init__(self):
        self.uploads, self.jobs, self.polled = [], [], []
        self.prediction = "pred-0001"
        self.status = "completed"
        self.tokens = 70726
        self.content = b"attempt-1"
        self.download_status = 200

    def post(self, url, **kwargs):
        if url.endswith("/uploadMedia"):
            self.uploads.append(url)
            return Reply({"code": 200, "data": {"type": "image",
                                                "download_url": "https://ref/1.png"}})
        self.jobs.append(kwargs.get("json"))
        return Reply({"code": 200, "data": {"id": self.prediction,
                                            "status": "processing"}})

    def get(self, url, **kwargs):
        if "/prediction/" in url:
            self.polled.append(url.rsplit("/", 1)[-1])
            return Reply({"code": 200, "data": {
                "status": self.status,
                "outputs": ["https://atlas/out.mp4"],
                "total_tokens": self.tokens,
            }})
        return Reply(status=self.download_status, body=self.content)


def fake_ffmpeg(cmd, **kwargs):
    """Подмена `ffmpeg -an`: переносит байты из raw в цель, как настоящий."""
    source = Path(cmd[cmd.index("-i") + 1])
    shutil.copyfile(source, Path(cmd[-1]))
    return subprocess.CompletedProcess(cmd, 0)


@pytest.fixture
def service(monkeypatch):
    fake = Service()
    monkeypatch.setattr(atlas.requests, "post", fake.post)
    monkeypatch.setattr(atlas.requests, "get", fake.get)
    monkeypatch.setattr(atlas.subprocess, "run", fake_ffmpeg)
    return fake


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Весь проект в tmp: журнал, попытки и слоты."""
    monkeypatch.setattr(atlas, "ROOT", tmp_path)
    monkeypatch.setattr(atlas, "VIDEO", tmp_path / "assets" / "video")
    monkeypatch.setattr(atlas, "ATTEMPTS", tmp_path / "assets" / "video" / "attempts")
    monkeypatch.setattr(atlas, "LEDGER", tmp_path / "docs" / "atlas-ledger.csv")
    monkeypatch.setenv("ATLASCLOUD_API_KEY", KEY)
    return tmp_path


@pytest.fixture
def shot(project):
    """Кадр под генерацию. Якорь и слот — настоящие, из scenario/shots.json."""
    ref = project / "assets" / "screenshots" / "room.png"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"png")
    return BaseShot(anchor="combat", clip="base/03_breach.mp4", duration=7.0,
                    resolution="480p", prompt="a dark hold @image1",
                    negative="readable text", refs=("room.png",))


def rows(project):
    with open(project / "docs" / "atlas-ledger.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --- сколько это стоит -------------------------------------------------------
# Прежняя таблица цен говорила, что 720p дороже 480p на девять процентов, а по
# живым ответам он дороже в 2.16 раза. Сорок три теста прошли мимо этого, потому
# что стоимость не проверял ни один: она печатается перед тратой и на поведение
# не влияет. Ошибка была вдвое и вниз — то есть в сторону, в которую бюджет
# кончается раньше, чем ожидаешь.


def cost(duration: float, resolution: str) -> float:
    shot = BaseShot(anchor="combat", clip="c.mp4", duration=duration,
                    resolution=resolution)
    return atlas.estimate(shot, resolution)


def test_seven_seconds_of_720p_cost_as_much_as_fifteen_of_480p():
    """Замер, который проще всего запомнить и труднее всего сломать незаметно:
    152100 токенов против 151078."""
    assert cost(7, "720p") == pytest.approx(cost(15, "480p"), rel=0.03)


def test_720p_costs_twice_480p_per_second_not_a_tenth_more():
    assert cost(10, "720p") / cost(10, "480p") == pytest.approx(2.16, rel=0.02)


def test_an_unmeasured_resolution_does_not_pretend_to_be_free():
    """Ноль выглядел бы как «бесплатно» и потерялся бы в сумме, ничего не
    изменив. nan виден и в строке кадра, и в итоге."""
    import math
    assert math.isnan(cost(5, "1080p-SR"))
    assert math.isnan(cost(5, "нет такого"))


def test_the_four_pilot_generations_still_come_out_at_the_known_price():
    """443608 токенов на $2.46 — единственная привязка к деньгам, что у нас есть.
    Если цена токена уедет, эти четыре кадра перестанут сходиться."""
    pilot = cost(15, "480p") * 2 + cost(7, "480p") * 2
    assert pilot == pytest.approx(2.46, abs=0.05)


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["atlas_gen.py", "--shots",
                                      "scenario/shots.json", *argv])
    return atlas.main()


def attempt(project, name):
    return project / "assets" / "video" / "attempts" / name


def slot(project, clip):
    return project / "assets" / "video" / clip


# --- попытка не затирает попытку ---------------------------------------------


def test_generation_saves_the_attempt_next_to_the_others(project, service, shot):
    atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    assert attempt(project, "combat_a1.mp4").read_bytes() == b"attempt-1"


def test_every_attempt_survives_the_next_one(project, service, shot):
    """То, из-за чего всё и переделано: раньше вторая генерация ложилась в тот же
    файл, и первая версия исчезала — доставать её пришлось руками через API."""
    atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    service.content = b"attempt-2"
    atlas.generate(shot, "480p", "2026-08-03T20:10:00")

    assert attempt(project, "combat_a1.mp4").read_bytes() == b"attempt-1"
    assert attempt(project, "combat_a2.mp4").read_bytes() == b"attempt-2"


def test_the_slot_gets_the_fresh_attempt(project, service, shot):
    atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    assert slot(project, shot.clip).read_bytes() == b"attempt-1"


def test_the_slot_is_a_copy_and_the_attempt_stays_in_place(project, service, shot):
    """Переносом файла слот наполнять нельзя: попытки не стало бы, а весь смысл
    раскладки в том, что она остаётся."""
    atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    assert attempt(project, "combat_a1.mp4").exists()
    assert slot(project, shot.clip).exists()


def test_download_refuses_to_overwrite_an_attempt(project, service):
    """Последний барьер: даже если номер попытки посчитается неверно, байты уже
    скачанной попытки перезаписаны не будут."""
    target = attempt(project, "combat_a1.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"already-downloaded")
    with pytest.raises(atlas.AtlasError, match="уже скачана"):
        atlas.download("https://atlas/out.mp4", target)
    assert target.read_bytes() == b"already-downloaded"


# --- номер попытки -----------------------------------------------------------


def test_the_attempt_number_continues_from_the_ledger(project, service, shot):
    atlas.note({"shot": "combat", "attempt": 1, "status": "ok"})
    atlas.note({"shot": "combat", "attempt": 2, "status": "failed"})
    assert atlas.attempt_number("combat") == 3


def test_the_attempt_number_counts_files_when_the_ledger_is_gone(project):
    """Журнал можно удалить или переписать, а файлы останутся. Считать номер
    только по журналу — значит отправить новую генерацию в файл первой попытки."""
    attempt(project, "combat_a1.mp4").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "combat_a1.mp4").write_bytes(b"x")
    attempt(project, "combat_a2.mp4").write_bytes(b"x")
    assert atlas.attempt_number("combat") == 3


def test_the_attempt_number_takes_the_larger_of_the_two_counts(project):
    atlas.note({"shot": "combat", "attempt": 1, "status": "ok"})
    attempt(project, "combat_a4.mp4").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "combat_a4.mp4").write_bytes(b"x")
    assert atlas.attempt_number("combat") == 5


def test_attempts_are_counted_per_anchor(project):
    attempt(project, "combat_a1.mp4").parent.mkdir(parents=True, exist_ok=True)
    for name in ("combat_a1.mp4", "combat_a2.mp4", "ice_a1.mp4"):
        attempt(project, name).write_bytes(b"x")
    assert atlas.attempts("combat") == [1, 2]
    assert atlas.attempts("ice") == [1]
    assert atlas.attempts("interrogation") == []


def test_an_anchor_ending_in_a_is_not_confused_with_its_attempt_number(project):
    """burst3_impact_a — настоящий якорь номера. Отрезать номер поиском «_a»
    в имени файла нельзя: у этого кадра «_a» встречается дважды."""
    attempt(project, "x").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "burst3_impact_a_a2.mp4").write_bytes(b"x")
    assert atlas.attempts("burst3_impact_a") == [2]
    assert atlas.attempts("burst3_impact") == []


def test_a_half_downloaded_attempt_does_not_count_as_one(project):
    """Файл .raw.mp4 остаётся после сорвавшегося обеззвучивания. Это не попытка,
    и занимать её номер он не должен."""
    attempt(project, "x").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "combat_a1.raw.mp4").write_bytes(b"x")
    assert atlas.attempts("combat") == []


# --- журнал ------------------------------------------------------------------


def test_the_ledger_has_a_column_for_the_prediction_id():
    assert "prediction_id" in atlas.LEDGER_HEADER


def test_the_real_ledger_is_of_the_current_format():
    """Журнал в репозитории и заголовок в коде расходиться не должны: строка
    нового формата в журнале старого молча разъехалась бы по столбцам."""
    with open("docs/atlas-ledger.csv", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == atlas.LEDGER_HEADER


def test_generation_writes_the_prediction_id(project, service, shot):
    service.prediction = "pred-abc123"
    atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    line = rows(project)[0]
    assert line["prediction_id"] == "pred-abc123"
    assert line["status"] == "ok"
    assert line["total_tokens"] == str(service.tokens)
    assert line["file"] == shot.clip


def test_a_broken_download_still_writes_the_prediction_id(project, service, shot):
    """Ровно то, что случилось: генерация оплачена и готова, а файла нет. Без
    идентификатора в журнале результат достаётся только со скриншота дашборда."""
    service.download_status = 500
    service.prediction = "pred-lost"
    with pytest.raises(atlas.AtlasError):
        atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    line = rows(project)[0]
    assert line["status"] == "failed"
    assert line["prediction_id"] == "pred-lost"


def test_a_ledger_of_the_old_format_is_not_appended_to(project, service, shot):
    """Дописать колонку в старый журнал молча — значит сдвинуть все столбцы и
    первым потерять как раз prediction_id."""
    old = project / "docs" / "atlas-ledger.csv"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("timestamp,shot,status,file\n2026-08-03,combat,ok,x.mp4\n",
                   encoding="utf-8")
    with pytest.raises(atlas.AtlasError, match="формата"):
        atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    # Ни строки не дописано, и генерация не отправлена: падает до отправки.
    assert "pred" not in old.read_text(encoding="utf-8")
    assert service.jobs == []


def test_the_key_never_reaches_the_ledger_nor_the_output(project, service, shot,
                                                        capsys):
    service.download_status = 403
    with pytest.raises(atlas.AtlasError):
        atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    printed = capsys.readouterr()
    ledger = (project / "docs" / "atlas-ledger.csv").read_text(encoding="utf-8")
    assert KEY not in ledger
    assert KEY not in printed.out + printed.err


# --- --use: слот переключается без генерации ---------------------------------


def test_use_puts_an_older_attempt_into_the_slot(project, monkeypatch):
    """Ключа тут не нужно вовсе: ничего не отправляется и не оплачивается."""
    monkeypatch.delenv("ATLASCLOUD_API_KEY", raising=False)
    attempt(project, "x").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "combat_a1.mp4").write_bytes(b"attempt-1")
    attempt(project, "combat_a2.mp4").write_bytes(b"attempt-2")
    slot(project, "base/03_breach.mp4").parent.mkdir(parents=True, exist_ok=True)
    slot(project, "base/03_breach.mp4").write_bytes(b"attempt-2")

    assert run(monkeypatch, "--use", "combat=1") == 0
    assert slot(project, "base/03_breach.mp4").read_bytes() == b"attempt-1"
    # Попытка остаётся на месте: слот наполняется копией.
    assert attempt(project, "combat_a1.mp4").exists()


def test_use_takes_several_pairs(project, monkeypatch):
    attempt(project, "x").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "combat_a1.mp4").write_bytes(b"breach")
    attempt(project, "ice_a3.mp4").write_bytes(b"ice")

    assert run(monkeypatch, "--use", "combat=1", "ice=3") == 0
    assert slot(project, "base/03_breach.mp4").read_bytes() == b"breach"
    assert slot(project, "base/09_ice.mp4").read_bytes() == b"ice"


def test_use_leaves_the_ledger_alone(project, monkeypatch):
    """Журнал — журнал расходов. Переключение слота ничего не стоит и номера
    попытки не занимает."""
    attempt(project, "x").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "combat_a1.mp4").write_bytes(b"breach")
    run(monkeypatch, "--use", "combat=1")
    assert not (project / "docs" / "atlas-ledger.csv").exists()
    assert atlas.attempt_number("combat") == 2


def test_use_lists_the_attempts_there_are(project, monkeypatch, capsys):
    attempt(project, "x").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "combat_a1.mp4").write_bytes(b"x")
    attempt(project, "combat_a3.mp4").write_bytes(b"x")

    assert run(monkeypatch, "--use", "combat=2") == 1
    error = capsys.readouterr().err
    assert "1, 3" in error


def test_use_says_so_when_there_are_no_attempts_at_all(project, monkeypatch,
                                                       capsys):
    assert run(monkeypatch, "--use", "combat=1") == 1
    assert "нет вовсе" in capsys.readouterr().err


def test_use_does_not_touch_the_slot_when_the_attempt_is_missing(project,
                                                                monkeypatch):
    slot(project, "base/03_breach.mp4").parent.mkdir(parents=True, exist_ok=True)
    slot(project, "base/03_breach.mp4").write_bytes(b"picked-earlier")
    run(monkeypatch, "--use", "combat=9")
    assert slot(project, "base/03_breach.mp4").read_bytes() == b"picked-earlier"


def test_use_rejects_an_unknown_anchor(project, monkeypatch, capsys):
    assert run(monkeypatch, "--use", "no_such_shot=1") == 1
    error = capsys.readouterr().err
    assert "no_such_shot" in error and "combat" in error


def test_use_rejects_a_pair_without_a_number(project, monkeypatch, capsys):
    assert run(monkeypatch, "--use", "combat") == 1
    assert "ЯКОРЬ=НОМЕР" in capsys.readouterr().err


# --- --refetch: результат достаётся по идентификатору ------------------------


def test_refetch_saves_the_result_as_a_new_attempt(project, service, monkeypatch):
    assert run(monkeypatch, "--refetch", "pred-lost", "--as", "combat") == 0
    assert attempt(project, "combat_a1.mp4").read_bytes() == b"attempt-1"
    assert service.polled == ["pred-lost"]


def test_refetch_pays_nothing(project, service, monkeypatch):
    """Результат уже оплачен и живёт на стороне сервиса. Ни одной отправки."""
    run(monkeypatch, "--refetch", "pred-lost", "--as", "combat")
    assert service.jobs == [] and service.uploads == []
    line = rows(project)[0]
    assert line["status"] == "refetch"
    assert line["prediction_id"] == "pred-lost"
    assert float(line["cost_estimate_usd"]) == 0.0


def test_refetch_takes_the_next_free_number(project, service, monkeypatch):
    attempt(project, "x").parent.mkdir(parents=True, exist_ok=True)
    attempt(project, "combat_a1.mp4").write_bytes(b"attempt-1")
    run(monkeypatch, "--refetch", "pred-lost", "--as", "combat")
    assert attempt(project, "combat_a2.mp4").exists()
    assert attempt(project, "combat_a1.mp4").read_bytes() == b"attempt-1"


def test_refetch_leaves_the_slot_alone(project, service, monkeypatch, capsys):
    """Достают старую версию, чтобы сравнить её с отобранной. Подменить слот
    молча было бы той же потерей, только наоборот, — на это есть --use."""
    slot(project, "base/03_breach.mp4").parent.mkdir(parents=True, exist_ok=True)
    slot(project, "base/03_breach.mp4").write_bytes(b"picked-earlier")
    run(monkeypatch, "--refetch", "pred-lost", "--as", "combat")
    assert slot(project, "base/03_breach.mp4").read_bytes() == b"picked-earlier"
    assert "--use combat=1" in capsys.readouterr().out


def test_refetch_reports_a_prediction_that_failed(project, service, monkeypatch,
                                                  capsys):
    service.status = "failed"
    assert run(monkeypatch, "--refetch", "pred-bad", "--as", "combat") == 1
    assert "failed" in capsys.readouterr().err
    assert not attempt(project, "combat_a1.mp4").exists()


def test_refetch_rejects_an_unknown_anchor(project, service, monkeypatch, capsys):
    assert run(monkeypatch, "--refetch", "pred-lost", "--as", "nope") == 1
    assert "nope" in capsys.readouterr().err


def test_refetch_without_an_anchor_is_a_usage_error(project, service, monkeypatch):
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, "--refetch", "pred-lost")
    assert exit_info.value.code == 2


def test_refetch_needs_the_key(project, service, monkeypatch, capsys):
    monkeypatch.delenv("ATLASCLOUD_API_KEY", raising=False)
    assert run(monkeypatch, "--refetch", "pred-lost", "--as", "combat") == 1
    assert "ATLASCLOUD_API_KEY" in capsys.readouterr().err


# --- прежний CLI на месте ----------------------------------------------------


def test_dry_run_works_without_a_key_and_sends_nothing(project, service,
                                                       monkeypatch, capsys):
    monkeypatch.delenv("ATLASCLOUD_API_KEY", raising=False)
    assert run(monkeypatch, "--only", "combat", "--dry-run") == 0
    printed = capsys.readouterr().out
    assert "combat" in printed and "interrogation" not in printed
    assert service.jobs == [] and service.uploads == []


def test_dry_run_of_the_whole_list_shows_every_shot(project, monkeypatch, capsys):
    assert run(monkeypatch, "--all", "--dry-run") == 0
    printed = capsys.readouterr().out
    assert "кадров: 10" in printed
    assert "ice_final_impact" in printed


def test_resolution_still_overrides_the_shot(project, monkeypatch, capsys):
    assert run(monkeypatch, "--only", "combat", "--dry-run",
               "--resolution", "480p") == 0
    assert "480p" in capsys.readouterr().out


def test_only_still_rejects_an_unknown_anchor(project, monkeypatch):
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, "--only", "no_such_shot", "--dry-run")
    assert exit_info.value.code == 2


def test_a_run_without_any_mode_is_a_usage_error(project, monkeypatch):
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch)
    assert exit_info.value.code == 2


@pytest.mark.parametrize("argv", [
    ("--all", "--use", "combat=1"),
    ("--only", "combat", "--refetch", "pred-1", "--as", "combat"),
    ("--use", "combat=1", "--refetch", "pred-1", "--as", "combat"),
])
def test_the_modes_do_not_mix(project, monkeypatch, argv):
    """Молча проигнорировать половину командной строки — худшее, что тут можно
    сделать: пользователь решит, что генерация прошла."""
    with pytest.raises(SystemExit) as exit_info:
        run(monkeypatch, *argv)
    assert exit_info.value.code == 2


def test_generation_sends_what_the_contract_says(project, service, shot):
    """Разрешение и длительность доезжают до запроса, звук и водяной знак
    выключены, пропорции жёсткие — поля из docs/atlas-api.md."""
    atlas.generate(shot, "480p", "2026-08-03T20:00:00")
    body = service.jobs[0]
    assert body["resolution"] == "480p" and body["duration"] == 7
    assert body["ratio"] == "16:9"
    assert body["generate_audio"] is False and body["watermark"] is False
    assert body["reference_images"] == ["https://ref/1.png"]
    assert "readable text" in body["prompt"]


def test_upload_takes_the_link_from_download_url(project, service, tmp_path):
    """В их питоновском примере стоит data["url"], и это неверно."""
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"png")
    assert atlas.upload(ref) == "https://ref/1.png"
