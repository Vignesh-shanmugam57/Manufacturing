import { expect, test } from "@playwright/test";

// End-to-end tests of the plant team's app: sign in, issues, plant overview, plant map, data connectors, agent activity and the chat.
// They drive the real app (React -> FastAPI -> PostgreSQL, and Domo AI for the chat). The mock team and incident history are
// re-created once before the tests, so the Issues board always has the same story: 6 open issues, one of them critical.
const SHOTS = "test-results/screens";
const BASE = process.env.E2E_BASE_URL || "http://localhost:5173";
const unique = (prefix) => `${prefix}.${Date.now()}.${Math.floor(Math.random() * 1e4)}@example.com`;
const nav = (page, name) => page.locator(".nav").getByRole("button", { name });

async function signIn(page, { email = unique("e2e"), name = "Jordan Smith" } = {}) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("Role").selectOption("Utilities engineer");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.locator(".user-name")).toHaveText(name);
  return email;
}

// the setup pages live in a collapsible menu group
async function openSetup(page) {
  const toggle = page.getByRole("button", { name: "Setup and information" });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
}

test.beforeAll(async () => {
  test.setTimeout(240_000);
  const login = await fetch(`${BASE}/api/users/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: unique("e2e.seed"), name: "E2E Seed", role: "Utilities engineer" }),
  });
  const { id } = await login.json();
  const seeded = await fetch(`${BASE}/api/twin/mock/seed`, { method: "POST", headers: { "X-User-Id": id } });
  expect(seeded.status).toBe(200);
});

test("sign in lands on Issues, and the menu is the plant team first, then setup", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".login-brand")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/01-login.png` });
  await signIn(page);
  await expect(page.locator("h2", { hasText: "Issues" })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator(".nav-section", { hasText: "Plant team" })).toBeVisible();
  const team = page.locator('.nav[aria-label="Plant"] .nav-item');
  await expect(team).toHaveCount(3);
  for (const [i, label] of ["Issues", "Plant map", "Plant overview"].entries()) await expect(team.nth(i)).toContainText(label);
  await expect(page.locator(".new-chat")).toContainText("Ask the agent");
  await expect(page.locator('.nav[aria-label="Setup and information"] .nav-item')).toHaveCount(0);   // collapsed until opened
  await openSetup(page);
  const setup = page.locator('.nav[aria-label="Setup and information"] .nav-item');
  for (const [i, label] of ["Data connectors", "Agent activity", "How it works"].entries()) await expect(setup.nth(i)).toContainText(label);
  await page.screenshot({ path: `${SHOTS}/01b-menu.png`, fullPage: true });
});

test("issues: what is wrong, where, who has to go, how long, and what to do", async ({ page }) => {
  await signIn(page);
  await expect(page.locator(".iss-tile")).toHaveCount(6, { timeout: 60_000 });
  await expect(page.locator(".iss-tile").first()).toContainText("Open issues");
  const rows = page.locator(".iss-row");
  await expect(rows).toHaveCount(6);
  const critical = page.locator('.iss-row[data-sev="CRITICAL"]');
  await expect(critical).toHaveCount(1);
  await expect(critical).toContainText("Where:");                       // zone and equipment
  await expect(critical).toContainText("ext ");                         // who, with an extension
  await expect(critical).toContainText("Do:");                          // what to do
  await expect(critical.locator(".iss-timer b")).toHaveText(/\d+m \d+s|\d+h \d+m|\d+d \d+h/);   // how long it has been open
  await critical.click();
  const detail = page.locator(".iss-detail");
  for (const heading of ["What happened", "What to do", "Where and who", "Timeline"]) await expect(detail).toContainText(heading);
  await page.getByRole("button", { name: "Major", exact: true }).click();   // filter by severity
  await expect(page.locator(".iss-row")).toHaveCount(2);
  await page.getByRole("button", { name: "Closed", exact: true }).click();  // the history
  await expect(page.locator(".iss-row").first()).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${SHOTS}/02-issues.png`, fullPage: true });
});

test("issues: acknowledging an issue moves it on and is written to its timeline", async ({ page }) => {
  await signIn(page, { name: "Casey Planner" });
  const critical = page.locator('.iss-row[data-sev="CRITICAL"]');
  await expect(critical).toHaveCount(1, { timeout: 60_000 });
  await critical.click();
  await expect(page.locator(".iss-detail")).toContainText("New, not acknowledged");
  await page.locator(".iss-detail").getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.locator(".iss-detail .iss-pill").first()).toContainText("Acknowledged", { timeout: 30_000 });
  await expect(page.locator(".iss-detail .iss-tl")).toContainText("Casey Planner");
  await expect(page.locator(".iss-detail").getByRole("button", { name: "Acknowledge" })).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/03-acknowledged.png`, fullPage: true });
});

test("plant overview: every utility's status, usage against normal, and what needs attention", async ({ page }) => {
  await signIn(page);
  await nav(page, /Plant overview/).click();
  await expect(page.locator(".ov-ut")).toHaveCount(7, { timeout: 60_000 });
  await expect(page.locator(".ov-ut", { hasText: "Steam" })).toContainText("All normal");
  await expect(page.locator(".ov-ut", { hasText: "Gas" })).toContainText("open issue");
  const usage = page.locator('[aria-label="Usage"]');
  await expect(usage.locator("svg.ov-chart").first()).toBeVisible({ timeout: 60_000 });
  // the worst utility (gas) is selected first: its abnormal reading is drawn against its limit, so the problem is visible
  await expect(usage.locator("svg.ov-chart")).toHaveCount(2);
  await expect(usage).toContainText("against its limit");
  await expect(usage).toContainText("Usage itself is normal");
  await expect(usage).toContainText("Mock usage data");
  await page.locator(".ov-ut", { hasText: "Compressed air" }).click();
  await expect(usage).toContainText("Compressed air");
  await usage.getByRole("button", { name: "Last 7 days" }).click();
  await expect(usage.locator("svg.ov-chart").first().locator("rect")).toHaveCount(7);   // one bar per day
  await expect(page.locator('[aria-label="Needs attention"] li')).toHaveCount(3);
  await page.screenshot({ path: `${SHOTS}/04-overview.png`, fullPage: true });
});

test("plant map: an issue opens the 3D plant at its equipment, and the equipment is not shown as normal", async ({ page }) => {
  await signIn(page);
  await page.locator('.iss-row[data-sev="CRITICAL"]').click();
  await page.getByRole("button", { name: "Show on plant map" }).click();
  await expect(page.getByTestId("factory-3d").locator("canvas")).toBeVisible({ timeout: 60_000 });
  const panel = page.locator(".eqpanel");
  await expect(panel).toContainText("Gas Regulating Skid", { timeout: 60_000 });
  await expect(panel.locator(".lvl")).toContainText("Critical");            // an open issue is never shown as Normal
  await page.screenshot({ path: `${SHOTS}/05-map.png` });
});

test("data connectors: how connecting works, the catalog, and the connect wizard up to the mapping", async ({ page }) => {
  await signIn(page);
  await openSetup(page);
  await nav(page, /Data connectors/).click();
  await expect(page.locator(".cx-how li")).toHaveCount(4);
  await expect(page.locator("article.cx-card")).toHaveCount(13);
  await expect(page.locator("article.cx-card", { hasText: "PostgreSQL" })).toContainText("Available now");
  await expect(page.locator("article.cx-card", { hasText: "OPC UA" })).toContainText("Added per project");
  await page.locator("article.cx-card", { hasText: "Demo plant gateway" }).getByRole("button", { name: "Connect" }).click();
  const wizard = page.locator(".cx-modal");
  await expect(wizard).toContainText("Connect Demo plant gateway");
  await wizard.getByRole("button", { name: "Next" }).click();
  await wizard.getByRole("button", { name: "Test connection" }).click();
  await expect(wizard.locator(".cx-res.ok")).toContainText("demo gateway is reachable", { timeout: 60_000 });
  await wizard.getByRole("button", { name: "Next" }).click();
  await expect(wizard.locator(".cx-pill.ok")).toHaveCount(12, { timeout: 30_000 });   // every utility field matched automatically
  await page.screenshot({ path: `${SHOTS}/06-connectors.png`, fullPage: true });
  await wizard.getByRole("button", { name: "Cancel" }).click();                       // nothing is saved or pulled
  await expect(wizard).toHaveCount(0);
});

test("a system that needs a driver says so instead of pretending to connect", async ({ page }) => {
  await signIn(page);
  await openSetup(page);
  await nav(page, /Data connectors/).click();
  await page.locator("article.cx-card", { hasText: "OPC UA" }).getByRole("button", { name: "Connect" }).click();
  const wizard = page.locator(".cx-modal");
  await expect(wizard).toContainText("driver");
  await wizard.getByLabel(/^Server/).fill("opc.tcp://scada01:4840");
  await wizard.getByRole("button", { name: "Next" }).click();
  await wizard.getByRole("button", { name: "Test connection" }).click();
  await expect(wizard.locator(".cx-res.bad")).toContainText("driver", { timeout: 30_000 });
  await expect(wizard.getByRole("button", { name: "Next" })).toBeDisabled();
});

test("agent activity: what the agent did, and the nine steps behind an issue; history analysis is read-only", async ({ page }) => {
  await signIn(page);
  await openSetup(page);
  await nav(page, /Agent activity/).click();
  await expect(page.locator(".aa-tile")).toHaveCount(5);
  await expect(page.locator(".aa-tile").last()).toContainText("actions on equipment");
  await expect(page.locator(".aa-tile").last().locator("b")).toHaveText("0");
  const feed = page.locator(".aa-feed button");
  await expect(feed.first()).toBeVisible({ timeout: 60_000 });
  await feed.nth(1).click();
  await expect(page.locator(".aa-steps li")).toHaveCount(9, { timeout: 30_000 });
  await expect(page.locator(".aa-table")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/07-agent-activity.png`, fullPage: true });
  await page.getByRole("button", { name: "History analysis" }).click();
  await expect(page.locator(".stage")).toHaveCount(6);
  await expect(page.getByRole("button", { name: "Run analysis" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run agent" })).toHaveCount(0);        // it never raises alerts any more
});

test("how it works: the flow plays by itself and can be stepped through", async ({ page }) => {
  await signIn(page);
  await openSetup(page);
  await nav(page, /How it works/).click();
  await expect(page.locator(".arch-node")).toHaveCount(10);
  const first = page.locator('.arch-node[aria-current="step"]');
  await expect(first).toHaveCount(1);
  const before = await first.getAttribute("aria-label");
  await expect.poll(async () => page.locator('.arch-node[aria-current="step"]').getAttribute("aria-label"), { timeout: 15_000 }).not.toBe(before);
  await page.locator(".arch-node", { hasText: "Verify" }).click();
  await expect(page.locator(".arch-detail h3")).toHaveText("Verify");
});

test("ask the agent: suggested plant questions, and an answer from the live issues", async ({ page }) => {
  await signIn(page);
  await page.locator(".new-chat").click();
  const chips = page.locator(".suggestions button");
  await expect(chips).toHaveCount(4);
  await expect(chips.first()).toContainText("What needs attention first right now");
  await chips.first().click();
  const answer = page.locator(".msg.bot .bot-bubble:not(.progress)").last();
  await expect(answer).toContainText(/ALT-\d{5}|no open issues/i, { timeout: 180_000 });
  await page.screenshot({ path: `${SHOTS}/08-chat.png`, fullPage: true });
});

// ------------------------------------------------------------------ chat housekeeping, theme and mobile (unchanged behaviour)
const userId = (page) => page.evaluate(() => JSON.parse(localStorage.getItem("utilities-agent.user")).id);
const lastAnswer = (page) => page.locator(".msg.bot .bot-bubble:not(.progress)").last();

test("control requests are refused and handed to certified operators", async ({ page }) => {
  await signIn(page, { name: "Sam Patel" });
  await page.locator(".new-chat").click();
  await page.getByLabel("Message the utilities agent")
    .fill("Increase the compressed air pressure setpoint to 8 bar and start the standby compressor now.");
  await page.getByRole("button", { name: "Send message" }).click();
  const answer = lastAnswer(page);
  await expect(answer).toContainText(/operator/i, { timeout: 240_000 });
  await expect(answer).toContainText(/(cannot|can't|not able|unable|don't have|do not have)/i);
  await page.screenshot({ path: `${SHOTS}/09-control-refused.png` });
});

test("chats can be renamed and deleted, and are private to each user", async ({ page }) => {
  await signIn(page, { name: "Riley Owner" });
  const id = await userId(page);
  for (const title of ["Compressed air review", "Chiller follow-up"]) {
    const r = await page.request.post("/api/sessions", { data: { title }, headers: { "X-User-Id": id } });
    expect(r.status()).toBe(201);
  }
  await page.reload();
  await expect(page.locator(".session-item")).toHaveCount(2);

  const item = page.locator(".session-item", { hasText: "Compressed air review" });
  await item.hover();
  await item.getByRole("button", { name: "Rename chat" }).click();
  await page.getByLabel("Chat title").fill("Air header instability");
  await page.getByRole("button", { name: "Save title" }).click();
  await expect(page.locator(".session-title", { hasText: "Air header instability" })).toBeVisible();

  const victim = page.locator(".session-item", { hasText: "Chiller follow-up" });
  await victim.hover();
  await victim.getByRole("button", { name: "Delete chat" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.locator(".session-item")).toHaveCount(1);
  await page.reload();
  await expect(page.locator(".session-title")).toHaveText(["Air header instability"]);

  // Another user sees none of it.
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, { name: "Morgan Other" });
  await expect(page.locator(".sessions-empty")).toBeVisible();
  const other = await userId(page);
  const sessions = await (await page.request.get("/api/sessions", { headers: { "X-User-Id": other } })).json();
  expect(sessions).toEqual([]);
});

test("dark mode persists, sign out returns to login", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Switch to dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await nav(page, /Plant overview/).click();
  await expect(page.locator(".ov-ut")).toHaveCount(7, { timeout: 60_000 });
  await page.screenshot({ path: `${SHOTS}/10-overview-dark.png`, fullPage: true });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("mobile layout uses a slide-out menu and nothing overflows sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page);
  await expect(page.locator(".sidebar")).not.toBeInViewport();
  await expect(page.locator(".iss-row").first()).toBeVisible({ timeout: 120_000 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  await page.screenshot({ path: `${SHOTS}/11-mobile-issues.png`, fullPage: true });
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.locator(".sidebar")).toBeInViewport({ ratio: 1 });       // slide-in finished
  await nav(page, /Plant overview/).click();
  await expect(page.locator(".sidebar")).not.toBeInViewport();
  await expect(page.locator(".ov-ut")).toHaveCount(7, { timeout: 60_000 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  await page.screenshot({ path: `${SHOTS}/12-mobile-overview.png`, fullPage: true });
});

test("closing an issue is reflected on every screen: list, summary, overview, plant map and the sidebar badge", async ({ page }) => {
  test.setTimeout(300_000);
  const email = await signIn(page, { name: "Morgan Closer" });
  const { id } = await (await fetch(`${BASE}/api/users/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, name: "Morgan Closer", role: "Utilities engineer" }) })).json();
  await fetch(`${BASE}/api/twin/mock/seed`, { method: "POST", headers: { "X-User-Id": id } });   // start from the same six open issues every time
  await page.reload();
  const rows = page.locator(".iss-row");
  await expect(rows).toHaveCount(6, { timeout: 60_000 });
  const gas = page.locator('.iss-row[data-sev="CRITICAL"]');
  await expect(gas).toHaveCount(1);
  await gas.click();
  const detail = page.locator(".iss-detail");
  const ack = detail.getByRole("button", { name: "Acknowledge" });
  if (await ack.count()) { await ack.click(); await expect(ack).toHaveCount(0, { timeout: 30_000 }); }
  await detail.getByRole("textbox", { name: "Note" }).fill("Regulator replaced and leak tested");
  await detail.getByRole("button", { name: "Record the fix" }).click();
  await expect(detail.locator(".iss-tl")).toContainText("Regulator replaced", { timeout: 90_000 });
  // verification needs fresh, stable readings; keep asking until the system accepts it
  await expect(async () => {
    const vb = detail.getByRole("button", { name: "Verify with telemetry" });
    if (await vb.count()) await vb.click({ timeout: 10_000 });
    await expect(rows).toHaveCount(5, { timeout: 4_000 });
  }).toPass({ timeout: 200_000, intervals: [5_000] });
  await expect(page.locator(".iss-tile").first()).toContainText("5");              // the summary follows without a reload
  await expect(page.locator('.iss-row[data-sev="CRITICAL"]')).toHaveCount(0);
  await nav(page, /Plant overview/).click();
  await expect(page.locator(".ov-ut", { hasText: "Gas" })).toContainText("All normal", { timeout: 30_000 });
  await expect(page.locator('[aria-label="Needs attention"]')).not.toContainText("Gas");
  await nav(page, /Plant map/).click();
  await expect(page.locator(".topbar, header").first()).not.toContainText("Critical 1");
  await page.screenshot({ path: `${SHOTS}/13-closed-everywhere.png`, fullPage: true });
});
