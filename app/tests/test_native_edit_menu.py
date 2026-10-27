"""Native editing menus must not enable debugging or read the clipboard."""
import os
import importlib.util
import json
import subprocess
import sys
import unittest
from types import SimpleNamespace as Item
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kstudio import edit_menu as E


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, callback):
        self.handlers.append(callback)
        return self


class MenuItems(list):
    @property
    def Count(self):
        return len(self)

    def RemoveAt(self, index):
        del self[index]

    def Insert(self, index, item):
        self.insert(index, item)


class MenuTests(unittest.TestCase):
    def window(self, invoke=False):
        settings = Item(AreDefaultContextMenusEnabled=False, AreDevToolsEnabled=False,
                        AreBrowserAcceleratorKeysEnabled=False)
        core = Item(Settings=settings, ContextMenuRequested=Event())
        host = Item(CoreWebView2=core, InvokeRequired=invoke)
        host.Invoke = lambda callback: callback()
        return Item(native=Item(webview=host))

    def test_enables_only_native_edit_menu_without_debug(self):
        window = self.window()
        self.assertTrue(E.enable(window))
        core = window.native.webview.CoreWebView2
        self.assertTrue(core.Settings.AreDefaultContextMenusEnabled)
        self.assertFalse(core.Settings.AreDevToolsEnabled)
        self.assertFalse(core.Settings.AreBrowserAcceleratorKeysEnabled)
        self.assertEqual(core.ContextMenuRequested.handlers, [E.editable_context_menu])

    def test_editable_inputs_keep_menu_but_background_and_readonly_do_not(self):
        for editable in (True, False):
            args = Item(ContextMenuTarget=Item(IsEditable=editable), Handled=False,
                        MenuItems=MenuItems([Item(Name='delete')]))
            E.editable_context_menu(None, args)
            self.assertEqual(args.Handled, not editable)
        args = Item(ContextMenuTarget=None, Handled=False)
        E.editable_context_menu(None, args)
        self.assertTrue(args.Handled)

    def test_only_four_editing_commands_remain_with_native_disabled_states(self):
        commands = [Item(Name=name, IsEnabled=False) for name in
                    ('emoji', 'undo', 'cut', 'copy', 'paste', 'pasteAndMatchStyle',
                     'delete', 'selectAll', 'other', 'moreTools')]
        args = Item(ContextMenuTarget=Item(IsEditable=True), Handled=False,
                    MenuItems=MenuItems(commands))
        E.editable_context_menu(None, args)
        self.assertEqual([item.Name for item in args.MenuItems], ['cut', 'copy', 'paste', 'delete'])
        self.assertTrue(all(not item.IsEnabled for item in args.MenuItems))

    def test_delete_command_uses_the_editors_selection_and_is_disabled_without_it(self):
        for selected in (False, True):
            delete = Item(Name='custom-delete', CustomItemSelected=Event())
            scripts = []
            sender = Item(Environment=Item(CreateContextMenuItem=lambda *a: delete),
                          ExecuteScriptAsync=scripts.append)
            args = Item(ContextMenuTarget=Item(IsEditable=True, HasSelection=selected),
                        Handled=False, MenuItems=MenuItems([Item(Name='paste')]))
            core = Item(CoreWebView2ContextMenuItemKind=Item(Command=1))
            with patch.dict(sys.modules, {'Microsoft.Web.WebView2.Core': core}):
                E.editable_context_menu(sender, args)
            self.assertEqual(delete.IsEnabled, selected)
            self.assertIs(args.MenuItems[-1], delete)
            if selected:
                delete.CustomItemSelected.handlers[0](None, None)
                self.assertEqual(scripts, ["document.execCommand('delete')"])

    def test_reloading_page_does_not_add_duplicate_native_callbacks(self):
        window = self.window()
        self.assertTrue(E.enable(window))
        self.assertTrue(E.enable(window))
        self.assertEqual(len(window.native.webview.CoreWebView2.ContextMenuRequested.handlers), 1)

    def test_settings_are_marshalled_to_the_windows_ui_thread(self):
        window = self.window(invoke=True)
        with patch.dict(sys.modules, {'System': Item(Action=lambda callback: callback)}):
            self.assertTrue(E.enable(window))
        self.assertTrue(window.native.webview.CoreWebView2.Settings.AreDefaultContextMenusEnabled)

    def test_missing_native_backend_does_not_crash_the_application(self):
        with self.assertLogs('kstudio.edit_menu', level='ERROR'):
            self.assertFalse(E.enable(Item(native=None)))

    def test_install_waits_for_native_initialization_before_first_navigation(self):
        window = self.window()
        core = window.native.webview.CoreWebView2
        window.native.webview.CoreWebView2 = None
        window.native.webview.CoreWebView2InitializationCompleted = Event()
        window.events = Item(before_show=Event(), loaded=Event())
        E.install(window)
        self.assertFalse(window.events.loaded.handlers)
        window.events.before_show.handlers[0]()
        self.assertFalse(core.Settings.AreDefaultContextMenusEnabled)
        window.native.webview.CoreWebView2 = core
        callback = window.native.webview.CoreWebView2InitializationCompleted.handlers[0]
        callback(None, Item(IsSuccess=True))
        self.assertTrue(core.Settings.AreDefaultContextMenusEnabled)

    @unittest.skipUnless(sys.platform == 'win32' and importlib.util.find_spec('webview'),
                         'requires Windows WebView2')
    def test_real_native_right_click_in_fields_on_the_first_document(self):
        # Reading Settings alone cannot catch settings applied after navigation.
        helper = os.path.join(os.path.dirname(__file__), 'helpers', 'native_edit_menu_smoke.py')
        run = subprocess.run([sys.executable, helper], capture_output=True,
                             text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(json.loads(run.stdout.strip().splitlines()[-1])['ok'])


if __name__ == '__main__':
    unittest.main()
