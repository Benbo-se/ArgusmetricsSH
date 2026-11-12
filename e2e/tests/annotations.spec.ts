import { test, expect } from '@playwright/test';
import { createUserWithWebsite } from '../helpers/auth';

/**
 * Notes on the traffic graph (#220), in a real browser.
 *
 * The server side is covered by pytest. What only a browser can say is
 * whether the list under the graph works under Alpine's CSP build, which
 * renders nothing and only warns when an expression is one it cannot read,
 * and whether a note ends up on the right point of the chart, which is drawn
 * on a canvas and has no markup to look at.
 */

// Typed into the note on purpose: it has to come out as text everywhere.
const HOSTILE = '<img src=x onerror="window.__noteRan = true"> New start page';

async function signIn(page: any, request: any) {
  const { sessionToken, websiteId } = await createUserWithWebsite(request);
  await page.goto('/login');
  await page.evaluate((t: string) => { document.cookie = `session_token=${t}; path=/`; }, sessionToken);
  return websiteId;
}

/** What the chart says about one point: its notes in the tooltip, and
 *  whether the marker's dot is painted at the top of that point. */
async function pointOnChart(page: any, index: number) {
  return page.evaluate((i: number) => {
    const chart = (window as any).Chart.getChart('pageviews-chart');
    const at = i < 0 ? chart.data.labels.length + i : i;
    chart.tooltip.setActiveElements([{ datasetIndex: 0, index: at }], { x: 0, y: 0 });
    chart.update('none');
    const notes = (chart.tooltip.beforeBody || []).join(' ');
    chart.tooltip.setActiveElements([], { x: 0, y: 0 });
    chart.update('none');
    // Paint now. While anything is still animating (the line drawing itself
    // in, the tooltip fading) update() leaves the painting to the next
    // frame, and the pixel below would be read from the frame before: this
    // test once saw a marker that had already been deleted.
    chart.draw();

    const ratio = chart.currentDevicePixelRatio || 1;
    const x = Math.round(chart.scales.x.getPixelForValue(at) * ratio);
    const y = Math.round(chart.chartArea.top * ratio);
    const [r, g, b, a] = chart.ctx.getImageData(x, y, 1, 1).data;
    // The marker is the theme's warn colour: more red than blue, and opaque.
    // The line and its fill are the brand's blue, and the card is white.
    const marked = a > 200 && r > b + 40;
    return { notes, marked, points: chart.data.labels.length };
  }, index);
}

async function addNote(page: any, text: string) {
  await page.getByRole('button', { name: 'Add note' }).first().click();
  await page.locator('#note-text').pressSequentially(text, { delay: 5 });
  await page.locator('form').filter({ has: page.locator('#note-text') })
    .getByRole('button', { name: 'Add note' }).click();
}

test('a note is added, shown on its day, changed and deleted', async ({ page, request }) => {
  const problems: string[] = [];
  page.on('console', (m: any) => {
    if (m.type() === 'error' || /Alpine/i.test(m.text())) problems.push(m.text());
  });
  page.on('pageerror', (e: any) => problems.push(String(e)));

  const websiteId = await signIn(page, request);
  await page.goto(`/dashboard/website/${websiteId}`);
  const rows = page.locator('[data-chart-notes] li');

  await expect(page.getByText('No notes in this period.')).toBeVisible();
  expect((await pointOnChart(page, -1)).marked, 'a marker with no note').toBe(false);

  // The day field starts on the last day shown, which is today.
  await addNote(page, HOSTILE);
  await expect(rows).toHaveCount(1, { timeout: 8000 });
  await expect(rows.first()).toContainText(HOSTILE);
  expect(await rows.locator('img').count(), 'the note became markup').toBe(0);
  expect(await page.evaluate(() => (window as any).__noteRan), 'the note ran as script').toBeUndefined();

  // On the chart: today's point, and not yesterday's.
  let today = await pointOnChart(page, -1);
  expect(today.notes).toContain('New start page');
  expect(today.notes).toContain('<img');
  expect(today.marked, 'no marker on the day of the note').toBe(true);
  const yesterday = await pointOnChart(page, -2);
  expect(yesterday.notes).toBe('');
  expect(yesterday.marked, 'a marker on a day without a note').toBe(false);

  // The chart is rebuilt when the metric changes. The note has to survive it.
  await page.locator('[data-chart-metric="views"]').click();
  expect((await pointOnChart(page, -1)).notes).toContain('New start page');

  // It was saved, not only shown.
  await page.reload();
  await expect(rows).toHaveCount(1);
  expect((await pointOnChart(page, -1)).marked).toBe(true);

  // Change it.
  await rows.first().getByRole('button', { name: 'Edit note' }).click();
  await expect(page.locator('#note-text')).toHaveValue(HOSTILE);
  await page.locator('#note-text').fill('Campaign started');
  await page.getByRole('button', { name: 'Save note' }).click();
  await expect(rows.first()).toContainText('Campaign started');
  await expect(rows).toHaveCount(1);
  today = await pointOnChart(page, -1);
  expect(today.notes).toContain('Campaign started');
  expect(today.notes).not.toContain('New start page');

  // Delete it: asked first, then gone from the list and from the chart.
  await rows.first().getByRole('button', { name: 'Delete note' }).click();
  await expect(rows.first()).toContainText('Delete this note?');
  await rows.first().getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(page.getByText('No notes in this period.')).toBeVisible();
  today = await pointOnChart(page, -1);
  expect(today.notes).toBe('');
  expect(today.marked, 'the marker outlived its note').toBe(false);

  await page.reload();
  await expect(page.getByText('No notes in this period.')).toBeVisible();
  expect(problems, 'the console was not clean').toEqual([]);
});

test('in the hourly graph a note sits where its day begins', async ({ page, request }) => {
  const websiteId = await signIn(page, request);
  await page.goto(`/dashboard/website/${websiteId}`);
  await addNote(page, 'Launch day');
  await expect(page.locator('[data-chart-notes] li')).toHaveCount(1, { timeout: 8000 });

  // Today by the hour: every point is the same day, and the note is on the
  // first of them only.
  await page.goto(`/dashboard/website/${websiteId}?range=today`);
  await expect(page.locator('[data-chart-notes] li')).toHaveCount(1);
  const first = await pointOnChart(page, 0);
  expect(first.notes).toContain('Launch day');
  expect(first.marked).toBe(true);
  if (first.points > 1) {
    const second = await pointOnChart(page, 1);
    expect(second.notes).toBe('');
  }

  // Yesterday has no note, so neither the list nor the chart shows one.
  await page.goto(`/dashboard/website/${websiteId}?range=yesterday`);
  await expect(page.getByText('No notes in this period.')).toBeVisible();
  expect((await pointOnChart(page, 0)).notes).toBe('');
});

test('a note outside the period shown is saved and says where it went', async ({ page, request }) => {
  const websiteId = await signIn(page, request);
  await page.goto(`/dashboard/website/${websiteId}`);

  await page.getByRole('button', { name: 'Add note' }).first().click();
  await page.locator('#note-day').fill('2020-02-02');
  await page.locator('#note-text').fill('Long ago');
  await page.locator('form').filter({ has: page.locator('#note-text') })
    .getByRole('button', { name: 'Add note' }).click();

  await expect(page.getByText('outside the period shown')).toBeVisible({ timeout: 8000 });
  await expect(page.getByText('No notes in this period.')).toBeVisible();

  await page.goto(`/dashboard/website/${websiteId}?range=custom&start_date=2020-02-01&end_date=2020-02-03`);
  await expect(page.locator('[data-chart-notes] li')).toContainText('Long ago');
  const day = await pointOnChart(page, 1);
  expect(day.notes).toContain('Long ago');
  expect(day.marked).toBe(true);
});
