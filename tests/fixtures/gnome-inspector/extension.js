import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// Installed only in the test's temporary XDG_DATA_HOME, never in the user's Shell.
const XML = `<node><interface name="net.thunderbird.TrayTest">
  <method name="Windows"><arg type="s" direction="out"/></method>
  <method name="Close"><arg type="s" direction="in"/></method>
  <method name="Minimize"><arg type="s" direction="in"/></method>
  <method name="ActivateApplication"/>
  <method name="ApplicationState"><arg type="s" direction="out"/></method>
</interface></node>`;

export default class TrayTestInspector extends Extension {
  enable() {
    this.exported = Gio.DBusExportedObject.wrapJSObject(XML, this);
    this.exported.export(Gio.DBus.session, '/net/thunderbird/TrayTest');
  }
  Windows() {
    return JSON.stringify(global.get_window_actors().map(actor => ({
      title: actor.meta_window.get_title(),
      visible: actor.is_visible() && !actor.meta_window.is_hidden(),
      minimized: actor.meta_window.minimized,
      clientType: actor.meta_window.get_client_type() === Meta.WindowClientType.WAYLAND ? 'wayland' : 'x11',
      appId: Shell.WindowTracker.get_default().get_window_app(actor.meta_window)?.get_id(),
    })));
  }
  Close(title) {
    for (const actor of global.get_window_actors()) {
      if (actor.meta_window.get_title() === title) actor.meta_window.delete(global.get_current_time());
    }
  }
  Minimize(title) {
    for (const actor of global.get_window_actors()) {
      if (actor.meta_window.get_title() === title) actor.meta_window.minimize();
    }
  }
  ActivateApplication() {
    const app = Shell.AppSystem.get_default().lookup_app('thunderbird.desktop');
    if (!app) throw new Error('The private Thunderbird launcher is missing');
    app.activate();
  }
  ApplicationState() {
    const app = Shell.AppSystem.get_default().lookup_app('thunderbird.desktop');
    return JSON.stringify({
      running: app?.get_state() === Shell.AppState.RUNNING,
      starting: app?.get_state() === Shell.AppState.STARTING,
      windows: app?.get_n_windows() ?? 0,
    });
  }
  disable() {
    this.exported?.unexport();
    this.exported = null;
  }
}
