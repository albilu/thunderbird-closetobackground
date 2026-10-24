import {createI18n, localizeDocument} from "../lib/i18n.mjs";

const api = messenger;
const i18n = createI18n(api.i18n);
const t = i18n.message;
localizeDocument(document, i18n);
const form = document.querySelector("form");
const saveStatus = document.querySelector("#save-status");
const actionStatus = document.querySelector("#action-status");
let saving = false;

async function request(type, extra = {}) {
  const result = await api.runtime.sendMessage({type, ...extra});
  if (!result?.ok) throw new Error(result?.error || t("backgroundUnavailable"));
  return result.state;
}

function render(state) {
  const {settings, tray, unread, unreadIncomplete} = state;
  for (const input of form.querySelectorAll("input")) {
    input.checked = settings[input.name];
    input.disabled = saving || (input.name !== "enabled" && !settings.enabled);
  }
  const active = settings.enabled && tray.available && !state.windowError;
  document.querySelector("#status-title").textContent = t(!settings.enabled ? "statusDisabled" : active ? "statusReady" : "statusWaiting");
  document.querySelector("#status-detail").textContent = !settings.enabled ? t("statusDisabledDescription") : state.windowError || tray.message || t("statusInstallHelper");
  document.querySelector("#status-dot").className = `dot ${!settings.enabled ? "disabled" : active ? "ready" : ""}`;
  document.querySelector("#unread").textContent = `${unreadIncomplete ? "~" : ""}${i18n.number(unread)}`;
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
  saveStatus.textContent = t("settingsSaving");
  try {
    const state = await request("saveSettings", {settings: {[input.name]: input.checked}});
    saving = false;
    render(state);
    saveStatus.textContent = t("settingsSaved");
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
      actionStatus.textContent = t(button.id === "testNotification" ? "notificationRequested" : button.id === "retry" ? "statusReconnecting" : "actionDone");
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
    document.querySelector("#status-title").textContent = t("statusConnectionFailed");
    document.querySelector("#status-detail").textContent = error.message;
    document.querySelector("#status-dot").className = "dot";
    document.querySelector("#hide").disabled = true;
    document.querySelector("#testNotification").disabled = true;
  }
}
await refresh();
setInterval(refresh, 2000);
