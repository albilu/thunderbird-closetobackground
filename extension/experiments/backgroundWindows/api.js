/* global ChromeUtils, Services, Ci, Cc, Cu, fetch, FileReader */
// An IIFE keeps experiment globals isolated from other add-ons.
var backgroundWindows = (() => {
  const {ExtensionCommon} = ChromeUtils.importESModule("resource://gre/modules/ExtensionCommon.sys.mjs");
  const {ExtensionSupport} = ChromeUtils.importESModule("resource:///modules/ExtensionSupport.sys.mjs");

  return class extends ExtensionCommon.ExtensionAPI {
    initialize() {
      if (this.windows) return;
      this.configuration = {enabled: false, closeToTray: true, minimizeToTray: true};
      this.windows = new Map();
      this.quitting = false;
      this.quitGranted = false;
      this.listenerId = `${this.extension.id}-background-windows`;
      this.quitObserver = {
        observe: (_subject, topic) => {
          this.quitting = true;
          if (topic === "quit-application-granted") this.quitGranted = true;
          else Services.tm.dispatchToMainThread(() => {
            // A cancelled quit (for example an unsaved draft) must not disable us.
            if (!this.quitGranted) this.quitting = false;
          });
        },
      };
      Services.obs.addObserver(this.quitObserver, "quit-application-requested");
      Services.obs.addObserver(this.quitObserver, "quit-application-granted");
      ExtensionSupport.registerWindowListener(this.listenerId, {
        chromeURLs: ["chrome://messenger/content/messenger.xhtml"],
        onLoadWindow: win => this.attach(win),
        onUnloadWindow: win => this.detach(win),
      });
    }

    baseWindow(win) {
      return win.docShell.treeOwner.QueryInterface(Ci.nsIBaseWindow);
    }

    attach(win) {
      if (win.document.documentElement.getAttribute("windowtype") !== "mail:3pane" || this.windows.has(win)) return;
      const record = {hidden: false, restoring: false, state: win.windowState};
      // Wayland does not report a minimized state back to the client. Intercept
      // Thunderbird's own minimize command before GTK sends it to the compositor.
      record.originalMinimize = win.minimize;
      record.minimize = (...args) => {
        if (this.configuration.enabled && this.configuration.minimizeToTray && !this.quitting) {
          try { this.hide(win, record); return; } catch (error) { console.error(error); }
        }
        return record.originalMinimize.apply(win, args);
      };
      win.minimize = record.minimize;
      // Thunderbird's client-side titlebar calls window.close() directly. That
      // path bypasses the cancelable close event sent by the window manager.
      record.originalClose = win.close;
      record.closeWindow = (...args) => {
        if (this.configuration.enabled && this.configuration.closeToTray && !this.quitting) {
          try { this.hide(win, record); return; }
          catch (error) { console.error("Close to Background: window could not be hidden", error); }
        }
        return record.originalClose.apply(win, args);
      };
      win.close = record.closeWindow;
      // A second launch/launcher activation asks the existing mail window to
      // focus. Native focus alone does not map a window hidden via visibility.
      // Restore first, then let Thunderbird handle focus and activation tokens.
      record.originalFocus = win.focus;
      record.focus = (...args) => {
        if (record.hidden && !record.restoring && !this.quitting) this.restore();
        return record.originalFocus.apply(win, args);
      };
      win.focus = record.focus;
      record.close = event => {
        if (!this.configuration.enabled || !this.configuration.closeToTray || this.quitting) return;
        // Do not trap closing subdocuments, tabs, or modal dialogs.
        if (event.target !== win && event.target !== win.document) return;
        try {
          this.hide(win, record);
          event.preventDefault();
          event.stopImmediatePropagation();
        } catch (error) {
          console.error("Close to Background: window could not be hidden", error);
        }
      };
      record.resize = () => {
        if (record.restoring) {
          if (win.windowState !== win.STATE_MINIMIZED) {
            record.restoring = false;
            win.clearTimeout(record.restoreTimer);
            record.state = win.windowState;
          }
          return;
        }
        if (record.hidden) return;
        if (win.windowState === win.STATE_MINIMIZED) {
          if (this.configuration.enabled && this.configuration.minimizeToTray && !this.quitting) {
            try { this.hide(win, record); } catch (error) { console.error(error); }
          }
        } else record.state = win.windowState;
      };
      win.addEventListener("close", record.close, true);
      win.addEventListener("sizemodechange", record.resize);
      this.windows.set(win, record);
    }

    detach(win) {
      const record = this.windows.get(win);
      if (!record) return;
      win.removeEventListener("close", record.close, true);
      win.removeEventListener("sizemodechange", record.resize);
      win.clearTimeout(record.restoreTimer);
      if (win.minimize === record.minimize) win.minimize = record.originalMinimize;
      if (win.close === record.closeWindow) win.close = record.originalClose;
      if (win.focus === record.focus) win.focus = record.originalFocus;
      this.windows.delete(win);
    }

    hide(win, record) {
      if (win.closed) return;
      const base = this.baseWindow(win);
      win.clearTimeout(record.restoreTimer);
      record.restoring = false;
      // Keep the last non-minimized state so maximized windows restore correctly.
      if (!record.hidden && win.windowState !== win.STATE_MINIMIZED) record.state = win.windowState;
      base.visibility = false;
      // AppWindow::GetVisibility deliberately always returns true (Mozilla bug
      // 306245). The setter controls the native widget; do not read it back.
      record.hidden = true;
    }

    restore(focus = false) {
      let front = null;
      for (const [win, record] of this.windows) {
        if (win.closed) continue;
        if (!record.hidden) {
          front ??= win;
          continue;
        }
        try {
          record.restoring = true;
          win.clearTimeout(record.restoreTimer);
          // GTK's sizemodechange events arrive asynchronously. Ignore stale
          // minimized events until the compositor reports the restored state.
          record.restoreTimer = win.setTimeout(() => {
            record.restoring = false;
            // A fresh minimize can arrive before a restore finishes. Reconcile
            // the final state rather than dropping the user's newer action.
            if (!win.closed && win.windowState === win.STATE_MINIMIZED &&
                this.configuration.enabled && this.configuration.minimizeToTray && !this.quitting) {
              try { this.hide(win, record); } catch (error) { console.error(error); }
            }
          }, 500);
          this.baseWindow(win).visibility = true;
          win.restore();
          if (record.state === win.STATE_MAXIMIZED) win.maximize();
          if (record.state === win.STATE_FULLSCREEN) win.fullScreen = true;
          record.hidden = false;
          front = win;
        } catch (error) {
          record.restoring = false;
          console.error("Close to Background: restoring window failed", error);
        }
      }
      if (focus && front) {
        if (front.windowState === front.STATE_MINIMIZED) front.restore();
        front.focus();
      }
    }

    getAPI(context) {
      this.initialize();
      context.callOnClose({close: () => {
        this.configuration.enabled = false;
        this.restore();
      }});
      return {backgroundWindows: {
        getApplicationIcon: async () => {
          // Branding chrome URLs cannot be loaded by the notification's extension
          // principal. Return only Thunderbird's own artwork as a portable data URL.
          Cu.importGlobalProperties(["fetch", "FileReader"]);
          const response = await fetch("chrome://branding/content/icon128.png");
          if (!response.ok) throw new Error("Thunderbird's application icon could not be loaded.");
          const blob = await response.blob();
          return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob.slice(0, blob.size, "image/png"));
          });
        },
        configure: async configuration => {
          if (Services.appinfo.OS !== "Linux" && configuration.enabled) {
            throw new Error("Close to Background supports Linux only.");
          }
          this.configuration = {...configuration};
          if (!configuration.enabled) this.restore();
        },
        hideAll: async () => {
          if (!this.configuration.enabled || this.quitting) throw new Error("The tray is not available.");
          try {
            for (const [win, record] of this.windows) this.hide(win, record);
          } catch (error) {
            this.restore(true);
            throw error;
          }
        },
        restoreAll: async () => this.restore(true),
        quit: async () => {
          this.restore(true);
          const win = Services.wm.getMostRecentWindow("mail:3pane");
          // Uses Thunderbird's normal quit path, including unsaved-compose prompts.
          if (win) win.goQuitApplication();
        },
      }};
    }

    onShutdown(isAppShutdown) {
      if (!this.windows) return;
      this.configuration.enabled = false;
      if (!isAppShutdown) this.restore();
      for (const win of [...this.windows.keys()]) this.detach(win);
      ExtensionSupport.unregisterWindowListener(this.listenerId);
      Services.obs.removeObserver(this.quitObserver, "quit-application-requested");
      Services.obs.removeObserver(this.quitObserver, "quit-application-granted");
      if (!isAppShutdown) Services.obs.notifyObservers(null, "startupcache-invalidate");
    }
  };
})();
