"""Disposable local mail data for the real Thunderbird/GNOME integration test."""

ADD_MAIL = r"""
const {MailServices} = ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');
const root = MailServices.accounts.localFoldersServer.rootFolder;
const inbox = root.getChildNamed('Inbox');
const batch = inbox.getTotalMessages(false);
function add(folder, id) {
  const local = folder.QueryInterface(Ci.nsIMsgLocalMailFolder);
  const header = local.addMessage(
    'From - Fri Oct 23 2026 10:00:00\r\n' +
    'X-Mozilla-Status: 0000\r\nX-Mozilla-Status2: 00000000\r\n' +
    'Message-ID: <tray-smoke-' + batch + '-' + id + '@example.invalid>\r\n' +
    'Date: Fri, 23 Oct 2026 10:00:00 +0000\r\n' +
    'From: Private Sender <sender@example.invalid>\r\n' +
    'To: Local Test <local@example.invalid>\r\n' +
    'Subject: Private smoke-test subject\r\n\r\nLocal test message.\r\n');
  header.orFlags(Ci.nsMsgMessageFlags.New);
  MailServices.mfn.notifyMsgAdded(header);
}
for (let i = 0; i < 3; i++) add(inbox, i);
add(root.getChildNamed('Trash'), 'trash');
return {inbox: inbox.getNumUnread(false), trash: root.getChildNamed('Trash').getNumUnread(false)};
"""

CREATE_MAIL = r"""
{
  const {MailServices} = ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');
  MailServices.accounts.createLocalMailAccount();
  const root = MailServices.accounts.localFoldersServer.rootFolder;
  root.createSubfolder('Inbox', null);
  root.getChildNamed('Inbox').setFlag(Ci.nsMsgFolderFlags.Inbox);
}
""" + ADD_MAIL

MARK_READ = """
const {MailServices} = ChromeUtils.importESModule('resource:///modules/MailServices.sys.mjs');
const inbox = MailServices.accounts.localFoldersServer.rootFolder.getChildNamed('Inbox');
inbox.markMessagesRead(Array.from(inbox.messages), true);
return inbox.getNumUnread(false);
"""
