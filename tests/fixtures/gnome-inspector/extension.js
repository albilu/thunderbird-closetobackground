import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {dockManager} from 'file:///usr/share/gnome-shell/extensions/dash-to-dock@micxgx.gmail.com/extension.js';

// Installed only in the test's temporary XDG_DATA_HOME, never in the user's Shell.
const XML = `<node><interface name="net.thunderbird.TrayTest">
  <method name="Windows"><arg type="s" direction="out"/></method>
  <method name="Close"><arg type="s" direction="in"/></method>
  <method name="Minimize"><arg type="s" direction="in"/></method>
  <method name="ActivateApplication"/>
  <method name="ApplicationState"><arg type="s" direction="out"/></method>
  <method name="ClickDash"/>
  <method name="DockState"><arg type="s" direction="out"/></method>
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
      focused: actor.meta_window.has_focus(),
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
  dockIcon() {
    return dockManager?.mainDock?.dash.getAppIcons().find(icon => icon.app.get_id() === 'thunderbird.desktop');
  }
  ClickDash() {
    const icon = this.dockIcon();
    if (!icon) throw new Error('The private Thunderbird dock icon is missing');
    // Exercise the installed extension's primary-click handler, including its
    // preference/focus checks, instead of Shell.App.activate().
    icon.activate(1);
  }
  DockState() {
    const icon = this.dockIcon();
    return JSON.stringify(icon ? {
      running: !!icon.running, focused: !!icon.focused,
      windows: icon.getInterestingWindows().length,
      clickAction: new Gio.Settings({schema_id: 'org.gnome.shell.extensions.dash-to-dock'}).get_string('click-action'),
    } : null);
  }
  disable() {
    this.exported?.unexport();
    this.exported = null;
  }
}
