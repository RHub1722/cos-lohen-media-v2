// Сколько операций над медиаэлементом делает синхронизация подсказок.
//
//     node tools/sync_budget.js
//     node tools/sync_budget.js --json
//
// Зачем. Тренажёр подтормаживал НА ПЛАНШЕТЕ и только там. Воспроизвести это на
// компьютере нельзя: там автозапуск разрешён, перемотка дешёвая, и ветка, в
// которой всё вставало, просто не исполняется. Значит проверять надо не «тормозит
// ли», а СКОЛЬКО РАБОТЫ код заказывает у медиаэлемента. Это число от устройства
// не зависит, считается точно и ловит беду до того, как она доедет до планшета.
//
// Берётся ЖИВАЯ функция из src/training_template.html, а не её копия: копия
// разошлась бы с оригиналом молча, и тест сторожил бы вчерашний код.
//
// Стоимости операций — модель слабого планшета, и на счёт операций они не
// влияют. От них зависит только последняя колонка: какую долю кадрового
// бюджета эта работа съедает.

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const TEMPLATE = path.join(ROOT, "src", "training_template.html");

// Модель слабого планшета. Перемотка сжатого потока там на два порядка дороже
// отказа автозапуска, поэтому одна лишняя перемотка стоит как двадцать
// лишних play.
const COST_SEEK_MS = 35;
const COST_PLAY_MS = 1.5;
const FRAME_MS = 1000 / 60;

function grab(html, name, until) {
  const from = html.indexOf("function " + name + "(");
  if (from < 0) throw new Error("в шаблоне нет функции " + name);
  const to = html.indexOf(until, from);
  if (to < 0) throw new Error("не нашёл конец функции " + name);
  return html.slice(from, to);
}

function constants(html) {
  const out = {};
  for (const key of ["COUNT_DRIFT", "COUNT_FIX_EVERY", "COUNT_PLAY_EVERY"]) {
    const m = html.match(new RegExp("const\\s+" + key + "\\s*=\\s*([0-9.]+)"));
    if (!m) throw new Error("в шаблоне нет константы " + key);
    out[key] = Number(m[1]);
  }
  return out;
}

class FakeAudio {
  constructor(cfg) {
    this.cfg = cfg;
    this._t = 0;
    this.paused = true;
    this.seeking = false;
    this.readyState = cfg.readyState;
    this.playbackRate = 1;
    this.ops = { play: 0, seek: 0 };
  }
  get currentTime() { return this._t; }
  set currentTime(v) { this.ops.seek++; this._t = v; }
  play() {
    this.ops.play++;
    if (this.cfg.autoplayBlocked) {
      return Promise.reject(Object.assign(new Error("blocked"),
                                          { name: "NotAllowedError" }));
    }
    this.paused = false;
    return Promise.resolve();
  }
  pause() { this.paused = true; }
  tick(dt) { if (!this.paused) this._t += dt * this.cfg.audioRate; }
}

// Окружение, в котором живёт вырезанная функция. Всё, к чему она обращается,
// подставляется заглушками; чего не хватит — тест упадёт с внятным именем.
function build(html, version) {
  const c = constants(html);
  const audio = { a: null };
  const video = { currentTime: 0, paused: false, playbackRate: 1 };
  const diag = { playTries: 0, playFails: 0, playHeld: 0, lastPlayErr: "",
                 fixes: 0, fixHeld: 0, lastDrift: 0, maxDrift: 0 };
  const env = {
    countKey: "x",
    countPlayers: { get: () => audio.a },
    video,
    diag,
    performance: { now: () => env.clock },
    clock: 0,
    countFixedAt: 0,
    countPlayTriedAt: 0,
    tryPlay(a) {
      diag.playTries++;
      const p = a.play();
      if (p && p.catch) p.catch((err) => { diag.playFails++;
                                           diag.lastPlayErr = err.name; });
    },
    ...c
  };

  const body = version === "new"
    ? grab(html, "syncCount", "\nfunction setCount(")
    : OLD_SOURCE;

  // Функция собирается в изолированной области: она видит только то, что мы
  // положили в env, и ничего из настоящей страницы.
  const names = Object.keys(env);
  const make = new Function(...names,
    body + "\nreturn { syncCount, set clock(v) { performance.now = () => v; } };");
  const made = make(...names.map((n) => env[n]));
  return { env, audio, video, diag, sync: made.syncCount, cons: c };
}

// Старая версия — как она стояла до правки. Хранится здесь, а не в истории
// гита, чтобы сравнение можно было повторить одной командой.
const OLD_SOURCE = `
function syncCount() {
  const a = countPlayers.get(countKey);
  if (!a) return;
  if (a.readyState < 2 || a.seeking) return;
  if (a.playbackRate !== video.playbackRate) a.playbackRate = video.playbackRate;
  if (video.paused) { if (!a.paused) a.pause(); return; }
  if (a.paused) a.play().catch(() => {});
  const now = performance.now();
  if (now - countFixedAt < 250) return;
  if (Math.abs(a.currentTime - video.currentTime) > 0.15) {
    a.currentTime = video.currentTime;
    countFixedAt = now;
  }
}`;

const SCENES = [
  { key: "blocked", name: "автозапуск заблокирован (планшет: звук на паузе)",
    cfg: { readyState: 4, autoplayBlocked: true, audioRate: 1 } },
  { key: "starving", name: "поток голодает: на сейчас данные есть, на дальше нет",
    cfg: { readyState: 2, autoplayBlocked: false, audioRate: 0.4 } },
  { key: "healthy", name: "всё здорово: играет, расхождение не растёт",
    cfg: { readyState: 4, autoplayBlocked: false, audioRate: 1 } },
];

function run(html, version, cfg, seconds) {
  const ctx = build(html, version);
  const a = new FakeAudio(cfg);
  ctx.audio.a = a;

  // Нажатие кнопки. Без него прогон начинался бы с паузы, и «здоровый»
  // случай выглядел бы хуже, чем он есть: новая версия ждала бы отката
  // прежде чем запуститься. На странице это делает setCount.
  ctx.env.countPlayTriedAt = 0;
  ctx.env.tryPlay(a);
  a.currentTime = ctx.video.currentTime;
  a.ops.play = 0;
  a.ops.seek = 0;

  const frames = Math.round(seconds * 60);
  for (let i = 0; i < frames; i++) {
    ctx.env.clock = i * FRAME_MS;
    ctx.video.currentTime = ctx.env.clock / 1000;
    a.tick(FRAME_MS / 1000);
    ctx.sync();
  }
  const ops = ctx.audio.a.ops;
  const cost = ops.play * COST_PLAY_MS + ops.seek * COST_SEEK_MS;
  return { ops, cost, share: cost / (seconds * 1000) };
}

function measure(seconds = 10) {
  const html = fs.readFileSync(TEMPLATE, "utf8");
  return SCENES.map((s) => ({
    key: s.key, name: s.name,
    old: run(html, "old", s.cfg, seconds),
    now: run(html, "new", s.cfg, seconds),
    seconds
  }));
}

if (require.main === module) {
  const rows = measure(10);
  if (process.argv.includes("--json")) {
    process.stdout.write(JSON.stringify(rows, null, 2));
  } else {
    console.log("Работа синхронизации за 10 секунд игры, 60 кадров в секунду.");
    console.log("Модель слабого планшета: перемотка " + COST_SEEK_MS
                + " мс, отказ play " + COST_PLAY_MS + " мс.\n");
    for (const r of rows) {
      console.log(r.name);
      for (const [label, v] of [["СТАРАЯ", r.old], ["НОВАЯ", r.now]]) {
        console.log("  " + label.padEnd(7)
          + " play " + String(v.ops.play).padStart(4)
          + "   перемоток " + String(v.ops.seek).padStart(3)
          + "   → " + (v.cost / 1000).toFixed(2).padStart(6) + " с работы, "
          + (v.share * 100).toFixed(0).padStart(3) + "% главного потока");
      }
      console.log("");
    }
  }
}

module.exports = { measure, SCENES, COST_SEEK_MS, COST_PLAY_MS };
