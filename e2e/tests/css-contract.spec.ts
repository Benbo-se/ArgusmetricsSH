import { test, expect } from '@playwright/test';

/**
 * What the built stylesheet actually does, measured in a browser.
 *
 * Every other check on the CSS asks whether a class *exists*. That is not the
 * same question. Upgrading Tailwind 3 to 4 changed the default border colour
 * from gray-200 to currentColor, so `border` on its own went from light grey
 * to near black on 217 elements: card outlines, input fields, table dividers,
 * the whole dashboard. The class was present in both builds. The stylesheet
 * compiled without a warning. Five hundred tests passed. A diff of class names
 * showed nothing.
 *
 * The only thing that found it was computing the colour, which is what this
 * file does. It is deliberately small: a handful of declarations that the
 * design depends on and that a framework upgrade can move underneath it.
 *
 * A failure here is not a broken test. It is the next upgrade telling you
 * which default it changed.
 */

/** The stylesheet under test, wrapped around markup that uses it. */
async function measure(page: import('@playwright/test').Page, baseURL: string, html: string) {
    await page.setContent(`
        <!doctype html>
        <html><head><link rel="stylesheet" href="${baseURL}/static/css/tailwind.min.css"></head>
        <body class="text-gray-900">${html}</body></html>
    `, { waitUntil: 'load' });
}

const GRAY_200 = 'oklch(0.928 0.006 264.531)';

test.describe('The stylesheet keeps its defaults', () => {
    test('a bare border is light grey, not the text colour', async ({ page, baseURL }) => {
        await measure(page, baseURL!, '<div id="x" class="border p-4">card</div>');

        const colour = await page.evaluate(
            () => getComputedStyle(document.getElementById('x')!).borderColor
        );

        expect(colour, (
            'A bare `border` is taking the text colour. Tailwind 4 changed the '
            + 'default from gray-200 to currentColor; the compatibility rule in '
            + 'input.css restores it. 217 elements depend on this.'
        )).toBe(GRAY_200);
    });

    test('an explicit border colour agrees with the bare one', async ({ page, baseURL }) => {
        /** If these ever disagree, the default moved and the compatibility
         *  rule is no longer doing what it was written to do. */
        await measure(page, baseURL!,
            '<div id="a" class="border"></div><div id="b" class="border border-gray-200"></div>');

        const [bare, explicit] = await page.evaluate(() => [
            getComputedStyle(document.getElementById('a')!).borderColor,
            getComputedStyle(document.getElementById('b')!).borderColor,
        ]);

        expect(bare).toBe(explicit);
    });

    test('a border has a width', async ({ page, baseURL }) => {
        await measure(page, baseURL!, '<div id="x" class="border"></div>');

        const width = await page.evaluate(
            () => getComputedStyle(document.getElementById('x')!).borderWidth
        );
        expect(width).toBe('1px');
    });
});

test.describe('Classes built at runtime still resolve', () => {
    /**
     * These never appear as literal strings: they are assembled from a status
     * name or a column count while rendering. Tailwind cannot see them, so
     * they are listed in input.css. A pattern translated almost right is
     * silent, and shows up as an unstyled badge for whichever status nobody
     * happened to look at.
     */

    test('a status colour applies', async ({ page, baseURL }) => {
        await measure(page, baseURL!,
            '<div id="x" class="bg-green-500"></div><div id="y" class="text-rose-700"></div>');

        const [background, text] = await page.evaluate(() => [
            getComputedStyle(document.getElementById('x')!).backgroundColor,
            getComputedStyle(document.getElementById('y')!).color,
        ]);

        expect(background, 'bg-green-500 has no background').not.toBe('rgba(0, 0, 0, 0)');
        expect(text, 'text-rose-700 is not coloured').not.toBe('rgb(0, 0, 0)');
    });

    test('a column count actually makes that many columns', async ({ page, baseURL }) => {
        await measure(page, baseURL!,
            '<div id="x" class="grid grid-cols-12" style="width:1200px">'
            + Array.from({ length: 12 }, () => '<div></div>').join('')
            + '</div>');

        const columns = await page.evaluate(
            () => getComputedStyle(document.getElementById('x')!)
                .gridTemplateColumns.split(' ').length
        );

        expect(columns, 'grid-cols-12 did not produce twelve columns').toBe(12);
    });

    test('a ring colour from the safelist applies', async ({ page, baseURL }) => {
        await measure(page, baseURL!, '<div id="x" class="ring-1 ring-amber-400"></div>');

        const shadow = await page.evaluate(
            () => getComputedStyle(document.getElementById('x')!).boxShadow
        );

        expect(shadow, 'ring-amber-400 produced no ring').not.toBe('none');
    });
});

test.describe('Dark mode comes from theme.css, not from Tailwind', () => {
    /**
     * There is not one `dark:` utility in any template, and there never was:
     * the v3 build contained no dark variant either, so `darkMode: 'class'`
     * in the old config had been configuring nothing for as long as it
     * existed. Dark mode is custom properties under [data-theme="dark"].
     *
     * This checks the mechanism that is real. If a `dark:` utility is ever
     * written, input.css points the variant at the same attribute, so the two
     * agree rather than one following the operating system.
     */
    test('the theme attribute changes the tokens', async ({ page, baseURL }) => {
        await page.setContent(`
            <!doctype html>
            <html><head><link rel="stylesheet" href="${baseURL}/static/css/theme.css"></head>
            <body><div id="x">text</div></body></html>
        `, { waitUntil: 'load' });

        const light = await page.evaluate(() => {
            document.documentElement.setAttribute('data-theme', 'light');
            return getComputedStyle(document.body).backgroundColor;
        });
        const dark = await page.evaluate(() => {
            document.documentElement.setAttribute('data-theme', 'dark');
            return getComputedStyle(document.body).backgroundColor;
        });

        expect(dark, 'data-theme="dark" changed nothing').not.toBe(light);
    });
});
