import {HOST_NAME, PROTOCOL_VERSION} from "./core.mjs";
import {HELPER_MESSAGE_KEYS} from "./i18n.mjs";

export class NativeBridge {
  constructor(runtime, {onStatus, onAction, translate}, timers = globalThis) {
    this.runtime = runtime;
    this.onStatus = onStatus;
    this.onAction = onAction;
    this.t = translate;
    this.timers = timers;
    this.port = null;
    this.retryDelay = 1000;
    this.lastSeen = 0;
    this.stopped = true;
    this.state = {};
  }

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
    this.heartbeat = this.timers.setInterval(() => {
      if (!this.port) return;
      if (Date.now() - this.lastSeen > 30_000) {
        this.disconnect(this.t("helperTimeout"));
      } else {
        this.send({type: "ping"});
      }
    }, 10_000);
  }

  connect() {
    if (this.stopped || this.port) return;
    this.timers.clearTimeout(this.retryTimer);
    this.onStatus({available: false, message: this.t("helperConnecting")});
    try {
      const port = this.runtime.connectNative(HOST_NAME);
      this.port = port;
      this.lastSeen = Date.now();
      port.onMessage.addListener(message => {
        if (this.port !== port || !message || typeof message !== "object") return;
        if (message.protocol !== PROTOCOL_VERSION) {
          this.disconnect(this.t("helperVersionMismatch"));
          return;
        }
        this.lastSeen = Date.now();
        if (message.type === "status") {
          this.retryDelay = 1000;
          this.onStatus({available: message.available === true,
            message: this.helperMessage(message)});
        } else if (message.type === "action") {
          if (["restore", "hide", "toggle", "settings", "quit"].includes(message.action)) {
            this.onAction(message.action);
          }
        } else if (message.type === "error") {
          this.disconnect(this.helperMessage(message) || this.t("helperError"));
        }
      });
      port.onDisconnect.addListener(() => {
        // Reading port.error also consumes Thunderbird's native-host failure.
        const reason = port.error?.message || this.runtime.lastError?.message;
        if (this.port === port) this.disconnect(reason ? this.t("helperConnectionError", reason) : this.t("helperDisconnected"));
      });
      this.send({type: "hello", ...this.state});
    } catch (error) {
      this.disconnect(this.t("helperConnectionError", error.message));
    }
  }

  helperMessage(message) {
    return (HELPER_MESSAGE_KEYS.has(message.messageKey) && this.t(message.messageKey)) || String(message.message ?? "");
  }

  send(message) {
    if (!this.port) return false;
    try {
      this.port.postMessage({...message, protocol: PROTOCOL_VERSION});
      return true;
    } catch (error) {
      this.disconnect(this.t("helperConnectionError", error.message));
      return false;
    }
  }

  update(state) {
    this.state = state;
    this.send({type: "state", ...state});
  }

  disconnect(message) {
    const port = this.port;
    this.port = null;
    try { port?.disconnect(); } catch { /* Already disconnected. */ }
    this.onStatus({available: false, message});
    this.timers.clearTimeout(this.retryTimer);
    if (!this.stopped) {
      this.retryTimer = this.timers.setTimeout(() => this.connect(), this.retryDelay);
      this.retryDelay = Math.min(30_000, this.retryDelay * 2);
    }
  }

  retry() {
    this.disconnect(this.t("helperReconnecting"));
    this.connect();
  }

  stop() {
    this.stopped = true;
    this.timers.clearInterval(this.heartbeat);
    this.disconnect(this.t("helperStopped"));
  }
}
