const api = messenger;
const form = document.querySelector("form");
const saveStatus = document.querySelector("#save-status");
const actionStatus = document.querySelector("#action-status");
let saving = false;

async function request(type, extra = {}) {
  const result = await api.runtime.sendMessage({type, ...extra});
  if (!result?.ok) throw new Error(result?.error || "The add-on background page is unavailable.");
  return result.state;
}

function render(state) {
  const {settings, tray, unread, unreadIncomplete} = state;
  for (const input of form.querySelectorAll("input")) {
    input.checked = settings[input.name];
    input.disabled = saving || (input.name !== "enabled" && !settings.enabled);
  }
  const active = settings.enabled && tray.available && !state.windowError;
  document.querySelector("#status-title").textContent = !settings.enabled ? "Background mode is off" : active ? "Your tray is ready" : "Waiting for a working tray";
  document.querySelector("#status-detail").textContent = !settings.enabled ? "Thunderbird windows close and minimize normally." : state.windowError || tray.message || "Install the helper to get started.";
  document.querySelector("#status-dot").className = `dot ${!settings.enabled ? "disabled" : active ? "ready" : ""}`;
  document.querySelector("#unread").textContent = `${unreadIncomplete ? "~" : ""}${unread}`;
  const diagnostics = [state.mailError, state.notificationError].filter(Boolean).join(" ");
  document.querySelector("#diagnostics").textContent = diagnostics;
  document.querySelector("#diagnostics").hidden = !diagnostics;
  document.querySelector("#hide").disabled = !active;
  document.querySelector("#testNotification").disabled = !settings.enabled || !settings.notifications;
}

form.addEventListener("change", async event => {
  const input = event.target;
  if (input.tagName !== "INPUT") return;
  saving = true;
  for (const field of form.querySelectorAll("input")) field.disabled = true;
  saveStatus.textContent = "Saving…";
  try {
    const state = await request("saveSettings", {settings: {[input.name]: input.checked}});
    saving = false;
    render(state);
    saveStatus.textContent = "Saved.";
    saveStatus.classList.remove("error");
  } catch (error) {
    saving = false;
    saveStatus.textContent = error.message;
    saveStatus.classList.add("error");
    void refresh();
  }
});

for (const button of document.querySelectorAll("button")) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await request(button.id);
      actionStatus.classList.remove("error");
      actionStatus.textContent = button.id === "testNotification" ? "Notification requested. Your desktop’s notification preferences apply." : button.id === "retry" ? "Reconnecting…" : "Done.";
    } catch (error) {
      actionStatus.textContent = error.message;
      actionStatus.classList.add("error");
    } finally { button.disabled = false; await refresh(); }
  });
}

async function refresh() {
  try {
    const state = await request("getState");
    if (!saving) render(state);
  } catch (error) {
    document.querySelector("#status-title").textContent = "Unable to connect";
    document.querySelector("#status-detail").textContent = error.message;
    document.querySelector("#status-dot").className = "dot";
    document.querySelector("#hide").disabled = true;
    document.querySelector("#testNotification").disabled = true;
  }
}
await refresh();
setInterval(refresh, 2000);
