"""Small, self-contained local dashboard HTML.

The page has no remote scripts, styles, fonts, images or network dependencies.
A short-lived bootstrap ticket arrives only in the URL fragment and is exchanged
for an HttpOnly same-origin session cookie by the local runtime.
"""

from __future__ import annotations

import re

_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


def render_dashboard(nonce: str) -> bytes:
    """Render the dashboard with a request-specific CSP nonce."""
    if not isinstance(nonce, str) or _NONCE_PATTERN.fullmatch(nonce) is None:
        raise ValueError("Dashboard nonce has an invalid format.")

    html = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Nika · локальная панель</title>
  <style nonce="__NONCE__">
    :root {
      color-scheme: dark;
      font-family: Inter, "Segoe UI", sans-serif;
      background: #101116;
      color: #f2f1f7;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(ellipse at 15% 0%, #292034 0, transparent 42%),
        #101116;
    }
    main { width: min(980px, calc(100% - 32px)); margin: 0 auto; padding: 42px 0 64px; }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 30px;
    }
    .brand { display: flex; align-items: center; gap: 14px; }
    .orb {
      width: 42px;
      height: 42px;
      border-radius: 14px;
      background: linear-gradient(145deg, #d8b5ff, #8261b9 60%, #3e3154);
      box-shadow: 0 0 30px #9b6bd844;
    }
    h1 { margin: 0; font-size: 27px; letter-spacing: .02em; }
    .sub { color: #a6a0b3; font-size: 12px; letter-spacing: .17em; margin-top: 4px; }
    button {
      border: 1px solid #51445e;
      border-radius: 10px;
      background: #241f2b;
      color: #f6efff;
      padding: 10px 15px;
      font: inherit;
      cursor: pointer;
    }
    button:hover { background: #302638; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .card {
      border: 1px solid #39313f;
      border-radius: 16px;
      padding: 20px;
      background: #1a1920dd;
      min-height: 132px;
    }
    .wide { grid-column: 1 / -1; }
    .label { color: #a69eaf; font-size: 11px; letter-spacing: .15em; text-transform: uppercase; }
    .value { font-size: 23px; font-weight: 650; margin-top: 13px; overflow-wrap: anywhere; }
    .detail { color: #aaa3b4; font-size: 13px; margin-top: 8px; line-height: 1.55; }
    .state { display: inline-flex; align-items: center; gap: 8px; }
    .dot {
      display: inline-block;
      width: 9px;
      height: 9px;
      background: #8a79a2;
      border-radius: 50%;
    }
    .dot.ok { background: #68c89c; box-shadow: 0 0 12px #68c89c66; }
    .dot.bad { background: #d66f7c; }
    #error { color: #f29ca6; min-height: 22px; margin-top: 18px; }
    footer { color: #777181; font-size: 12px; margin-top: 28px; }
    @media (max-width: 620px) {
      header { align-items: flex-start; flex-direction: column; }
      .grid { grid-template-columns: 1fr; }
      .wide { grid-column: auto; }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div class="brand">
      <div class="orb" aria-hidden="true"></div>
      <div><h1>Ника</h1><div class="sub">LOCAL CONTROL PANEL</div></div>
    </div>
    <button id="refresh" type="button">Обновить состояние</button>
  </header>
  <section class="grid" aria-live="polite">
    <article class="card">
      <div class="label">Локальное ядро</div>
      <div class="value state">
        <span id="runtime-dot" class="dot"></span>
        <span id="runtime">Проверка…</span>
      </div>
      <div class="detail" id="uptime">Ожидание ответа локального процесса</div>
    </article>
    <article class="card">
      <div class="label">Память SQLite</div>
      <div class="value state">
        <span id="database-dot" class="dot"></span>
        <span id="database">Проверка…</span>
      </div>
      <div class="detail" id="schema">Схема базы данных</div>
    </article>
    <article class="card">
      <div class="label">Модель</div>
      <div class="value" id="provider">Проверка…</div>
      <div class="detail">Показывается только факт настройки. Адреса и ключи не раскрываются.</div>
    </article>
    <article class="card">
      <div class="label">Возможности bridge</div>
      <div class="value" id="capabilities">Проверка…</div>
      <div class="detail">Только локальный аутентифицированный канал.</div>
    </article>
    <article class="card wide">
      <div class="label">Локальное хранилище</div>
      <div class="value" id="counts">Проверка…</div>
      <div class="detail" id="updated">Данные не покидают этот компьютер.</div>
    </article>
  </section>
  <div id="error" role="status"></div>
  <footer>
    Панель доступна только через локальный адрес 127.0.0.1.
    Настройка провайдера и управление секретами появятся отдельным этапом.
  </footer>
</main>
<script nonce="__NONCE__">
(() => {
  const byId = (id) => document.getElementById(id);
  const text = (id, value) => { byId(id).textContent = String(value); };
  const dot = (id, ok) => { byId(id).className = "dot" + (ok ? " ok" : " bad"); };

  async function refresh() {
    byId("error").textContent = "";
    try {
      const response = await fetch("/dashboard/api/status", {
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      });
      if (response.status === 401) {
        throw new Error(
          "Нет локальной сессии. Закрой панель и запусти команду nika dashboard заново."
        );
      }
      if (!response.ok) throw new Error("Локальный runtime вернул HTTP " + response.status + ".");
      const data = await response.json();

      text("runtime", data.runtime === "running" ? "Работает" : "Недоступно");
      dot("runtime-dot", data.runtime === "running");
      text("uptime", "Время работы: " + Math.floor(data.uptime_seconds) + " сек.");

      text("database", data.database.healthy ? "Исправна" : "Ошибка проверки");
      dot("database-dot", data.database.healthy);
      text("schema", "Схема SQLite: v" + data.database.schema_version);

      text("provider", data.provider.configured ? "Настроен" : "Не настроен");
      text("capabilities", data.capabilities.length ? data.capabilities.join(" · ") : "Нет");
      const c = data.counts;
      text("counts", "События: " + c.events + " · Факты памяти: " + c.memories +
        " · Диалоги: " + c.conversations + " · Сообщения: " + c.messages);
      text("updated", "Обновлено: " + new Date().toLocaleTimeString());
    } catch (error) {
      byId("error").textContent = error instanceof Error
        ? error.message
        : "Не удалось получить статус.";
    }
  }

  async function bootstrap() {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const ticket = fragment.get("ticket");
    if (ticket) {
      history.replaceState(null, "", window.location.pathname);
      const response = await fetch("/dashboard/session/exchange", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket })
      });
      if (!response.ok) {
        throw new Error(
          "Ссылка на вход недействительна или истекла. Запусти nika dashboard заново."
        );
      }
    }
    await refresh();
  }

  byId("refresh").addEventListener("click", refresh);
  bootstrap().catch((error) => {
    byId("error").textContent = error instanceof Error
      ? error.message
      : "Не удалось открыть панель.";
  });
})();
</script>
</body>
</html>"""
    return html.replace("__NONCE__", nonce).encode("utf-8")
