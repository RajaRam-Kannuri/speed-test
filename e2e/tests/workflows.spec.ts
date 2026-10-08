import { expect, test, type Page } from "@playwright/test";

// The three acceptance workflows, driven through the UI against the Acme CRM sample app.
// Nothing is mocked: discovery, generation and runs use the real API, worker and Playwright engine.

const SAMPLE = process.env.E2E_SAMPLE_URL || "http://127.0.0.1:8100";
const stamp = Date.now();
const user = { name: "Priya Tester", email: `e2e-${stamp}@example.com`, password: "E2e-Passw0rd-123", org: "Lorven QA" };

test.describe.configure({ mode: "serial" });

let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});

test.afterAll(async () => {
  await page.close();
});

async function waitForRunToFinish(p: Page) {
  await expect(p).toHaveURL(/\/runs\/[0-9a-f-]{36}/);
  await expect(p.getByText(/Running in an isolated browser/)).toBeHidden({ timeout: 180_000 });
}

test("register and create a project", async () => {
  await page.goto("/register");
  await page.getByLabel("Your name").fill(user.name);
  await page.getByLabel("Work email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByLabel("Company or team name").fill(user.org);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: /Welcome, Priya/ })).toBeVisible();
  await page.getByLabel("Project name").fill("Acme CRM");
  await page.getByLabel("Application URL (optional)").fill(SAMPLE);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByTestId("project-switcher")).toContainText("Acme CRM");
  await expect(page.getByText("Create your first test")).toBeVisible();
});

test("Workflow A: test a website end to end", async () => {
  await page.getByTestId("create-test").click();
  await page.getByRole("link", { name: /Test a Website/ }).click();
  await expect(page.getByRole("heading", { name: "Test a website" })).toBeVisible();
  await page.getByLabel("Website URL").fill(SAMPLE + "/");
  await page.getByText("The site needs a sign-in").click();
  await page.getByLabel("Sign-in page").fill("/login");
  await page.getByLabel("Username or email").fill("demo@acme.test");
  await page.getByLabel("Password").fill("Passw0rd!");
  const discover = page.getByRole("button", { name: "Discover website" });
  await expect(discover).toBeDisabled(); // authorisation confirmation is required
  await page.getByTestId("authorize-checkbox").check();
  await discover.click();

  await expect(page.getByText(/Discovered \d+ pages/)).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("Signed in")).toBeVisible();
  await expect(page.getByTestId("discovered-pages").locator("img").first()).toBeVisible();

  await page.getByTestId("generate-tests").click();
  const table = page.getByTestId("generated-tests");
  await expect(table).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/\d+ test cases generated/)).toBeVisible();
  await expect(table.getByText("Verify login with valid credentials")).toBeVisible();
  // Generated tests have not run yet.
  await expect(table.getByText("Generated").first()).toBeVisible();

  // Review one test's steps before running.
  await table.getByRole("button", { name: "Verify login with valid credentials" }).click();
  await expect(table.getByText("{{password}}").first()).toBeVisible();

  await page.getByTestId("run-tests").click();
  await waitForRunToFinish(page);
  const total = Number(await page.getByTestId("stat-tests").innerText());
  expect(total).toBeGreaterThan(10);
  await expect(page.getByTestId("stat-passed")).toHaveText(String(total));
  await expect(page.getByTestId("stat-failed")).toHaveText("0");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(/Run [0-9a-f]{8}/);
  // Evidence from the real run: steps and a screenshot.
  const detail = page.getByTestId("result-detail");
  await expect(detail.getByRole("heading", { name: "Steps", exact: true })).toBeVisible();
  await expect(detail.locator("img").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /HTML report/ })).toBeVisible();
});

test("Workflow B: test an API end to end", async () => {
  await page.getByTestId("create-test").click();
  await page.getByRole("link", { name: /Test an API/ }).click();
  await page.getByLabel("OpenAPI / Swagger URL").fill(SAMPLE + "/openapi.json");
  await page.getByLabel("API token (optional)").fill("demo-token");
  await page.getByRole("button", { name: "Import API" }).click();
  const endpoints = page.getByTestId("endpoints");
  await expect(endpoints).toBeVisible({ timeout: 30_000 });
  await expect(endpoints.getByText("/api/customers/{customer_id}").first()).toBeVisible();
  await page.getByTestId("generate-api-tests").click();
  const table = page.getByTestId("generated-tests");
  await expect(table).toBeVisible({ timeout: 60_000 });
  await expect(table.getByText("POST /api/customers rejects requests without credentials")).toBeVisible();
  await expect(table.getByText("POST /api/customers rejects a duplicate resource")).toBeVisible();
  await page.getByTestId("run-tests").click();
  await waitForRunToFinish(page);
  const total = Number(await page.getByTestId("stat-tests").innerText());
  expect(total).toBeGreaterThanOrEqual(20);
  await expect(page.getByTestId("stat-passed")).toHaveText(String(total));
  // Request/response evidence for API results.
  await expect(page.getByTestId("result-detail").getByRole("heading", { name: "API requests" })).toBeVisible();
});

test("Workflow C: natural-language test with the assistant", async () => {
  await page.goto("/assistant");
  const instruction = "Open the application, log in with valid credentials, navigate to the dashboard, create a new customer, and verify that the customer appears in the customer list.";
  await page.getByLabel("Message").fill(instruction);
  await page.getByTestId("send-message").click();
  const plan = page.getByTestId("plan-card").last();
  await expect(plan).toBeVisible({ timeout: 60_000 });
  await expect(plan.getByTestId("step-row").first()).toBeVisible();
  const steps = await plan.getByTestId("step-row").count();
  expect(steps).toBeGreaterThan(8);
  // Credentials were saved by Workflow A, so no prerequisites are missing.
  await expect(plan.getByText("Test data needed before running")).toHaveCount(0);

  // Review: edit a step (reorder is covered by the builder test), then validate the generated code.
  await plan.getByTestId("validate-plan").click();
  await expect(plan.getByText("Playwright code generated and compiled.")).toBeVisible({ timeout: 60_000 });
  await plan.getByTestId("run-plan").click();
  const run = page.getByTestId("assistant-run").last();
  await expect(run).toBeVisible();
  await expect(run.getByText("Passed")).toBeVisible({ timeout: 120_000 });
  await expect(run.getByText("1/1 passed")).toBeVisible();

  await page.getByLabel("Message").fill("Why did it fail?");
  await page.getByTestId("send-message").click();
  await expect(page.getByText(/There is nothing to analyse/)).toBeVisible();
});

test("Visual builder: build, validate and run a test without code", async () => {
  await page.goto("/tests/new");
  await page.getByLabel("Test name").fill("About page shows company history");
  await page.getByTestId("add-step").click();
  await page.getByTestId("action-palette").getByRole("button", { name: "Navigate", exact: true }).click();
  await page.getByLabel("URL or path").fill("/about");
  await page.getByTestId("add-step").click();
  await page.getByTestId("action-palette").getByRole("button", { name: "Assert text", exact: true }).click();
  await page.getByLabel("Expected text").fill("since 2019");
  await page.getByTestId("add-step").click();
  await page.getByTestId("action-palette").getByRole("button", { name: "Assert title", exact: true }).click();
  await page.getByLabel("Title contains").fill("About");
  // Reorder: move the title check above the text check.
  await page.getByRole("button", { name: "Move up" }).nth(2).click();
  await expect(page.getByTestId("step-row").nth(1)).toContainText("Assert title");
  await page.getByTestId("save-test").click();
  await expect(page).toHaveURL(/\/tests\/[0-9a-f-]{36}/);
  await page.getByTestId("validate-test").click();
  await expect(page.getByText(/Valid: the generated Playwright code compiled/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("tab", { name: "Code" }).click();
  await expect(page.getByTestId("generated-code")).toContainText('llx.navigate("/about")');
  await page.getByRole("tab", { name: "Steps" }).click();
  await page.getByTestId("run-tests").click();
  await waitForRunToFinish(page);
  await expect(page.getByTestId("stat-passed")).toHaveText("1");
});

test("Dashboard and reports show real results", async () => {
  await page.goto("/");
  await expect(page.getByText("Results over the last 14 days")).toBeVisible();
  await expect(page.getByRole("img", { name: /Test results per day/ })).toBeVisible();
  await page.goto("/reports");
  await page.getByRole("button", { name: "Show table" }).click();
  await expect(page.getByRole("link", { name: "HTML" }).first()).toBeVisible();
  await page.goto("/settings");
  await page.getByRole("tab", { name: "Audit log" }).click();
  await expect(page.getByTestId("audit-log")).toContainText("discovery.started");
});
