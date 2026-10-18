// Accessibility audit: runs axe-core (WCAG 2.0/2.1 A and AA rules plus best practices)
// on every type of page at desktop and phone widths, and prints each rule that fails.
//
//   npm install --no-save playwright@1.48 axe-core@4.10.2 && npx playwright install chromium
//   node tools/a11y_audit.js http://localhost:8000
//
// Exit status 1 when any rule fails. Keyboard, reflow and contrast checks done by hand
// are described in docs/ACCESSIBILITY.md.
const { chromium } = require("playwright");
const fs = require("fs");

const base = (process.argv[2] || "http://localhost:8000").replace(/\/$/, "");
const axe = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const pages = [
  "/", "/?lang=fr", "/search/?q=housing", "/search/?q=logement&text=fr&lang=fr",
  "/sittings/", "/members/", "/votes/", "/bills/", "/trends/?t1=housing&t2=inflation",
  "/language/", "/topics/", "/new/", "/accessibility/", "/accessibility/?lang=fr",
  "/api/docs/", "/no-such-page/",
];

(async () => {
  const browser = await chromium.launch();
  // Also one page of each kind with data: the first link of each list page.
  const probe = await browser.newPage();
  for (const [list, pattern] of [["/sittings/", "/sittings/"], ["/members/", "/members/"],
    ["/votes/", "/votes/"], ["/bills/", "/bills/"], ["/topics/", "/topics/"]]) {
    await probe.goto(base + list);
    const href = await probe.evaluate((p) => {
      const a = [...document.querySelectorAll("main a")].find((x) => x.pathname.includes(p) && x.pathname.split("/").filter(Boolean).length > 1);
      return a ? a.pathname : null;
    }, pattern);
    if (href) pages.push(href.replace(/^.*?(\/(sittings|members|votes|bills|topics)\/)/, "$1"));
  }
  await probe.close();

  const failures = {};
  for (const width of [1280, 375]) {
    for (const path of pages) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.goto(base + path, { waitUntil: "load" });
      await page.addScriptTag({ content: axe });
      const result = await page.evaluate(() => axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] },
      }));
      for (const v of result.violations) {
        failures[v.id] = failures[v.id] || { help: v.help, impact: v.impact, where: new Set() };
        failures[v.id].where.add(`${path} @${width}px`);
      }
      await page.close();
    }
  }
  await browser.close();
  console.log(`${pages.length} pages × 2 widths checked.`);
  for (const [id, f] of Object.entries(failures)) {
    console.log(`\n${id} (${f.impact}): ${f.help}\n  ${[...f.where].join("\n  ")}`);
  }
  if (!Object.keys(failures).length) console.log("No failures.");
  process.exit(Object.keys(failures).length ? 1 : 0);
})();
