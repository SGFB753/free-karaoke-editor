// Open optional sections and scroll the single properties panel as a user does.
export function useWorkspaceNavigation(page){
  const click = page.click.bind(page);
  page.click = async (selector, ...args) => {
    const pane = await page.evaluate(sel => {
      const parent = document.querySelector(sel)?.closest('[data-pane]');
      if (!parent) return null;
      if (parent.classList.contains('hide')) return parent.dataset.pane;
      if (parent.closest('.side.settings-open') && ['line','check'].includes(parent.dataset.pane)) return 'close';
      return null;
    }, selector);
    if (pane) await click(pane === 'close' ? '#btnWorkspaceClose' :
      pane === 'look' ? '#btnWorkspaceLook' : '#btnWorkspaceProject');
    await page.evaluate(sel => {
      const element = document.querySelector(sel);
      if (element && element.closest('[data-pane]')) element.scrollIntoView({block:'nearest'});
    }, selector);
    return click(selector, ...args);
  };
}
