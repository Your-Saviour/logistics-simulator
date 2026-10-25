# Facility rendering reference

`facility-held.png` is the uncached production renderer at commit `cb67a3f`,
captured in Docker Chromium 156 with ANGLE/SwiftShader on ARM64. It uses the
500-unit held fixture in `handling-scene.spec.ts`, a 1440×900 viewport and an
831×538 canvas. Antialiasing is disabled and DPR is 1.

This image predates framebuffer caching. The cache regression compares current
pixels against it and separately checks camera changes, pointer selection,
stock removal, context restoration and direct rendering without a stencil
buffer. Update the reference only for an intentional visual change, using the
same fixture and browser configuration.

`facility-floor.png` is the fixed outbound-floor/marker region (canvas x=600,
y=320, width=90, height=60) from that validated held view. The busy benchmark
checks this region before and after measurement, so a disappearing facility
cannot pass merely by reporting 500 logical units and drawing robots.
