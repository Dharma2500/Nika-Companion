"""Small, self-contained local dashboard HTML.

The page has no remote scripts, styles, fonts, images or network dependencies.
A short-lived bootstrap ticket arrives only in the URL fragment and is exchanged
for an HttpOnly same-origin session cookie by the local runtime.
"""

from __future__ import annotations

import re

_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9+/]{32}$")


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
    button:disabled { opacity: .55; cursor: wait; }
    input {
      width: 100%;
      margin-top: 8px;
      border: 1px solid #51445e;
      border-radius: 10px;
      background: #121118;
      color: #f6efff;
      padding: 12px;
      font: inherit;
    }
    input:focus { outline: 2px solid #9d79c8; outline-offset: 2px; }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 18px;
    }
    .field { display: block; color: #c9c1d1; font-size: 13px; }
    details { border-top: 1px solid #39313f; margin-top: 18px; padding-top: 14px; }
    summary { color: #c7b4df; cursor: pointer; font-size: 13px; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
    .feedback { min-height: 20px; margin-top: 14px; color: #a9d9bd; font-size: 13px; }
    .feedback.bad { color: #f29ca6; }
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
      .grid, .form-grid { grid-template-columns: 1fr; }
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
      <div class="label">OpenAI API</div>
      <div class="value" id="provider">Проверка…</div>
      <div class="detail" id="provider-detail">Основной и резервный ключи.</div>
    </article>
    <article class="card">
      <div class="label">Возможности bridge</div>
      <div class="value" id="capabilities">Проверка…</div>
      <div class="detail">Только локальный аутентифицированный канал.</div>
    </article>
    <article class="card wide">
      <div class="label">Основное подключение · OpenAI</div>
      <div class="detail">
        Ключ 1 используется первым. Ключ 2 подключается при исчерпании квоты,
        временном ограничении или ошибке доступа основного ключа.
        Пустое поле при сохранении оставляет ранее сохранённый ключ без изменений.
        Секреты не возвращаются в браузер и хранятся в Windows Credential Manager.
      </div>
      <form method="post" action="/dashboard/api/openai-credentials" autocomplete="off">
        <div class="form-grid">
          <label class="field" for="openai-primary-key">
            API-ключ №1 · основной
            <input id="openai-primary-key" name="primary_key" type="password"
              maxlength="4096" autocomplete="new-password" spellcheck="false"
              placeholder="Вставь основной OpenAI API key">
          </label>
          <label class="field" for="openai-secondary-key">
            API-ключ №2 · резервный
            <input id="openai-secondary-key" name="secondary_key" type="password"
              maxlength="4096" autocomplete="new-password" spellcheck="false"
              placeholder="Вставь резервный OpenAI API key">
          </label>
          <label class="field" for="openai-model">
            Модель для обычного общения
            <input id="openai-model" name="model" type="text" maxlength="160"
              value="gpt-4.1-mini" autocomplete="off" spellcheck="false">
          </label>
          <label class="field" for="openai-daily-limit">
            Лимит токенов в сутки
            <input id="openai-daily-limit" name="daily_token_limit" type="number"
              min="1000" max="5000000" step="1000" value="60000">
          </label>
        </div>
        <div class="actions">
          <button type="submit" name="action" value="save">Сохранить ключи и настройки</button>
          <button type="submit" name="action" value="test">
            Проверить сохранённые ключи (до 64 токенов)
          </button>
          <button type="submit" name="action" value="clear_primary">Удалить ключ №1</button>
          <button type="submit" name="action" value="clear_secondary">Удалить ключ №2</button>
        </div>
      </form>
      <div id="openai-feedback" class="feedback" role="status"></div>
      <div class="detail" id="openai-usage">Использование API ещё не зарегистрировано.</div>
      <details>
        <summary>Дополнительно: OpenAI-compatible / LM Studio (на будущее)</summary>
        <div class="detail">
          Альтернативный локальный провайдер сохранён в архитектуре, но сейчас не активируется
          автоматически и не тестируется. Основной режим проекта — OpenAI API.
        </div>
        <div class="form-grid">
          <label class="field" for="provider-base-url">
            Base URL
            <input id="provider-base-url" type="url" maxlength="2048"
              placeholder="http://127.0.0.1:1234/v1" autocomplete="off" spellcheck="false">
          </label>
          <label class="field" for="provider-model">
            Model ID
            <input id="provider-model" type="text" maxlength="160"
              placeholder="Имя модели" autocomplete="off" spellcheck="false">
          </label>
        </div>
        <div class="actions">
          <button id="provider-save" type="button">Сохранить альтернативный endpoint</button>
        </div>
        <div id="provider-feedback" class="feedback" role="status"></div>
      </details>
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
    Ключи хранятся в Windows Credential Manager. В SQLite сохраняются только сообщения,
    проверенные воспоминания и счётчики токенов.
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

      const openai = data.openai;
      text(
        "provider",
        openai.primary_configured || openai.secondary_configured
          ? "OpenAI подключён"
          : (data.provider.configured ? "Альтернативный провайдер" : "Не настроен")
      );
      text(
        "provider-detail",
        "Ключ 1: " + (openai.primary_configured ? "сохранён" : "нет") +
        " · Ключ 2: " + (openai.secondary_configured ? "сохранён" : "нет") +
        " · Активный: " + (openai.active_slot || "нет")
      );
      if (document.activeElement !== byId("openai-model")) {
        byId("openai-model").value = openai.model || "gpt-4.1-mini";
      }
      if (document.activeElement !== byId("openai-daily-limit")) {
        byId("openai-daily-limit").value = openai.daily_token_limit || 60000;
      }
      text(
        "openai-usage",
        "Сегодня: " + openai.usage.total_tokens.toLocaleString("ru-RU") +
        " / " + openai.daily_token_limit.toLocaleString("ru-RU") +
        " токенов · запросов: " + openai.usage.requests +
        " · вход: " + openai.usage.input_tokens +
        " · выход: " + openai.usage.output_tokens +
        " · кеш: " + openai.usage.cached_tokens
      );
      text("capabilities", data.capabilities.length ? data.capabilities.join(" · ") : "Нет");
      if (document.activeElement !== byId("provider-base-url")) {
        byId("provider-base-url").value = data.provider.base_url || "";
      }
      if (document.activeElement !== byId("provider-model")) {
        byId("provider-model").value = data.provider.model || "";
      }
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

  async function postJson(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(
        data.message || "Запрос отклонён (HTTP " + response.status + ")."
      );
    }
    return data;
  }

  function showProviderFeedback(message, bad = false) {
    const target = byId("provider-feedback");
    target.textContent = message;
    target.className = "feedback" + (bad ? " bad" : "");
  }

  byId("provider-save").addEventListener("click", async () => {
    showProviderFeedback("Сохраняю настройки…");
    byId("provider-save").disabled = true;
    try {
      await postJson("/dashboard/api/provider", {
        base_url: byId("provider-base-url").value.trim(),
        model: byId("provider-model").value.trim()
      });
      showProviderFeedback(
        "Настройки сохранены. Теперь нажми «Проверить соединение»."
      );
      await refresh();
    } catch (error) {
      showProviderFeedback(
        error instanceof Error ? error.message : "Не удалось сохранить настройки.",
        true
      );
    } finally {
      byId("provider-save").disabled = false;
    }
  });

  byId("provider-test").addEventListener("click", async () => {
    showProviderFeedback("Проверяю соединение и генерацию…");
    byId("provider-test").disabled = true;
    try {
      await postJson("/dashboard/api/provider/test", {});
      showProviderFeedback(
        "Модель отвечает. Ника готова к приватному диалогу."
      );
      await refresh();
    } catch (error) {
      showProviderFeedback(
        error instanceof Error ? error.message : "Модель не ответила.",
        true
      );
    } finally {
      byId("provider-test").disabled = false;
    }
  });

  const notice = new URLSearchParams(window.location.search).get("notice");
  const noticeMessages = {
    saved: "Настройки сохранены. Значения ключей не отображаются.",
    cleared: "Ключ удалён из Windows Credential Manager.",
    test_ok: "OpenAI отвечает. Тестовый запрос учтён в токенах.",
    test_failed: "Проверка OpenAI не прошла. Проверь ключ, доступ к модели и квоту.",
    no_keys: "Сначала сохрани хотя бы один API-ключ.",
    credential_store_unavailable: "Windows Credential Manager недоступен. Ключи не сохранены."
  };
  if (notice && noticeMessages[notice]) {
    text("openai-feedback", noticeMessages[notice]);
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
