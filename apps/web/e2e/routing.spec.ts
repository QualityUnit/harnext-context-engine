import { test, expect, type Page } from "@playwright/test";

// A logged-in session so useUser() doesn't bounce us to /login. Injected before
// any app script runs, on every navigation in the context.
const SESSION = {
  token: "test-token",
  user: {
    id: "u1",
    email: "dev@example.com",
    name: "Dev User",
    avatar_url: null,
    created_at: "2026-01-01T00:00:00Z",
  },
};

test.beforeEach(async ({ context }) => {
  await context.addInitScript((session) => {
    localStorage.setItem("mg.session", JSON.stringify(session));
  }, SESSION);
});

const title = (page: Page) => page.locator("h1.view-title");
const navLink = (page: Page, name: string) =>
  page.locator(".sidebar").getByRole("link", { name, exact: true });

// Each view: its route, the sidebar link that reaches it, and its heading.
const VIEWS = [
  { nav: "Dashboard", path: "/projects/p1", heading: "MCP server requests" },
  { nav: "Sources", path: "/projects/p1/sources", heading: "Context sources" },
  { nav: "Files", path: "/projects/p1/files", heading: "Context filesystem" },
  { nav: "Connect", path: "/projects/p1/connect", heading: "Connect a harness" },
  { nav: "Settings", path: "/projects/p1/settings", heading: "Settings" },
];

test("each view is reachable by clicking its sidebar link, and the URL + active state follow", async ({
  page,
}) => {
  await page.goto("/projects/p1");
  await expect(title(page)).toHaveText("MCP server requests");

  for (const view of VIEWS) {
    await navLink(page, view.nav).click();
    await expect(page).toHaveURL(new RegExp(`${view.path}$`));
    await expect(title(page)).toHaveText(view.heading);
    // The link for the current view is highlighted; the others are not.
    await expect(navLink(page, view.nav)).toHaveClass(/active/);
    for (const other of VIEWS.filter((v) => v.nav !== view.nav)) {
      await expect(navLink(page, other.nav)).not.toHaveClass(/active/);
    }
  }
});

test("every view has its own deep-linkable, reloadable route", async ({ page }) => {
  for (const view of VIEWS) {
    await page.goto(view.path); // hard navigation, as if pasted / reloaded
    await expect(page).toHaveURL(new RegExp(`${view.path}$`));
    await expect(title(page)).toHaveText(view.heading);
    await expect(navLink(page, view.nav)).toHaveClass(/active/);
  }
});

test("browser back/forward moves between view routes", async ({ page }) => {
  await page.goto("/projects/p1");
  await navLink(page, "Sources").click();
  await expect(title(page)).toHaveText("Context sources");
  await navLink(page, "Settings").click();
  await expect(title(page)).toHaveText("Settings");

  await page.goBack();
  await expect(page).toHaveURL(/\/projects\/p1\/sources$/);
  await expect(title(page)).toHaveText("Context sources");

  await page.goBack();
  await expect(page).toHaveURL(/\/projects\/p1$/);
  await expect(title(page)).toHaveText("MCP server requests");

  await page.goForward();
  await expect(page).toHaveURL(/\/projects\/p1\/sources$/);
  await expect(title(page)).toHaveText("Context sources");
});

test("switching projects lands on the target project's dashboard route", async ({ page }) => {
  await page.goto("/projects/p1/sources");
  await expect(title(page)).toHaveText("Context sources");

  // Open the workspace switcher and pick the other project.
  await page.locator(".ws-btn").click();
  await page.locator(".ws-item", { hasText: "side-project" }).click();

  await expect(page).toHaveURL(/\/projects\/p2$/);
  await expect(title(page)).toHaveText("MCP server requests");
});
