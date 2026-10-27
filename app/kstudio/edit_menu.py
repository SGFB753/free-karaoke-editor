"""Native clipboard editing for the Windows WebView, without debug mode."""
import logging


def install(window):
    """Configure the native control before its first page navigation.

    WebView2 snapshots context-menu settings at navigation time. A loaded
    callback is too late: it changes the property but leaves menus disabled
    for the document that the user is already editing.
    """
    def before_show():
        host = window.native.webview
        if host.CoreWebView2 is not None:
            enable(window)
            return

        def initialized(_sender, args):
            if args.IsSuccess:
                enable(window)

        host.CoreWebView2InitializationCompleted += initialized
        window._studio_edit_menu_initialized = initialized

    window.events.before_show += before_show


def editable_context_menu(sender, args):
    """Keep the native edit menu for inputs, not for the timeline/background."""
    args.Handled = not bool(getattr(args.ContextMenuTarget, 'IsEditable', False))
    if args.Handled:
        return
    # Keep the built-in commands: Chromium owns selection, clipboard access,
    # undo history and disabled states. Remove browser tools and separators.
    items = args.MenuItems
    for index in range(items.Count - 1, -1, -1):
        if items[index].Name not in {'cut', 'copy', 'paste', 'delete'}:
            items.RemoveAt(index)
    if not any(item.Name == 'delete' for item in items):
        # Current WebView2 versions omit Delete from their built-in menu.
        from Microsoft.Web.WebView2.Core import CoreWebView2ContextMenuItemKind
        from .i18n import tr
        delete = sender.Environment.CreateContextMenuItem(
            tr('Delete', 'Удалить'), None, CoreWebView2ContextMenuItemKind.Command)
        delete.IsEnabled = bool(args.ContextMenuTarget.HasSelection)

        def delete_selected(_item, _event):
            sender.ExecuteScriptAsync("document.execCommand('delete')")

        delete.CustomItemSelected += delete_selected
        items.Insert(items.Count, delete)


def enable(window):
    """Enable editing menus: pywebview disables all native menus by default.

    Its loaded callbacks run outside the WinForms UI thread. Marshal settings
    and event registration through the owned WebView control, never a browser
    profile or a global clipboard hook.
    """
    try:
        host = window.native.webview
        applied = [False]

        def configure():
            core = host.CoreWebView2
            previous = getattr(window, '_studio_edit_menu', None)
            if not previous or previous[0] != core:
                core.ContextMenuRequested += editable_context_menu
                # Keep the Python callback alive for the native event lifetime.
                window._studio_edit_menu = (core, editable_context_menu)
            core.Settings.AreDefaultContextMenusEnabled = True
            applied[0] = True

        if host.InvokeRequired:
            from System import Action
            host.Invoke(Action(configure))
        else:
            configure()
        return applied[0]
    except Exception:
        logging.getLogger(__name__).exception('Could not enable the native text editing menu')
        return False
