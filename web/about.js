/**
 * about.js
 * ========
 *
 * What version this is, and how somebody tells you it broke.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * A tester who is not you will report a problem as "it didn't work". That is
 * not their fault, it is all they can see. What turns that into something
 * fixable is knowing which browser, which screen, whether the browser was
 * even willing to save anything, and what the last error was. None of it is
 * anything they could be expected to find on their own, and all of it is
 * sitting right here in the page.
 *
 * So there is a button that writes the report for them.
 *
 * WHAT IT DELIBERATELY DOES NOT COLLECT
 * -------------------------------------
 * Nothing about what is IN their inventory. No profile names, no room names,
 * no item names, no notes, no counts of anything inside a profile. How many
 * profiles are saved, and nothing else. This is somebody's home or their
 * workplace, and the point of the whole app is that it never leaves their
 * machine. A diagnostics button that quietly walked their data out of that
 * promise would be worse than no diagnostics button.
 *
 * And nothing is sent anywhere. The report is put on screen, in a box they
 * can read, and copying it is a thing they do. If they do not like the look
 * of it they can edit it or close it.
 */

/** Bumped by hand when a batch goes out. Dated rather than numbered, because
 *  the useful question in a bug report is "how old is this" and a date
 *  answers it without anybody having to look up a changelog. */
export const VERSION = "2026-09-28";


// The last thing that went wrong, or null. Kept here rather than in a
// variable in app.js because the listeners below have to be installed before
// anything else runs, and this file has no other work to do at load time.
let lastError = null;

export function watchForErrors() {
  window.addEventListener("error", event => {
    lastError = describe(event.error, event.message, event.filename,
                         event.lineno);
  });
  window.addEventListener("unhandledrejection", event => {
    lastError = describe(event.reason, String(event.reason));
  });
}

function describe(error, message, file, line) {
  const where = file ? ` (${file.split("/").pop()}:${line})` : "";
  const name = error?.name ? `${error.name}: ` : "";
  return `${name}${error?.message || message || "something failed"}${where}`;
}


/** The report, as plain text.
 *
 *  `store` is the storage layer or null, which is itself worth reporting: a
 *  browser that refuses to keep anything is the single most common reason for
 *  "I lost my work", and it is invisible from the inside.
 */
export function report(store, savedCount) {
  const lines = [
    `Invenfloor ${VERSION}`,
    `Page: ${location.href}`,
    `Browser: ${navigator.userAgent}`,
    `Screen: ${window.innerWidth}x${window.innerHeight}, `
      + `${window.devicePixelRatio || 1}x, `
      + `${matchMedia("(pointer: coarse)").matches ? "touch" : "mouse"}`,
    `Saving: ${storageState(store)}`,
    `Profiles saved here: ${savedCount ?? "unknown"}`,
    `Last error: ${lastError || "none this visit"}`,
  ];
  return lines.join("\n");
}

function storageState(store) {
  if (!store) return "NOT WORKING (private window, or site data switched off)";
  return store.locked ? "working, locked with a passphrase" : "working";
}


/** The footer: version, and the button that opens the report.
 *
 *  `issuesUrl` is where a report goes. Passed in rather than written here so
 *  that moving the project does not mean editing two files.
 */
export function footer(store, savedCount, issuesUrl, make) {
  const { el, put, button } = make;

  const bar = el("footer", "note faint about");
  const opened = el("div");

  put(bar,
      el("span", null, `Invenfloor ${VERSION} · everything you save stays `
                     + `in this browser · `),
      button("Something wrong?", "quiet small", () => {
        if (opened.firstChild) { opened.replaceChildren(); return; }
        put(opened, problemPanel(store, savedCount, issuesUrl, make));
      }));

  return put(el("div"), bar, opened);
}

function problemPanel(store, savedCount, issuesUrl, make) {
  const { el, put, button } = make;
  const card = el("div", "card");

  put(card, el("p", "note",
    "Copy the text below and send it over. It says which browser you are on "
    + "and whether this page was able to save anything, which is usually the "
    + "answer. It contains nothing about what is in your inventory."));

  const box = el("textarea", "report");
  box.value = report(store, savedCount);
  box.rows = 8;
  box.readOnly = true;
  box.spellcheck = false;
  put(card, box);

  const says = el("span", "note faint");
  const copy = button("Copy it", "small", async () => {
    try {
      await navigator.clipboard.writeText(box.value);
      says.textContent = "Copied.";
    } catch {
      // Clipboard access is refused on an insecure page and in a few
      // browsers. Selecting the text is something they can do by hand, so
      // do that for them rather than leaving a button that does nothing.
      box.select();
      says.textContent = "Press Ctrl+C or Cmd+C to copy.";
    }
  });

  const row = put(el("div", "row"), copy);
  if (issuesUrl) {
    const link = el("a", "note", "Open the issue tracker");
    link.href = issuesUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    put(row, link);
  }
  put(row, says);
  return put(card, row);
}
