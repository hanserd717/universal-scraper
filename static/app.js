// Простейший клиент dashboard. Токен хранится только в памяти вкладки
// (сознательно не используем localStorage здесь как пример — в реальном
// проекте выберите between localStorage/httpOnly cookie согласно вашей модели угроз).
let token = null;

async function register() {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const resp = await fetch("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const status = document.getElementById("auth-status");
  status.textContent = resp.ok ? "Регистрация успешна, теперь войдите." : "Ошибка регистрации.";
}

async function login() {
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const body = new URLSearchParams({ username: email, password });
  const resp = await fetch("/auth/login", { method: "POST", body });
  const status = document.getElementById("auth-status");
  if (resp.ok) {
    const data = await resp.json();
    token = data.access_token;
    status.textContent = "Вход выполнен.";
    loadProjects();
  } else {
    status.textContent = "Неверный email или пароль.";
  }
}

function authHeaders() {
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

async function createProject() {
  const name = document.getElementById("proj-name").value;
  const url = document.getElementById("proj-url").value;
  const legal = document.getElementById("legal-confirm").checked;

  const resp = await fetch("/projects", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ name, url, legal_confirmation: legal }),
  });

  if (resp.ok) {
    loadProjects();
  } else {
    const err = await resp.json();
    alert("Ошибка: " + JSON.stringify(err.detail));
  }
}

async function discoverCatalog() {
  const name = document.getElementById("catalog-name").value;
  const categoriesRaw = document.getElementById("catalog-categories").value;
  const count = parseInt(document.getElementById("catalog-count").value, 10) || 5;
  const categories = categoriesRaw.split(",").map((c) => c.trim()).filter(Boolean);

  const status = document.getElementById("catalog-status");

  if (!name || categories.length === 0) {
    alert("Укажите название проекта и хотя бы одну категорию");
    return;
  }

  status.textContent = "AI подбирает сервисы... это может занять до минуты";

  const resp = await fetch("/catalog/discover", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ name, categories, count_per_category: count }),
  });

  if (resp.ok) {
    status.textContent = "Готово! Проект создан ниже.";
    loadProjects();
  } else {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    status.textContent = "Ошибка: " + (err.detail || resp.status);
  }
}

async function loadProjects() {
  const resp = await fetch("/projects", { headers: authHeaders() });
  if (!resp.ok) return;
  const projects = await resp.json();
  const container = document.getElementById("projects-list");
  container.innerHTML = "";

  for (const p of projects) {
    const card = document.createElement("div");
    card.className = "bg-white rounded-lg shadow p-4 flex justify-between items-center";
    card.innerHTML = `
      <div>
        <div class="font-semibold">${p.name}</div>
        <div class="text-sm text-gray-500">${p.url} — статус: <span id="status-${p.id}">${p.status}</span></div>
      </div>
      <div class="space-x-2 flex items-center">
        <button onclick="startParsing('${p.id}')" class="bg-blue-600 text-white px-3 py-1 rounded">▶ Start</button>
        <select id="lang-${p.id}" class="border rounded px-2 py-1 text-sm">
          <option value="original">Без перевода</option>
          <option value="ru">Перевод RU</option>
          <option value="en">Перевод EN</option>
          <option value="both">Оригинал + RU + EN</option>
        </select>
        <button onclick="downloadExport(event, '${p.id}', 'excel', '${p.name}')" class="bg-gray-200 px-3 py-1 rounded">📄 Excel</button>
      </div>
    `;
    container.appendChild(card);
    subscribeProgress(p.id);
  }
}

async function startParsing(projectId) {
  await fetch(`/projects/${projectId}/start`, { method: "POST", headers: authHeaders() });
}

async function downloadExport(evt, projectId, fmt, projectName) {
  // Обычная <a href> ссылка не прикладывает Authorization-заголовок, а эндпоинт
  // экспорта защищён JWT — поэтому качаем через fetch с токеном, а не напрямую по ссылке.
  const langSelect = document.getElementById(`lang-${projectId}`);
  const lang = langSelect ? langSelect.value : "original";

  const button = evt ? evt.target : null;
  const originalText = button ? button.textContent : null;
  if (button) {
    button.textContent = lang === "original" ? "Скачивание..." : "Перевожу... (может занять время)";
    button.disabled = true;
  }

  try {
    const resp = await fetch(`/projects/${projectId}/export/${fmt}?lang=${lang}`, {
      headers: authHeaders(),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      if (resp.status === 401) {
        alert("Сессия истекла или вы не вошли в систему — войдите заново.");
      } else {
        alert("Не удалось скачать экспорт: " + (err.detail || resp.status));
      }
      return;
    }

    const blob = await resp.blob();
    const ext = fmt === "excel" ? "xlsx" : fmt;
    const downloadUrl = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = `${projectName}.${ext}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(downloadUrl);
  } finally {
    if (button) {
      button.textContent = originalText;
      button.disabled = false;
    }
  }
}

function subscribeProgress(projectId) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/projects/${projectId}/progress`);
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    const el = document.getElementById(`status-${projectId}`);
    if (el) el.textContent = `${data.status} (${data.pages_done}/${data.pages_total})`;
  };
}
