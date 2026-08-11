# Adding a language

The window speaks English and Russian out of the box; both live in `ui.js`.
Any further language is a JSON file in this folder named after its code —
`de.json`, `fr.json`, `uk.json` — with the same keys.

1. Copy `template.json` to `<code>.json`.
2. Translate the values. Leave a value empty and the English one is used, so a
   half-finished file is still useful.
3. Add the code to `LANGS` in `ui.js` (one line) and reload the window.

Keys whose value is a function in `ui.js` (they take a number or a name) are
not in the template: they need code, not translation, and stay English for now.

The finished karaoke page carries its own copy of the labels, so a page built
before a language was added keeps the language it was built with.
