import {test, expect} from '@playwright/test';

test('Chromium renders pixels through WebGL2', async ({page}) => {
  const result = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 32; canvas.height = 32;
    const gl = canvas.getContext('webgl2');
    if (!gl) return {available: false, renderer: null, pixel: []};
    gl.clearColor(1, 0, 0, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    const pixel = new Uint8Array(4);
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    return {available: true, renderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER), pixel: [...pixel]};
  });
  console.log('Docker Chromium rendering capability:', JSON.stringify(result));
  expect(result.available).toBe(true);
  expect(result.pixel).toEqual([255, 0, 0, 255]);
});
